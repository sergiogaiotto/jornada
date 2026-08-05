"""Casos de uso do M4 · Validação campo-a-campo & War Room (§8-M4) — via ports.

- `validar_campo` (POST /os/{id}/validacoes/{campo}): checagem automática contra a
  fonte (contagem/schema/frescor — fixtures §11 em dev/teste) e devolve a evidência.
- `abrir_pendencia_de_campo` (POST .../validacoes/{campo}/pendencia): pendência
  ancorada no campo via `origem = validacao:{campo}` (delegada ao ServicoOs do M1 —
  SLA/eventos/numeração inclusos).
- `criar_thread` (POST /os/{id}/threads): thread do War Room ANCORADA em campo.
- `executar_go` (POST /os/{id}/go): portão (A1 → GoBloqueado/409 listando pendências e
  campos não decididos), congela SLAs+versões em `os.frozen` (A2), gera o .docx
  executivo (A3 — armazenado em `documento_portao`) e avança fase → criada.
Eventos (§2.3): validacao.executada · thread.aberta · gate.passed|blocked ·
os.phase_changed · documento_portao.gerado.
"""

import hashlib
import uuid
from typing import Any

from application.ports.clock import ClockPort
from application.ports.documentos import GeradorDocumentoPort
from application.ports.fonte_validacao import FonteValidacaoPort
from application.ports.publicacoes import PublicacoesPort
from application.ports.repositorio_os import RepositorioOs
from application.ports.repositorio_validacao import RepositorioValidacao
from application.services.os_service import ServicoOs
from domain.campanha import fases
from domain.campanha.modelos import OS, EventoDominio, Pendencia
from domain.intake.completude import valor_do_campo
from domain.validacao import regras
from domain.validacao.erros import CampoForaDoBriefing, GoBloqueado
from domain.validacao.modelos import DocumentoPortao, ThreadWarRoom, ValidacaoCampo


