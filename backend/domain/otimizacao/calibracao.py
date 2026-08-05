"""Calibração de priors (§8-M11 CalibrateService) — CÓDIGO PURO, zero LLM (§10.6:
o agente calibrate §7.2 só NARRA; ajuste e backtest são determinísticos).

Compara previsto (P50 congelado no snapshot — §1.1.2) × realizado (conversões ENS) por
OS, deriva a razão global realizado/previsto (clampada) e propõe priors novos escalando
as taxas de conversão (`canais[*].conversao` e `conversao_organica`) do prior vigente.
Backtest OBRIGATÓRIO (§8-M11): re-prevê cada caso com a razão proposta e exige que o
erro absoluto médio (MAPE sobre o realizado) MELHORE; sem melhora, nada é publicado.
"""

from __future__ import annotations

import json
from typing import Any

RAZAO_MIN, RAZAO_MAX = 0.25, 4.0  # calibração nunca extrapola 4x numa rodada
TAXA_MIN, TAXA_MAX = 1e-6, 0.95  # taxas de conversão permanecem probabilidades


def razao_calibracao(casos: list[dict[str, Any]]) -> float:
    """Razão global Σrealizado/Σprevisto dos casos, clampada em [0.25, 4.0]."""
    previsto = sum(float(c["previsto"]) for c in casos)
    realizado = sum(float(c["realizado"]) for c in casos)
    if previsto <= 0:
        return 1.0
    return round(min(RAZAO_MAX, max(RAZAO_MIN, realizado / previsto)), 6)


def propor_priors(atuais: dict[str, Any], razao: float, versao_nova: int) -> dict[str, Any]:
    """Priors novos = vigentes com taxas de conversão escaladas pela razão (clampadas).

    Deep-copy via json (priors são jsonb §4.1); demais chaves preservadas — o motor
    (§6) não muda: "o serviço passa a preferi-los sem tocar o motor" (priors.py).
    """
    novos: dict[str, Any] = json.loads(json.dumps(atuais))
    for dados in (novos.get("canais") or {}).values():
        dados["conversao"] = _clamp_taxa(float(dados.get("conversao", 0.0)) * razao)
    if "conversao_organica" in novos:
        novos["conversao_organica"] = _clamp_taxa(float(novos["conversao_organica"]) * razao)
    novos["versao"] = versao_nova
    novos["origem"] = "calibracao"
    novos["razao_aplicada"] = razao
    return novos


def backtest(casos: list[dict[str, Any]], razao: float) -> dict[str, Any]:
    """Backtest obrigatório (§8-M11): erro relativo por caso, antes × depois da razão.

    MAPE sobre max(realizado, 1) — determinístico e defensivo contra divisão por zero.
    `melhora` = mape_novo ≤ mape_antigo; `score` numeric(4,2) = max(0, 1 − mape_novo)
    saturado em [0, 1] (1.0 = previsão calibrada perfeita).
    """
    detalhes: list[dict[str, Any]] = []
    erros_antigos: list[float] = []
    erros_novos: list[float] = []
    for caso in casos:
        previsto = float(caso["previsto"])
        realizado = float(caso["realizado"])
        base = max(realizado, 1.0)
        erro_antigo = abs(previsto - realizado) / base
        erro_novo = abs(previsto * razao - realizado) / base
        erros_antigos.append(erro_antigo)
        erros_novos.append(erro_novo)
        detalhes.append(
            {
                "os": caso.get("os"),
                "previsto": previsto,
                "previsto_calibrado": round(previsto * razao, 2),
                "realizado": realizado,
                "erro_antigo": round(erro_antigo, 4),
                "erro_novo": round(erro_novo, 4),
            }
        )
    mape_antigo = round(sum(erros_antigos) / len(erros_antigos), 4)
    mape_novo = round(sum(erros_novos) / len(erros_novos), 4)
    return {
        "casos": detalhes,
        "razao": razao,
        "mape_antigo": mape_antigo,
        "mape_novo": mape_novo,
        "melhora": mape_novo <= mape_antigo,
        "score": round(min(1.0, max(0.0, 1.0 - mape_novo)), 2),
    }


def _clamp_taxa(valor: float) -> float:
    return round(min(TAXA_MAX, max(TAXA_MIN, valor)), 6)
