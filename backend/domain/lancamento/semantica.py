"""Camada semântica do Pergunte aos Dados (§8-M10 parte 3, §7.2 insight) — CÓDIGO
PURO, ZERO LLM, ZERO I/O.

Dicionário VERSIONADO de consultas nomeadas `vw_metricas_*` (roas, lift,
custo_por_pedido, atingimento_meta): o agente insight compõe SOMENTE sobre elas —
NL → consulta nomeada + parâmetros, NUNCA SQL livre (§7.2: "NL→SQL somente sobre
camada semântica (views métricas); mostra a query"). Cada consulta carrega a
definição SQL da view (a "query" exibida na resposta — §8-M10); a execução em
dev/teste é o equivalente determinístico em Python sobre o repositório em memória
(mesmo racional da view `os_saude` §4.1: contrato SQL íntegro, adapter equivale).

Guarda-corpos (defesa em profundidade — o serviço RECUSA antes de chegar aqui):
nome fora do dicionário ou parâmetro fora da whitelist ⇒ `ConsultaForaDaCamada`
(nada é executado, nada é inventado §1.3.5). Realizado medido sobre a telemetria
ENS (extract é conciliação — premissa do monitor T13); previsto SEMPRE do Previsto
congelado do snapshot (§1.1.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from domain.lancamento.erros import ConsultaForaDaCamada
from domain.lancamento.modelos import TelemetryEvent
from domain.lancamento.monitor import montar_monitor

VERSAO_CAMADA = "1.0.0"  # dicionário versionado (§8-M10 parte 3)

CANAIS = ("email", "sms", "push", "whatsapp", "rcs")  # enum fechado do JGC §5.2/§4.1


@dataclass(frozen=True)
class ConsultaNomeada:
    """Entrada do dicionário: métrica nomeada + whitelist de parâmetros + SQL da view."""

    nome: str  # vw_metricas_*
    metrica: str
    versao: str
    descricao: str
    parametros: dict[str, str] = field(default_factory=dict)  # {param: descrição} — whitelist
    sql: str = ""  # definição da view (a "query" mostrada — §7.2/§8-M10)


CAMADA_SEMANTICA: dict[str, ConsultaNomeada] = {
    consulta.nome: consulta
    for consulta in (
        ConsultaNomeada(
            nome="vw_metricas_roas",
            metrica="roas",
            versao=VERSAO_CAMADA,
            descricao=(
                "ROAS previsto×realizado da OS: receita (conversões tratado × ticket "
                "médio congelado) / custo real (sents × tarifa vigente por canal)."
            ),
            sql=(
                "-- vw_metricas_roas v" + VERSAO_CAMADA + "\n"
                "select s.previsto->>'roas' as roas_previsto,\n"
                "       (conv.tratado * (s.previsto->'parametros'->>'ticket_medio')::numeric)\n"
                "         / nullif(custo.realizado, 0) as roas_realizado\n"
                "from snapshot s\n"
                "join vw_conversoes_tratado conv using (os_id)\n"
                "join vw_custo_realizado custo using (os_id)"
            ),
        ),
        ConsultaNomeada(
            nome="vw_metricas_lift",
            metrica="lift",
            versao=VERSAO_CAMADA,
            descricao=(
                "Lift (pp) vs holdout previsto×realizado, com IC95 e significância "
                "(IC exclui zero — regra §8-M11-A2) sobre conversões tratado×holdout."
            ),
            sql=(
                "-- vw_metricas_lift v" + VERSAO_CAMADA + "\n"
                "select s.previsto->>'lift_pp' as lift_previsto_pp,\n"
                "       lift_pp(conv.tratado, conv.holdout, pop.n_tratado,\n"
                "               s.previsto->>'holdout_pct') as lift_realizado\n"
                "from snapshot s\n"
                "join vw_conversoes_por_grupo conv using (os_id)\n"
                "join vw_populacao_exposta pop using (os_id)"
            ),
        ),
        ConsultaNomeada(
            nome="vw_metricas_custo_por_pedido",
            metrica="custo_por_pedido",
            versao=VERSAO_CAMADA,
            descricao=(
                "Custo por pedido (custo / conversões) previsto×realizado; "
                "opcionalmente recortado por canal (realizado)."
            ),
            parametros={"canal": "opcional — um de " + "|".join(CANAIS)},
            sql=(
                "-- vw_metricas_custo_por_pedido v" + VERSAO_CAMADA + " (param :canal)\n"
                "select custo.realizado / nullif(conv.tratado, 0) as custo_por_pedido_realizado,\n"
                "       (s.previsto->>'custo')::numeric\n"
                "         / nullif((s.previsto->>'conversoes')::numeric, 0)\n"
                "         as custo_por_pedido_previsto\n"
                "from snapshot s\n"
                "join vw_custo_realizado custo using (os_id)\n"
                "join vw_conversoes_tratado conv using (os_id)\n"
                "where (:canal is null or custo.canal = :canal)"
            ),
        ),
        ConsultaNomeada(
            nome="vw_metricas_atingimento_meta",
            metrica="atingimento_meta",
            versao=VERSAO_CAMADA,
            descricao=(
                "Atingimento das metas do briefing (realizado/alvo em %); "
                "opcionalmente uma meta específica."
            ),
            parametros={"meta": "opcional — nome da meta do briefing (ex.: conversoes, roas)"},
            sql=(
                "-- vw_metricas_atingimento_meta v" + VERSAO_CAMADA + " (param :meta)\n"
                "select m.nome as meta, m.alvo, r.realizado,\n"
                "       round(100.0 * r.realizado / nullif(m.alvo, 0), 1) as atingimento_pct\n"
                "from vw_metas_briefing m\n"
                "join vw_kpis_realizados r using (os_id, nome)\n"
                "where (:meta is null or m.nome = :meta)"
            ),
        ),
    )
}


@dataclass(frozen=True)
class ContextoMetricas:
    """Insumos da execução (§8-M10): telemetria + Previsto CONGELADO + tarifas + metas."""

    previsto: dict[str, Any]
    eventos: list[TelemetryEvent]
    tarifas: dict[str, Decimal]
    metas: dict[str, Any]
    holdout_pct: float | None


def normalizar_parametros(
    consulta: ConsultaNomeada, parametros: dict[str, Any]
) -> dict[str, Any] | None:
    """Whitelist por consulta (§7.2: nunca SQL livre — parâmetro fora da lista, ou
    `canal` fora do enum §4.1, invalida a composição). None = inválido (o serviço
    RECUSA sem executar)."""
    normalizados: dict[str, Any] = {}
    for nome, valor in parametros.items():
        if nome not in consulta.parametros or valor is None:
            return None
        if nome == "canal":
            if str(valor) not in CANAIS:
                return None
            normalizados[nome] = str(valor)
        else:
            normalizados[nome] = str(valor)
    return normalizados


def executar(nome: str, parametros: dict[str, Any], contexto: ContextoMetricas) -> dict[str, Any]:
    """Executa a consulta NOMEADA (única via de execução — §7.2) e devolve o pacote
    com a query anexada (§8-M10: 'resposta inclui a query')."""
    consulta = CAMADA_SEMANTICA.get(nome)
    if consulta is None:
        raise ConsultaForaDaCamada(
            f"Consulta {nome!r} fora da camada semântica (§7.2) — nada foi executado."
        )
    normalizados = normalizar_parametros(consulta, parametros)
    if normalizados is None:
        raise ConsultaForaDaCamada(
            f"Parâmetros fora da whitelist da consulta {nome} (§7.2) — nada foi executado."
        )
    painel = montar_monitor(
        previsto=contexto.previsto,
        eventos=contexto.eventos,
        tarifas=contexto.tarifas,
        metas=contexto.metas,
        holdout_pct=contexto.holdout_pct,
    )
    resultado = _RESOLUTORES[nome](painel, normalizados, contexto)
    return {
        "nome": consulta.nome,
        "metrica": consulta.metrica,
        "versao": consulta.versao,
        "parametros": normalizados,
        "sql": consulta.sql,
        "resultado": resultado,
    }


# ------------------------------------------------------------- resolutores (puros)


def _roas(
    painel: dict[str, Any], _params: dict[str, Any], _ctx: ContextoMetricas
) -> dict[str, Any]:
    kpis = painel["kpis"]
    return {
        "roas": kpis["roas"],
        "receita": kpis["receita"],
        "custo": kpis["custo"],
    }


def _lift(
    painel: dict[str, Any], _params: dict[str, Any], _ctx: ContextoMetricas
) -> dict[str, Any]:
    return {"lift_pp": painel["kpis"]["lift_pp"]}


def _custo_por_pedido(
    painel: dict[str, Any], params: dict[str, Any], contexto: ContextoMetricas
) -> dict[str, Any]:
    canal = params.get("canal")
    kpis = painel["kpis"]
    if canal is None:
        custo_prev, custo_real = kpis["custo"]["previsto"], kpis["custo"]["realizado"]
        conv_prev, conv_real = kpis["conversoes"]["previsto"], kpis["conversoes"]["realizado"]
        detalhe = None
    else:  # recorte por canal: telemetria ENS (extract é conciliação — monitor T13)
        ens = [e for e in contexto.eventos if e.fonte != "extract" and e.canal == canal]
        sents = sum(1 for e in ens if e.tipo == "sent")
        conv_real = sum(
            1 for e in ens if e.tipo == "conversion" and (e.payload or {}).get("grupo") != "holdout"
        )
        custo_real = float(Decimal(sents) * contexto.tarifas.get(canal, Decimal(0)))
        custo_prev, conv_prev = None, None
        detalhe = "previsto por canal indisponível: o funil congelado não abre conversão por canal."
    return {
        "canal": canal or "todos",
        "custo": {"previsto": custo_prev, "realizado": custo_real},
        "conversoes": {"previsto": conv_prev, "realizado": conv_real},
        "custo_por_pedido": {
            "previsto": _divide(custo_prev, conv_prev),
            "realizado": _divide(custo_real, conv_real),
        },
        **({"detalhe": detalhe} if detalhe else {}),
    }


def _atingimento_meta(
    painel: dict[str, Any], params: dict[str, Any], _ctx: ContextoMetricas
) -> dict[str, Any]:
    alvo_nome = params.get("meta")
    metas = painel["metas"]
    linhas = []
    nomes = [alvo_nome] if alvo_nome is not None else sorted(metas)
    for nome in nomes:
        par = metas.get(nome)
        if par is None:  # meta não definida no briefing — resultado explícito, nada inventado
            linhas.append(
                {
                    "meta": nome,
                    "alvo": None,
                    "realizado": None,
                    "atingimento_pct": None,
                    "detalhe": "meta não definida no briefing da OS.",
                }
            )
            continue
        alvo, realizado = par["previsto"], par["realizado"]
        atingimento = _divide(realizado, alvo)
        linhas.append(
            {
                "meta": nome,
                "alvo": alvo,
                "realizado": realizado,
                "atingimento_pct": None if atingimento is None else round(atingimento * 100.0, 1),
            }
        )
    return {"metas": linhas}


def _divide(numerador: Any, denominador: Any) -> float | None:
    try:
        n, d = float(numerador), float(denominador)
    except (TypeError, ValueError):
        return None
    return round(n / d, 4) if d else None


_RESOLUTORES = {
    "vw_metricas_roas": _roas,
    "vw_metricas_lift": _lift,
    "vw_metricas_custo_por_pedido": _custo_por_pedido,
    "vw_metricas_atingimento_meta": _atingimento_meta,
}
