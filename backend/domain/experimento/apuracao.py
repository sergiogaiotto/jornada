"""Apuração do experimento (§8-M11: `POST /experimentos/{id}/apurar`) — CÓDIGO PURO,
zero LLM (§10.6). Anti-peeking (A1): a janela pré-registrada começa na PRIMEIRA
exposição (`sent` ENS) e dura `janela_dias`; antes do fim NENHUM lift é calculado.

Lift vs holdout em pp com IC95 — aproximação normal de duas proporções, MESMO z do
motor §6/poder M8/monitor M10; `significativo` ⇔ IC exclui zero (A2). n holdout é
proporcional ao `holdout_pct` pré-registrado (mesmo recorte do monitor M10: holdout
não recebe envio — seu n vem da proporção congelada sobre a população exposta).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

Z_ALFA_2 = 1.959964  # α = 0,05 bilateral — mesma constante do §6/poder/monitor


def fim_da_janela(primeira_exposicao: datetime, janela_dias: int) -> datetime:
    """Fim da janela pré-registrada: primeira exposição + `janela_dias` (§4.1)."""
    return primeira_exposicao + timedelta(days=janela_dias)


def n_holdout_proporcional(n_tratado: int, holdout_pct: float) -> int:
    """n do holdout pela proporção congelada (holdout_pct sobre o total abordável)."""
    if not 0.0 < holdout_pct < 100.0:
        return 0
    return max(1, round(n_tratado * holdout_pct / (100.0 - holdout_pct)))


def lift_com_ic(
    conv_tratado: int, conv_holdout: int, n_tratado: int, n_holdout: int
) -> dict[str, Any]:
    """Lift (pp) com IC95; `significativo` SÓ com IC excluindo zero (§8-M11-A2)."""
    if n_tratado <= 0 or n_holdout <= 0:
        return {"lift_pp": None, "ic95_pp": None, "significativo": False}
    p_t = min(1.0, conv_tratado / n_tratado)
    p_h = min(1.0, conv_holdout / n_holdout)
    se = math.sqrt(p_t * (1.0 - p_t) / n_tratado + p_h * (1.0 - p_h) / n_holdout)
    diff = p_t - p_h
    ic = [
        round((diff - Z_ALFA_2 * se) * 100.0, 4),
        round((diff + Z_ALFA_2 * se) * 100.0, 4),
    ]
    return {
        "lift_pp": round(diff * 100.0, 4),
        "ic95_pp": ic,
        "significativo": ic[0] > 0.0 or ic[1] < 0.0,  # IC exclui zero (A2)
        "p_tratado": round(p_t, 6),
        "p_holdout": round(p_h, 6),
        "n_tratado": n_tratado,
        "n_holdout": n_holdout,
        "conversoes_tratado": conv_tratado,
        "conversoes_holdout": conv_holdout,
    }
