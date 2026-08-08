"""Casos de uso do M6 · Criativo (T6) — via ports (§8-M6).

- `gerar` (POST /os/{id}/criativos/gerar): pipeline visual→copy→content (LLM 120b —
  roster §7.2) monta a matriz canal×variante a partir do KV master; VALIDADORES
  DETERMINÍSTICOS reprovam SMS>160 (A1)/template WhatsApp/termos proibidos ANTES de
  persistir; LLM 20b acrescenta warnings não bloqueantes ("regras + warn LLM").
  Toda célula nasce `gerado` — o agente JAMAIS aprova (A3). Ledger `invocacao`
  (via_ai) por chamada de LLM + evento `agent.invoked` + trace Langfuse (§10.8).
- `decidir_celula` (PATCH /criativos/{id}/celula): aprovar/revisar por célula —
  aprovação é ato HUMANO analista+ (RBAC na rota + regra pura em domain, A3).
- `editar_kv_master` (PUT /criativos/{id}/kv-master): compliance determinístico do
  novo KV + marca TODAS as células derivadas `adaptado_revisar` (A2); warn 20b é
  best-effort (LLM fora → sem avisos; a edição NUNCA depende de LLM — §10.6).
- `kv_master_padrao` (GET /os/{id}/criativos/kv-padrao): KV de PARTIDA derivado do
  briefing da OS — código puro, ZERO LLM (A8 do UAT: o Estúdio abria com copy fixa da
  campanha de franquia mesmo em OS de outro tema).
Eventos (§2.3): agent.invoked · criativo.gerado · criativo.celula_alterada ·
criativo.kv_master_editado.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from agents import criativo as agentes_t6
from application.ports.clock import ClockPort
from application.ports.llm import LLMIndisponivel, LLMPort
from application.ports.observabilidade import TracerPort
from application.ports.publicacoes_ia import PublicacoesIaPort
from application.ports.repositorio_criativo import RepositorioCriativo
from application.services import portao_ia
from application.services.os_service import ServicoOs
from domain.agentes.modelos import Invocacao, agente_uuid
from domain.campanha.erros import NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio
from domain.criativo import kv_padrao, validadores
from domain.criativo import matriz as regras
from domain.criativo.erros import SaidaDoCriativoInvalida
from domain.criativo.modelos import (
    CANAIS_CRIATIVO,
    VARIANTES_DEFAULT,
    CelulaCriativo,
    Criativo,
)
from domain.ia_responsavel.erros import TetoDeTokensExcedido


class ServicoCriativo:
    def __init__(
        self,
        repositorio: RepositorioCriativo,
        relogio: ClockPort,
        servico_os: ServicoOs,
        llm: LLMPort,
        tracer: TracerPort,
        publicacoes_ia: PublicacoesIaPort,
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._servico_os = servico_os
        self._llm = llm
        self._tracer = tracer
        self._publicacoes_ia = publicacoes_ia  # política de IA PUBLICADA (§10.2)

    # ------------------------------------------------------------------ Gerar
    def gerar(
        self,
        tenant_id: str,
        os_id: uuid.UUID,
        *,
        kv_master: dict[str, Any],
        canais: list[str] | None,
        variantes: list[str] | None,
        instrucoes: str | None,
        portador_id: uuid.UUID,
    ) -> tuple[Criativo, list[str], list[Invocacao]]:
        """POST /os/{id}/criativos/gerar — matriz canal×variante a partir do KV master.

        §10.2 (C02): `instrucoes` é texto livre do usuário e alimenta os TRÊS agentes
        do pipeline (visual→copy→content) e as três linhas do ledger — saneada aqui,
        na fronteira, daqui para baixo só existe a versão sanitizada. `sanear` mantém o
        piso do C02 e passa a BLOQUEAR a chamada quando a política do tenant marcar a
        categoria detectada (§10.2)."""
        portao = portao_ia.de(  # política PUBLICADA + gasto do teto (J02)
            self._publicacoes_ia,
            tenant_id,
            gasto_tokens=portao_ia.gasto_do_dia(self._repo, self._relogio, tenant_id),
        )
        instrucoes = portao.sanear(instrucoes) if instrucoes else instrucoes
        os_ = self._servico_os.obter_os(tenant_id, os_id)  # NaoEncontrado → 404
        canais = list(canais or CANAIS_CRIATIVO)
        variantes = list(variantes or VARIANTES_DEFAULT)
        validadores.validar_kv_master(kv_master)  # compliance determinístico do KV

        # Pipeline visual → copy → content (§7.2); cada chamada vira invocacao+trace.
        invocacoes: list[Invocacao] = []
        contexto_anterior: dict[str, str] = {}
        texto_content = ""
        for nome in agentes_t6.AGENTES_T6:
            skill = agentes_t6.carregar(nome)
            mensagens = agentes_t6.montar_mensagens(
                skill,
                kv_master=kv_master,
                canais=canais,
                variantes=variantes,
                briefing=os_.briefing,
                instrucoes=instrucoes,
                contexto_anterior=dict(contexto_anterior) or None,
            )
            inicio = self._relogio.agora()
            # (f) §7.2: perfil do roster CONFERIDO contra a política antes da chamada.
            portao.autorizar_modelo(skill.nome, skill.modelo_perfil)
            texto, tokens_uso = self._llm.chat(mensagens, perfil=skill.modelo_perfil)  # 503 se fora
            fim = self._relogio.agora()
            contexto_anterior[nome] = texto
            texto_content = texto  # a matriz sai da ÚLTIMA etapa (content)
            invocacoes.append(
                self._registrar_invocacao(
                    os_,
                    skill,
                    input={"kv_master": kv_master, "instrucoes": instrucoes or ""},
                    output={"texto": texto},
                    evidencias=[],
                    portador_id=portador_id,
                    inicio=inicio,
                    fim=fim,
                    span="generate",
                    portao=portao,
                    tokens=tokens_uso,
                )
            )

        saida = agentes_t6.interpretar_matriz(texto_content, canais=canais, variantes=variantes)
        if not saida.celulas:  # guarda-corpo §1.3.5: nada é inventado
            raise SaidaDoCriativoInvalida(
                "Content não devolveu matriz utilizável (JSON malformado ou nenhuma "
                "célula nos canais×variantes pedidos — §8-M6). "
                + (f"Resposta do agente: {saida.resposta}" if saida.resposta else "")
            )

        agora = self._relogio.agora()
        celulas = [
            CelulaCriativo(canal=c.canal, variante=c.variante, conteudo=c.conteudo)
            for c in saida.celulas  # estado default `gerado` — agente nunca aprova (A3)
        ]
        validadores.validar_celulas(celulas)  # A1: SMS>160 etc. → CriativoInvalido (422)
        avisos = self._avisos_compliance(os_, celulas, kv_master, portador_id, portao)

        criativo = Criativo(
            id=uuid.uuid4(),
            os_id=os_.id,
            kv_master=dict(kv_master),
            celulas=celulas,
            created_at=agora,
            updated_at=agora,
        )
        self._repo.adicionar_criativo(criativo)
        # evidências da matriz ficam no ledger da invocação do content
        invocacoes[-1].evidencias = list(saida.evidencias)
        self._evento(
            os_,
            "criativo.gerado",
            {
                "criativo_id": str(criativo.id),
                "canais": canais,
                "variantes": variantes,
                "celulas": len(celulas),
            },
            actor="agente:content",
            via_ai=True,
        )
        return criativo, avisos, invocacoes

    # ----------------------------------------------------------------- Célula
    def decidir_celula(
        self,
        tenant_id: str,
        criativo_id: uuid.UUID,
        *,
        canal: str,
        variante: str,
        acao: Literal["aprovar", "revisar"],
        observacao: str | None,
        por: uuid.UUID,
        actor: str,
    ) -> Criativo:
        """PATCH /criativos/{id}/celula — aprovar/revisar por célula (A3: só humano
        analista+; RBAC na rota, regra pura em domain/criativo/matriz.py)."""
        criativo, os_ = self._exigir_criativo(tenant_id, criativo_id)
        agora = self._relogio.agora()
        if acao == "aprovar":
            celula = regras.aprovar_celula(
                criativo, canal, variante, por=por, agora=agora, observacao=observacao
            )
        else:
            celula = regras.pedir_revisao(
                criativo, canal, variante, agora=agora, observacao=observacao
            )
        self._repo.salvar_criativo(criativo)
        self._evento(
            os_,
            "criativo.celula_alterada",
            {
                "criativo_id": str(criativo.id),
                "canal": canal,
                "variante": variante,
                "acao": acao,
                "estado": celula.estado,
            },
            actor=actor,
        )
        return criativo

    # -------------------------------------------------------------- KV master
    def editar_kv_master(
        self,
        tenant_id: str,
        criativo_id: uuid.UUID,
        *,
        kv_master: dict[str, Any],
        portador_id: uuid.UUID,
        actor: str,
    ) -> tuple[Criativo, list[str]]:
        """PUT /criativos/{id}/kv-master — A2: células derivadas → `adaptado_revisar`.

        Compliance determinístico valida o novo KV (422); warn 20b é best-effort —
        a edição NUNCA depende de LLM (§10.6).
        """
        criativo, os_ = self._exigir_criativo(tenant_id, criativo_id)
        validadores.validar_kv_master(kv_master)  # CriativoInvalido → 422
        agora = self._relogio.agora()
        marcadas = regras.editar_kv_master(criativo, kv_master, agora=agora)
        self._repo.salvar_criativo(criativo)
        avisos = self._avisos_compliance(
            os_,
            criativo.celulas,
            kv_master,
            portador_id,
            portao_ia.de(  # política PUBLICADA (§10.2) + gasto do teto (J02)
                self._publicacoes_ia,
                tenant_id,
                gasto_tokens=portao_ia.gasto_do_dia(self._repo, self._relogio, tenant_id),
            ),
        )
        self._evento(
            os_,
            "criativo.kv_master_editado",
            {
                "criativo_id": str(criativo.id),
                "celulas_marcadas": [f"{c.canal}/{c.variante}" for c in marcadas],
                "estado": "adaptado_revisar",
            },
            actor=actor,
        )
        return criativo, avisos

    # ------------------------------------------------------- KV master padrão
    def kv_master_padrao(
        self, tenant_id: str, os_id: uuid.UUID
    ) -> tuple[dict[str, str], list[str], bool]:
        """GET /os/{id}/criativos/kv-padrao — KV de partida derivado do BRIEFING (A8).

        Determinístico, sem LLM e sem persistir nada: devolve `(kv_master, campos do
        briefing usados, briefing suficiente?)`. Briefing insuficiente → placeholders
        neutros ("(defina o Key Visual)"), nunca copy de outra campanha (§1.3.5).
        """
        os_ = self._servico_os.obter_os(tenant_id, os_id)  # NaoEncontrado → 404
        return (
            kv_padrao.derivar_kv_master(os_.briefing),
            kv_padrao.campos_derivados(os_.briefing),
            kv_padrao.suficiente(os_.briefing),
        )

    # --------------------------------------------------------------- Interno
    def _exigir_criativo(self, tenant_id: str, criativo_id: uuid.UUID) -> tuple[Criativo, OS]:
        criativo = self._repo.obter_criativo(criativo_id)
        if criativo is None:
            raise NaoEncontrado(f"Criativo {criativo_id} não encontrado.")
        os_ = self._servico_os.obter_os(tenant_id, criativo.os_id)  # escopo de tenant via OS
        return criativo, os_

    def _avisos_compliance(
        self,
        os_: OS,
        celulas: list[CelulaCriativo],
        kv_master: dict[str, Any],
        portador_id: uuid.UUID,
        portao: portao_ia.PortaoIa,
    ) -> list[str]:
        """Warn de linguagem (LLM 20b — "regras + warn LLM"): NUNCA bloqueia; hub fora
        → sem avisos (§10.6 — o caminho determinístico já deu o veredito).

        DIVERGÊNCIA CONHECIDA, deliberadamente NÃO enforçada aqui (§7.2 · parâmetro (f)):
        este é o único `chat` da plataforma que usa um perfil LITERAL (`"20b"`) em vez do
        `skill.modelo_perfil`, e atribui o span ao `content` — cujo roster declara 120b.
        Chamar `autorizar_modelo("content", "20b")` recusaria a geração de criativo com a
        política DEFAULT (roster pinado), quebrando comportamento que hoje funciona; e o
        default não pode mudar nesta fiação. O caso é análogo ao `guard` (veredito
        determinístico, LLM só EXPLICA), que o roster resolveu com entrada própria de
        20b. A correção é do roster, não daqui — registrada como EMENDA SUGERIDA no
        relatório desta onda. Enquanto ela não vem, este call site fica FORA do
        parâmetro (f), declarado em vez de escondido."""
        textos = [str(v) for v in kv_master.values() if isinstance(v, str)]
        for celula in celulas:
            textos.extend(v for v in celula.conteudo.values() if isinstance(v, str))
        mensagens = agentes_t6.montar_mensagens_compliance(textos)
        inicio = self._relogio.agora()
        try:
            # J02 (auditoria da onda 6): este chat NÃO passa por `autorizar_modelo` (a
            # exceção do vigia F03 é sobre o PERFIL), mas o teto de tokens é ortogonal
            # ao roster — sem o teto aqui, este era o único chat da rota kv-master que
            # ignorava o orçamento. O teto é aplicado DENTRO do try: o warn é acessório
            # (a edição já foi persistida), então orçamento estourado DEGRADA o warn
            # para vazio — a enforcement do teto é "o modelo não é chamado", não um 429
            # que quebraria uma edição já feita. Mesma direção do LLMIndisponivel.
            portao.exigir_dentro_do_teto()
            texto, tokens_uso = self._llm.chat(mensagens, perfil="20b")
        except (LLMIndisponivel, TetoDeTokensExcedido):
            return []  # warn é acessório — nunca bloqueia nem depende de LLM
        fim = self._relogio.agora()
        avisos = agentes_t6.interpretar_avisos(texto)
        skill = agentes_t6.carregar("content")  # warn atribuído ao content (etapa T6)
        self._registrar_invocacao(
            os_,
            skill,
            input={"proposito": "compliance_warn", "textos": len(textos)},
            output={"avisos": avisos},
            evidencias=[],
            portador_id=portador_id,
            inicio=inicio,
            fim=fim,
            span="compliance_warn",
            portao=portao,
            tokens=tokens_uso,
        )
        return avisos

    def _registrar_invocacao(
        self,
        os_: OS,
        skill: Any,
        *,
        input: dict[str, Any],
        output: dict[str, Any],
        evidencias: list[str],
        portador_id: uuid.UUID,
        inicio: datetime,
        fim: datetime,
        span: str,
        portao: portao_ia.PortaoIa,
        tokens: int | None = None,
    ) -> Invocacao:
        """Ledger via_ai (§4.1 `invocacao`) + evento `agent.invoked` + trace (§10.8).

        Ponto ÚNICO de gravação do M6: a retenção da política (§10.4) é aplicada aqui,
        então nem o pipeline nem o warn de compliance podem escapar dela por esquecimento.
        """
        invocacao = Invocacao(
            id=uuid.uuid4(),
            tenant_id=os_.tenant_id,
            os_id=os_.id,
            agente_id=agente_uuid(skill.nome),
            skill_versao=skill.versao,
            usuario_portador=portador_id,
            input=portao.reter_input({"os_id": str(os_.id), **input}),
            output=portao.reter_output(output),
            evidencias=list(evidencias),
            tokens=tokens,  # I04: usage do provedor — §10.8
            latencia_ms=int((fim - inicio).total_seconds() * 1000),
            created_at=fim,
        )
        self._repo.adicionar_invocacao(invocacao)
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type="agent.invoked",
                payload={
                    "invocacao_id": str(invocacao.id),
                    "agente": skill.nome,
                    "os_codigo": os_.codigo,
                },
                actor=f"agente:{skill.nome}",
                via_ai=True,
                created_at=fim,
            )
        )
        self._tracer.trace(  # §10.8: fire-and-forget, trace_id = invocacao.id
            trace_id=str(invocacao.id),
            nome=f"{skill.nome}.{span}",
            metadados={
                "tenant": os_.tenant_id,
                "os_id": str(os_.id),
                "agente": skill.nome,
                "skill_versao": skill.versao,
                "modelo_perfil": skill.modelo_perfil,
            },
            spans=[{"nome": span, "latencia_ms": invocacao.latencia_ms}],
        )
        return invocacao

    def _evento(
        self, os_: OS, tipo: str, payload: dict[str, Any], *, actor: str, via_ai: bool = False
    ) -> None:
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type=tipo,
                payload=payload,
                actor=actor,
                via_ai=via_ai,
                created_at=self._relogio.agora(),
            )
        )
