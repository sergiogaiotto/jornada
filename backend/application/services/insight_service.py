"""Caso de uso do M10 (parte 3) · Pergunte aos Dados (§8-M10, §7.2 insight) —
`POST /os/{id}/perguntar`.

O agente insight (LLM 120b — roster §7.2) só COMPÕE: NL → consulta NOMEADA
`vw_metricas_*` + parâmetros do dicionário versionado (domain/lancamento/
semantica.py) — NUNCA SQL livre. Toda execução é código puro sobre a camada
semântica e a resposta anexa a consulta executada (§8-M10: "resposta inclui a
query"). Fora do escopo ⇒ RECUSA PADRÃO sem executar nada (A4):
- pré-guarda determinística: pergunta pedindo dado individual/PII recusa SEM
  chamar o LLM (PII jamais em prompt §1.3.5/§10.2);
- guarda-corpos pós-LLM (agents/insight.py): SQL livre, view desconhecida,
  parâmetro fora da whitelist ou JSON malformado ⇒ recusa, zero execução.
Toda pergunta grava `invocacao` (via_ai — LGPD Art. 20, pergunta com PII
mascarada §10.2) + evento `agent.invoked` (§2.3) + trace Langfuse fire-and-forget
com trace_id = invocacao.id (§10.8). Previsto CONGELADO é a régua (§1.1.2):
OS sem snapshot com previsto ⇒ PrevistoAusente (409), como no monitor T13.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from agents import insight as agente_insight
from application.ports.clock import ClockPort
from application.ports.llm import LLMPort
from application.ports.observabilidade import TracerPort
from application.ports.repositorio_insight import RepositorioInsight
from domain.agentes.modelos import Invocacao, agente_uuid
from domain.campanha.erros import NaoEncontrado
from domain.campanha.modelos import OS, EventoDominio
from domain.custo.tarifas import TARIFAS_VIGENTES
from domain.governanca.modelos import Snapshot
from domain.lancamento import semantica
from domain.lancamento.erros import PrevistoAusente


class ServicoInsight:
    def __init__(
        self,
        repositorio: RepositorioInsight,
        relogio: ClockPort,
        llm: LLMPort,
        tracer: TracerPort,
        tarifas: dict[str, Decimal] | None = None,
    ) -> None:
        self._repo = repositorio
        self._relogio = relogio
        self._llm = llm
        self._tracer = tracer
        self._tarifas = tarifas if tarifas is not None else TARIFAS_VIGENTES

    # -------------------------------------------------- POST /os/{id}/perguntar
    def perguntar(
        self, tenant_id: str, os_id: uuid.UUID, *, pergunta: str, portador_id: uuid.UUID
    ) -> dict[str, Any]:
        os_ = self._repo.obter_os(tenant_id, os_id)
        if os_ is None:
            raise NaoEncontrado(f"OS {os_id} não encontrada no tenant {tenant_id!r}.")
        skill = agente_insight.carregar()
        inicio = self._relogio.agora()

        spans: list[dict[str, Any]] = []
        consulta_executada: dict[str, Any] | None = None
        motivo = agente_insight.motivo_fora_do_escopo(pergunta)
        if motivo is not None:  # A4: recusa determinística — SEM LLM, SEM consulta
            saida = agente_insight.SaidaInsight(
                consulta=None,
                parametros={},
                resposta=agente_insight.RECUSA_PADRAO,
                recusa=motivo,
            )
            spans.append({"nome": "guard", "recusa": motivo})
        else:
            contexto = self._contexto_metricas(os_)  # falha RÁPIDO: PrevistoAusente → 409
            mensagens = agente_insight.montar_mensagens(skill, pergunta)
            texto = self._llm.chat(mensagens, perfil=skill.modelo_perfil)  # indisponível → 503
            spans.append({"nome": "generate", "modelo_perfil": skill.modelo_perfil})
            saida = agente_insight.interpretar_saida(texto)
            if saida.recusa is None and saida.consulta is not None:
                consulta_executada = semantica.executar(saida.consulta, saida.parametros, contexto)
                spans.append(
                    {
                        "nome": "executar_consulta",
                        "consulta": saida.consulta,
                        "zero_sql_livre": True,
                    }
                )

        fim = self._relogio.agora()
        invocacao = self._registrar_invocacao(
            os_, skill, pergunta, saida, consulta_executada, portador_id, inicio, fim
        )
        self._tracer.trace(  # §10.8: fire-and-forget, trace_id = invocacao.id
            trace_id=str(invocacao.id),
            nome="insight.perguntar",
            metadados={
                "tenant": tenant_id,
                "os_id": str(os_.id),
                "agente": skill.nome,
                "skill_versao": skill.versao,
                "modelo_perfil": skill.modelo_perfil,
            },
            spans=spans,
        )
        resposta = saida.resposta
        if not resposta:  # narrativa vazia: fallback determinístico — nada inventado (§1.3.5)
            resposta = (
                agente_insight.RECUSA_PADRAO
                if consulta_executada is None
                else (
                    f"Consulta {consulta_executada['nome']} executada — resultado e query anexados."
                )
            )
        return {
            "resposta": resposta,
            "recusado": saida.recusa is not None,
            "motivo_recusa": saida.recusa,
            "consulta_executada": consulta_executada,
            "camada_semantica": {
                "versao": semantica.VERSAO_CAMADA,
                "consultas": sorted(semantica.CAMADA_SEMANTICA),
            },
            "invocacao_id": invocacao.id,
        }

    # ------------------------------------------------------------------- privados
    def _contexto_metricas(self, os_: OS) -> semantica.ContextoMetricas:
        """Insumos da camada semântica — MESMA régua do monitor T13 (§1.1.2):
        Previsto congelado do snapshot de referência, telemetria da OS, tarifas,
        metas do briefing e holdout congelado (fallback: segmento §4.1)."""
        snapshot = self._snapshot_de_referencia(os_.id)
        if snapshot is None or not snapshot.previsto:
            raise PrevistoAusente(
                "OS sem snapshot com Previsto congelado — a camada semântica compara "
                "todo KPI contra a régua congelada (§8-M10/§1.1.2)."
            )
        experimento = (snapshot.conteudo.get("componentes") or {}).get("experimento") or {}
        holdout_pct = experimento.get("holdout_pct")
        if holdout_pct is None:
            segmentos = self._repo.listar_segmentos(os_.id)
            holdout_pct = segmentos[-1].holdout_pct if segmentos else None
        return semantica.ContextoMetricas(
            previsto=snapshot.previsto,
            eventos=self._repo.listar_telemetria(os_.id),
            tarifas=self._tarifas,
            metas=dict((os_.briefing or {}).get("metas") or {}),
            holdout_pct=holdout_pct,
        )

    def _snapshot_de_referencia(self, os_id: uuid.UUID) -> Snapshot | None:
        """Espelha `ServicoLancamento._launch_de_referencia` (monitor T13): snapshot
        do último launch; sem launch, o último snapshot com Previsto congelado."""
        snapshot: Snapshot | None = None
        com_launch: Snapshot | None = None
        for candidato in self._repo.listar_snapshots(os_id):
            if self._repo.listar_launches(candidato.id):
                com_launch = candidato
            elif com_launch is None and candidato.previsto:
                snapshot = candidato
        return com_launch or snapshot

    def _registrar_invocacao(
        self,
        os_: OS,
        skill: Any,
        pergunta: str,
        saida: agente_insight.SaidaInsight,
        consulta_executada: dict[str, Any] | None,
        portador_id: uuid.UUID,
        inicio: datetime,
        fim: datetime,
    ) -> Invocacao:
        """Ledger via_ai (§4.1 `invocacao`) + evento `agent.invoked` (§2.3). Pergunta
        entra MASCARADA (runs de dígitos ≥11 — §10.2: PII nunca em log/ledger)."""
        invocacao = Invocacao(
            id=uuid.uuid4(),
            tenant_id=os_.tenant_id,
            os_id=os_.id,
            agente_id=agente_uuid(skill.nome),
            skill_versao=skill.versao,
            usuario_portador=portador_id,
            input={"pergunta": agente_insight.mascarar_pii(pergunta)},
            output={
                "consulta": saida.consulta,
                "parametros": saida.parametros,
                "resposta": saida.resposta,
                "recusa": saida.recusa,
            },
            evidencias=(
                []  # a evidência é a própria consulta versionada executada (§7.2)
                if consulta_executada is None
                else [f"{consulta_executada['nome']}@{consulta_executada['versao']}"]
            ),
            latencia_ms=int((fim - inicio).total_seconds() * 1000),
            created_at=fim,
        )
        self._repo.adicionar_invocacao(invocacao)
        self._repo.adicionar_evento(
            EventoDominio(
                tenant_id=os_.tenant_id,
                os_id=os_.id,
                type="agent.invoked",  # §2.3
                payload={
                    "agente": skill.nome,
                    "invocacao_id": str(invocacao.id),
                    "recusado": saida.recusa is not None,
                    "consulta": saida.consulta,
                },
                actor=str(portador_id),
                via_ai=True,
                created_at=fim,
            )
        )
        return invocacao
