"""Diff estrutural entre grafos JGC (§5) — CÓDIGO PURO, compartilhado pelo M7
(`POST /jornadas/{id}/ajustar`: prévia Aplicar/Rejeitar §1.1.3) e pelo M11
(propostas do optimize §8-M11: "proposta = diff JGC + impacto simulado")."""

from __future__ import annotations

from typing import Any


def diff_grafos(atual: dict[str, Any], proposto: dict[str, Any]) -> dict[str, Any]:
    """Diff por id (nodes/edges adicionados/removidos/alterados) + `meta_alterada`."""

    def _por_id(itens: Any) -> dict[str, Any]:
        return {str(i.get("id")): i for i in itens or [] if isinstance(i, dict) and i.get("id")}

    diff: dict[str, Any] = {}
    for chave in ("nodes", "edges"):
        de, para = _por_id(atual.get(chave)), _por_id(proposto.get(chave))
        diff[chave] = {
            "adicionados": sorted(set(para) - set(de)),
            "removidos": sorted(set(de) - set(para)),
            "alterados": sorted(i for i in set(de) & set(para) if de[i] != para[i]),
        }
    diff["meta_alterada"] = (atual.get("meta") or {}) != (proposto.get("meta") or {})
    return diff
