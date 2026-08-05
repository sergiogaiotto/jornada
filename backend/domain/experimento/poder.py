"""Cálculo de poder do pré-registro (§8-M8: `POST /experimentos` — "pré-registro +
poder") — CÓDIGO PURO, zero LLM (§10.6).

n mínimo POR BRAÇO para detectar o MDE pré-registrado num teste de duas proporções
(aproximação normal, α=0,05 bilateral, poder alvo 0,80) — as MESMAS premissas do
motor (§6 `_poder`): n = (z_{α/2}+z_β)² · (p₁(1−p₁)+p₂(1−p₂)) / MDE².
"""

import math

Z_ALFA_2 = 1.959964  # α = 0,05 bilateral (mesma constante do motor §6)
Z_PODER_80 = 0.841621  # z do poder alvo 0,80
ALFA = 0.05
PODER_ALVO = 0.80


def n_minimo_por_mde(p_base: float, mde_pp: float) -> int:
    """n mínimo por braço (holdout é o braço limitante) para o MDE em pontos percentuais.

    `p_base` = conversão orgânica esperada (prior §6); `mde_pp` > 0.
    """
    if mde_pp <= 0:
        raise ValueError("MDE deve ser > 0 pp (§8-M8: pré-registro com cálculo de poder).")
    mde = mde_pp / 100.0
    p2 = min(1.0, p_base + mde)
    variancia = p_base * (1.0 - p_base) + p2 * (1.0 - p2)
    return math.ceil(((Z_ALFA_2 + Z_PODER_80) ** 2) * variancia / (mde**2))
