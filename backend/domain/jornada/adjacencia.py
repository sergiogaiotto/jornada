"""Adjacência do JGC — fonte ÚNICA para validação, taxímetro e simulador (emenda D07).

Três módulos precisam da mesma pergunta ("quais as saídas de cada nó?"): o validador
(§5.3), o taxímetro (§8-M7) e o motor Monte Carlo (§6). Até o UAT #4 cada um tinha a
sua cópia — e a emenda A13 (aresta/regra malformada não pode estourar `KeyError`) foi
aplicada em duas delas. A terceira, o motor, ficou de fora: um `decisionSplit` cujas
`regras` não trazem `to` derrubava `POST /jornadas/{id}/simular` com HTTP 500. Pior, o
grafo que expôs isso foi gerado pelo próprio Flow (gpt-oss-120b) e passou na validação.

Uma cópia só, defensiva por contrato: aresta ou regra sem `from`/`to` é IGNORADA aqui —
quem reporta o erro ao usuário é sempre o `validar_grafo` (§5.3), com nó e regra
nomeados. Consumidores de adjacência jamais levantam exceção bruta por dado torto.
"""

from typing import Any


def saidas_do_grafo(grafo: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Saídas por nó: `edges` + regras de `decisionSplit` (que carregam `to` direto).

    Cada saída é `{id, from, to, cond}`. Para uma regra, `cond` é a `expr` e o `id`
    sintético é `{no}:{to}` — o taxímetro e o motor ignoram o `id`; a validação o usa
    para nomear o braço na mensagem de erro.
    """
    saidas: dict[str, list[dict[str, Any]]] = {}
    for aresta in grafo.get("edges") or []:
        if not isinstance(aresta, dict) or not aresta.get("from") or not aresta.get("to"):
            continue
        saidas.setdefault(str(aresta["from"]), []).append(aresta)
    for no in grafo.get("nodes") or []:
        if not isinstance(no, dict) or not no.get("id") or no.get("type") != "decisionSplit":
            continue
        for regra in no.get("data", {}).get("regras") or []:
            if not isinstance(regra, dict) or not regra.get("to"):
                continue
            saidas.setdefault(str(no["id"]), []).append(
                {
                    "id": f"{no['id']}:{regra['to']}",
                    "from": str(no["id"]),
                    "to": str(regra["to"]),
                    "cond": regra.get("expr"),
                }
            )
    return saidas
