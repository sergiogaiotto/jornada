"""Ranking determinístico das propostas do optimize (§8-M11: "ranqueadas
lift×esforço×risco") — CÓDIGO PURO, zero LLM (§10.6: o agente propõe, o código ranqueia).

- lift  = ganho RELATIVO de conversões P50 da pré-simulação (proposto vs base §6);
- esforço = tamanho do diff JGC (nós/arestas adicionados+removidos+alterados; ≥1);
- risco = fator multiplicativo: semáforo da pré-simulação (amarelo/vermelho), custo
  P50 subindo e mudança no nó de entrada (reinicia contatos em espera — §5.4.3).
score = lift / (esforço × risco) — maior é melhor; empate mantém a ordem de proposta.
"""

from __future__ import annotations

from typing import Any

RISCO_BASE = 1.0
RISCO_SEMAFORO = {"verde": 0.0, "amarelo": 0.5, "vermelho": 1.5}
RISCO_CUSTO_SOBE = 0.5
RISCO_ALTERA_ENTRADA = 1.0


def esforco_do_diff(diff: dict[str, Any]) -> int:
    """Nº de mudanças estruturais do diff JGC (formato do M7 `ajustar`); mínimo 1."""
    mudancas = 0
    for chave in ("nodes", "edges"):
        bloco = diff.get(chave) or {}
        for tipo in ("adicionados", "removidos", "alterados"):
            mudancas += len(bloco.get(tipo) or [])
    if diff.get("meta_alterada"):
        mudancas += 1
    return max(1, mudancas)


def risco_da_proposta(*, semaforo: str, delta_custo_p50: float, altera_entrada: bool) -> float:
    """Fator de risco ≥ 1.0 — soma de agravantes sobre a base."""
    risco = RISCO_BASE + RISCO_SEMAFORO.get(semaforo, RISCO_SEMAFORO["vermelho"])
    if delta_custo_p50 > 0:
        risco += RISCO_CUSTO_SOBE
    if altera_entrada:
        risco += RISCO_ALTERA_ENTRADA
    return round(risco, 2)


def score_da_proposta(
    *, conversoes_base_p50: float, conversoes_proposto_p50: float, esforco: int, risco: float
) -> float:
    """lift/(esforço×risco): lift = ganho relativo de conversões P50 (negativo conta)."""
    base = max(float(conversoes_base_p50), 1.0)
    lift_rel = (float(conversoes_proposto_p50) - float(conversoes_base_p50)) / base
    return round(lift_rel / (max(1, esforco) * max(1.0, risco)), 6)
