"""Reconciliação diária ENS×extract (§8-M10, aceite A3) — CÓDIGO PURO, ZERO LLM.

Telemetria dupla (§2.1): o ENS é o fluxo em tempo real (webhook, governa breakers e
monitor) e o extract é o batch D-1 do SFMC. A reconciliação compara as CONTAGENS por
tipo de evento (§4.1 `telemetry_event.tipo`) entre as duas fontes; divergência
relativa acima de `LIMITE_DIVERGENCIA_PCT` (2% — A3) em qualquer tipo ⇒ alerta.
Match agregado por tipo no v1 (match por contato_hash é evolução do adapter real).
"""

from __future__ import annotations

from typing import Any

from domain.lancamento.modelos import TIPOS_TELEMETRIA, TelemetryEvent

LIMITE_DIVERGENCIA_PCT = 2.0  # §8-M10-A3: "ENS×extract divergência >2% → alerta"


def comparar_fontes(
    eventos: list[TelemetryEvent], *, limite_pct: float = LIMITE_DIVERGENCIA_PCT
) -> dict[str, Any]:
    """Contagens ENS×extract por tipo + divergência relativa (% sobre a maior fonte).

    Retorna {limite_pct, por_tipo: {tipo: {ens, extract, divergencia_pct,
    acima_limite}}, divergencias: [tipos acima], divergente} — só tipos com evento em
    alguma fonte entram em `por_tipo`.
    """
    contagens: dict[str, dict[str, int]] = {}
    for evento in eventos:
        fonte = "extract" if evento.fonte == "extract" else "ens"
        contagens.setdefault(evento.tipo, {"ens": 0, "extract": 0})[fonte] += 1

    por_tipo: dict[str, dict[str, Any]] = {}
    divergencias: list[str] = []
    for tipo in TIPOS_TELEMETRIA:
        if tipo not in contagens:
            continue
        n_ens, n_extract = contagens[tipo]["ens"], contagens[tipo]["extract"]
        base = max(n_ens, n_extract)
        pct = round(abs(n_ens - n_extract) * 100.0 / base, 2) if base else 0.0
        acima = pct > limite_pct
        por_tipo[tipo] = {
            "ens": n_ens,
            "extract": n_extract,
            "divergencia_pct": pct,
            "acima_limite": acima,
        }
        if acima:
            divergencias.append(tipo)
    return {
        "limite_pct": limite_pct,
        "por_tipo": por_tipo,
        "divergencias": divergencias,
        "divergente": bool(divergencias),
    }
