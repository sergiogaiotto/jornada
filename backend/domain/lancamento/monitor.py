"""Monitor T13 (§8-M10: `GET /os/{id}/monitor`) — CÓDIGO PURO, ZERO LLM (§10.6).

TODOS os KPIs saem como PAR `{previsto, realizado}` (§1.1.2: "o Previsto congelado é
a régua do pós-disparo — previsto × realizado em todo KPI"): conversões, lift vs
holdout com IC95, ROAS, custo real, receita, metas do briefing × realizado e
disparos/custo POR CANAL. O previsto vem EXCLUSIVAMENTE do `snapshot.previsto`
congelado (§4.1); o realizado vem da telemetria ENS (fluxo em tempo real — o extract
é conciliação, nunca soma para não dobrar contagem).

Premissas do realizado (documentadas na saída):
- conversões = eventos `conversion` do grupo tratado (`payload.grupo != 'holdout'`) —
  mesmo recorte do motor §6 (holdout não recebe envios; converte no orgânico);
- n tratado = contatos DISTINTOS com `sent` (população exposta até agora); n holdout
  proporcional via `holdout_pct` congelado — lift em pp com IC95 normal de duas
  proporções (mesmo z do §6; `significativo` ⇔ IC exclui zero, regra §8-M11-A2);
- receita = conversões × ticket médio congelado no previsto; ROAS = receita/custo;
- custo real = Σ sents × tarifa vigente por canal (Decimal — dinheiro nunca em float).
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from domain.lancamento.modelos import TelemetryEvent

_Z_ALFA_2 = 1.959964  # mesma constante do motor §6 / poder M8


def _par(previsto: Any, realizado: Any) -> dict[str, Any]:
    return {"previsto": previsto, "realizado": realizado}


def _lift_realizado(
    conv_tratado: int,
    conv_holdout: int,
    n_tratado: int,
    holdout_pct: float | None,
) -> dict[str, Any]:
    """Lift vs holdout (pp) com IC95 — aproximação normal de duas proporções."""
    if not n_tratado or not holdout_pct or not 0.0 < holdout_pct < 100.0:
        return {
            "valor_pp": None,
            "ic95_pp": None,
            "significativo": None,
            "detalhe": "sem população exposta ou holdout_pct congelado — lift não mensurável.",
        }
    n_holdout = max(1, round(n_tratado * holdout_pct / (100.0 - holdout_pct)))
    p_t = min(1.0, conv_tratado / n_tratado)
    p_h = min(1.0, conv_holdout / n_holdout)
    se = math.sqrt(p_t * (1.0 - p_t) / n_tratado + p_h * (1.0 - p_h) / n_holdout)
    diff = p_t - p_h
    ic = [round((diff - _Z_ALFA_2 * se) * 100.0, 4), round((diff + _Z_ALFA_2 * se) * 100.0, 4)]
    return {
        "valor_pp": round(diff * 100.0, 4),
        "ic95_pp": ic,
        "significativo": ic[0] > 0.0 or ic[1] < 0.0,  # IC exclui zero (§8-M11-A2)
        "n_tratado": n_tratado,
        "n_holdout": n_holdout,
        "conversoes_tratado": conv_tratado,
        "conversoes_holdout": conv_holdout,
    }


def montar_monitor(
    *,
    previsto: dict[str, Any],
    eventos: list[TelemetryEvent],
    tarifas: dict[str, Decimal],
    metas: dict[str, Any],
    holdout_pct: float | None,
) -> dict[str, Any]:
    """KPIs previsto×realizado (§8-M10) sobre o Previsto congelado + telemetria ENS."""
    ens = [e for e in eventos if e.fonte != "extract"]
    n_extract = len(eventos) - len(ens)

    sents = [e for e in ens if e.tipo == "sent"]
    disparos_real: dict[str, int] = {}
    for evento in sents:
        disparos_real[evento.canal or "?"] = disparos_real.get(evento.canal or "?", 0) + 1
    conv_tratado = 0
    conv_holdout = 0
    for evento in ens:
        if evento.tipo != "conversion":
            continue
        if (evento.payload or {}).get("grupo") == "holdout":
            conv_holdout += 1
        else:
            conv_tratado += 1

    custo_real_canal = {
        canal: Decimal(n) * tarifas.get(canal, Decimal(0)) for canal, n in disparos_real.items()
    }
    custo_real = float(sum(custo_real_canal.values(), Decimal(0)))
    ticket = float((previsto.get("parametros") or {}).get("ticket_medio") or 0.0)
    receita_real = round(conv_tratado * ticket, 2)
    roas_real = round(receita_real / custo_real, 4) if custo_real > 0 else None

    n_tratado = len({e.contato_hash for e in sents if e.contato_hash})
    lift_real = _lift_realizado(conv_tratado, conv_holdout, n_tratado, holdout_pct)

    # ------- previsto por canal (funil congelado: nós channel.* → p50 de envios) -------
    disparos_prev: dict[str, float] = {}
    for no in (previsto.get("funil") or {}).values():
        tipo = str(no.get("tipo", ""))
        if tipo.startswith("channel."):
            canal = tipo.split(".", 1)[1]
            disparos_prev[canal] = round(disparos_prev.get(canal, 0.0) + float(no["p50"]), 1)

    def _custo_prev(canal: str) -> float | None:
        if canal not in disparos_prev:
            return None
        return round(float(Decimal(str(disparos_prev[canal])) * tarifas.get(canal, Decimal(0))), 4)

    canais = {
        canal: {
            "disparos": _par(disparos_prev.get(canal), disparos_real.get(canal, 0)),
            "custo": _par(
                _custo_prev(canal), round(float(custo_real_canal.get(canal, Decimal(0))), 4)
            ),
        }
        for canal in sorted({*disparos_prev, *disparos_real})
    }

    kpis = {
        "conversoes": _par(previsto.get("conversoes"), conv_tratado),
        "lift_pp": _par(previsto.get("lift_pp"), lift_real),
        "roas": _par(previsto.get("roas"), roas_real),
        "custo": _par(previsto.get("custo"), round(custo_real, 4)),
        "receita": _par(previsto.get("receita"), receita_real),
    }
    realizados_por_meta: dict[str, Any] = {
        "conversoes": conv_tratado,
        "roas": roas_real,
        "custo": round(custo_real, 4),
        "receita": receita_real,
        "lift_pp": lift_real["valor_pp"],
    }
    metas_par = {
        nome: _par(alvo, realizados_por_meta.get(nome)) for nome, alvo in sorted(metas.items())
    }
    return {
        "kpis": kpis,
        "canais": canais,
        "metas": metas_par,
        "fontes": {"ens": len(ens), "extract": n_extract},
        "premissas": [
            "realizado medido sobre a telemetria ENS (extract é conciliação — não soma)",
            "conversões = eventos conversion do grupo tratado (payload.grupo != 'holdout')",
            "n tratado = contatos distintos com sent; n holdout proporcional ao "
            f"holdout_pct congelado ({holdout_pct})",
            f"receita = conversões × ticket médio congelado (R$ {ticket:.2f}); "
            "ROAS = receita/custo real",
        ],
    }