class ServicoValidacao:
    def __init__(
        self,
        repositorio: RepositorioValidacao,
        repositorio_os: RepositorioOs,
        relogio: ClockPort,
        servico_os: ServicoOs,
        fonte: FonteValidacaoPort,
        publicacoes: PublicacoesPort,
        gerador: GeradorDocumentoPort,
    ) -> None:
        self._repo = repositorio
        self._repo_os = repositorio_os
        self._relogio = relogio
        self._servico_os = servico_os
        self._fonte = fonte
        self._publicacoes = publicacoes
        self._gerador = gerador

    # ------------------------------------------------------------- Validações
    def validar_campo(
        self, tenant_id: str, os_id: uuid.UUID, campo: str, *, actor: str
    ) -> ValidacaoCampo:
        """POST /os/{id}/validacoes/{campo} — checagem automática + evidência (§8-M4)."""
        os_ = self._exigir_campo(tenant_id, os_id, campo)
        agora = self._relogio.agora()
        veredito, checagens, evidencia = regras.executar_checagens(
            valor_do_campo(os_.briefing, campo), self._fonte.consultar(campo), agora
        )
        validacao = ValidacaoCampo(
            id=uuid.uuid4(),
            os_id=os_.id,
            campo=campo,
            veredito=veredito,
            checagens=checagens,
            evidencia=evidencia,
            created_at=agora,
        )
        self._repo.adicionar_validacao(validacao)
        self._evento(
            os_,
            "validacao.executada",
            {"validacao_id": str(validacao.id), "campo": campo, "veredito": veredito},
            actor,
        )
        return validacao

    def abrir_pendencia_de_campo(
        self,
        tenant_id: str,
        os_id: uuid.UUID,
        campo: str,
        *,
        titulo: str | None,
        descricao: str | None,
        severidade: str | None,
        bloqueante: bool,
        accountable: uuid.UUID | None,
        actor: str,
    ) -> Pendencia:
        """POST /os/{id}/validacoes/{campo}/pendencia — ancorada via origem (§8-M4)."""
        self._exigir_campo(tenant_id, os_id, campo)
        return self._servico_os.abrir_pendencia(
            tenant_id,
            os_id,
            titulo=titulo or f"Validação do campo {campo!r} reprovada",
            tipo="issue",
            descricao=descricao,
            severidade=severidade,
            bloqueante=bloqueante,
            bloqueia_etapa=None,
            accountable=accountable,
            origem=regras.origem_do_campo(campo),
            via_ai=False,
            actor=actor,
        )

    # ---------------------------------------------------------------- Threads
    def criar_thread(
        self,
        tenant_id: str,
        os_id: uuid.UUID,
        *,
        campo: str,
        titulo: str | None,
        mensagem: str,
        actor: str,
    ) -> ThreadWarRoom:
        """POST /os/{id}/threads — thread do War Room ancorada em campo do briefing."""
        os_ = self._exigir_campo(tenant_id, os_id, campo)
        agora = self._relogio.agora()
        thread = ThreadWarRoom(
            id=uuid.uuid4(),
            os_id=os_.id,
            campo=campo,
            titulo=titulo,
            mensagens=[{"autor": actor, "texto": mensagem, "em": agora.isoformat()}],
            status="aberta",
            created_at=agora,
        )
        self._repo.adicionar_thread(thread)
        self._evento(os_, "thread.aberta", {"thread_id": str(thread.id), "campo": campo}, actor)
        return thread

    # --------------------------------------------------------------------- GO
    def executar_go(
        self, tenant_id: str, os_id: uuid.UUID, *, actor: str
    ) -> tuple[OS, DocumentoPortao]:
        """POST /os/{id}/go — portão + congelamento + .docx + fase→criada (§8-M4)."""
        os_ = self._servico_os.obter_os(tenant_id, os_id)
        fases.validar_transicao(os_.fase, regras.FASE_POS_GO)  # GO só de `discutida`
        pendencias = self._repo_os.listar_pendencias(os_.id)
        validacoes = self._repo.listar_validacoes(os_.id)
        try:
            regras.validar_portao_go(os_.briefing, validacoes, pendencias)
        except GoBloqueado as exc:  # A1: 409 listando pendências + campos não decididos
            self._evento(
                os_,
                "gate.blocked",
                {
                    "portao": "go",
                    "campos_nao_decididos": exc.campos_nao_decididos,
                    "pendencias": [p.numero for p in exc.pendencias],
                },
                actor,
            )
            raise

        agora = self._relogio.agora()
        slas, clocks = regras.congelar_slas(os_.id, self._repo.listar_etapas(os_.id), agora)
        for clock in clocks:
            self._repo_os.adicionar_sla_clock(clock)
        frozen: dict[str, Any] = {  # §4.1: {agent_versions, policy_version, tarifario_id, slas}
            "agent_versions": self._publicacoes.versoes_agentes(),
            "policy_version": self._publicacoes.politica_publicada()["versao"],
            "tarifario_id": self._publicacoes.tarifario_id(),
            "slas": slas,
            "congelado_em": agora.isoformat(),
        }
        os_.frozen = frozen

        conteudo = self._gerador.documento_go(
            os_=os_, validacoes=validacoes, pendencias=pendencias, frozen=frozen
        )
        documento = DocumentoPortao(
            id=uuid.uuid4(),
            os_id=os_.id,
            portao="go",
            nome_arquivo=f"{os_.codigo}-portao-go.docx",
            conteudo=conteudo,
            hash=hashlib.sha256(conteudo).hexdigest(),
            created_at=agora,
        )
        self._repo.adicionar_documento(documento)

        fase_anterior = os_.fase
        os_.fase = regras.FASE_POS_GO
        os_.updated_at = agora
        self._repo_os.salvar_os(os_)

        self._evento(os_, "gate.passed", {"portao": "go", "fase_destino": os_.fase}, actor)
        self._evento(os_, "os.phase_changed", {"de": fase_anterior, "para": os_.fase}, actor)
        self._evento(
            os_,
            "documento_portao.gerado",
            {
                "documento_id": str(documento.id),
                "portao": "go",
                "nome_arquivo": documento.nome_arquivo,
                "hash": documento.hash,
            },
            actor,
        )
        return os_, documento

    # -------------------------------------------------------------- Interno
    def _exigir_campo(self, tenant_id: str, os_id: uuid.UUID, campo: str) -> OS:
        os_ = self._servico_os.obter_os(tenant_id, os_id)  # NaoEncontrado → 404
        if campo not in os_.briefing:
            raise CampoForaDoBriefing(
                f"Campo {campo!r} não existe no briefing da OS {os_.codigo} (âncora inválida)."
            )
        return os_

    def _evento(self, os_: OS, tipo: str, payload: dict[str, Any], actor: str) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=False,
                created_at=self._relogio.agora(),
            )
        )
