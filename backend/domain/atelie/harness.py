"""Consolidação DETERMINÍSTICA do harness (M12) — matemática pura, sem I/O.

O judge (agents/harness/judge.py — LLM 120b, rubrica fixa §7.1) devolve notas 0–100
por dimensão POR CASO; aqui o código consolida: média por dimensão sobre os casos que
a avaliam, score global = média das dimensões e `passou` = TODAS as dimensões ≥ 90
(§7.1: "score ≥ 90 por dimensão do judge"). Nota ausente/inválida vale 0 — o guarda-
corpo é conservador: o que o judge não atestou NÃO conta como aprovado (§1.3.5).
"""

from __future__ import annotations

import hashlib
from typing import Any

from domain.atelie.modelos import SCORE_MINIMO_PUBLICACAO


def hash_skill_md(texto: str) -> str:
    """sha256 do skill_md — amarra o harness_run ao CONTEÚDO julgado (publicar exige
    run sobre o texto atual; editar o draft torna o run obsoleto)."""
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def nota_valida(valor: Any) -> float:
    """Nota 0–100 (clamp); ausente/não-numérica → 0.0 (conservador, nada é inventado)."""
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        return 0.0
    return max(0.0, min(100.0, float(valor)))


def consolidar(casos: list[dict[str, Any]]) -> dict[str, Any]:
    """Consolida notas por caso → {score_por_dimensao, score, passou, dimensoes_reprovadas}.

    `casos` = [{"dimensoes": [...], "notas": {dim: 0-100}}]; dimensão avaliada em ao
    menos um caso entra na média (dimensões diferentes por caso são permitidas §4.1).
    """
    somas: dict[str, float] = {}
    contagens: dict[str, int] = {}
    for caso in casos:
        notas = caso.get("notas") or {}
        for dimensao in caso.get("dimensoes") or []:
            somas[dimensao] = somas.get(dimensao, 0.0) + nota_valida(notas.get(dimensao))
            contagens[dimensao] = contagens.get(dimensao, 0) + 1
    score_por_dimensao = {
        dimensao: round(somas[dimensao] / contagens[dimensao], 2) for dimensao in somas
    }
    reprovadas = sorted(d for d, s in score_por_dimensao.items() if s < SCORE_MINIMO_PUBLICACAO)
    score = (
        round(sum(score_por_dimensao.values()) / len(score_por_dimensao), 2)
        if score_por_dimensao
        else 0.0
    )
    return {
        "score_por_dimensao": score_por_dimensao,
        "score": score,
        "passou": bool(score_por_dimensao) and not reprovadas,
        "dimensoes_reprovadas": reprovadas,
    }
