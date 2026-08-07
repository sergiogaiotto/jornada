"""Canonicalização do JGC (§5): sha256 do JSON canônico = hash da versão.

Implementação PRÓPRIA e simples da canonicalização no espírito do RFC 8785 (JCS),
suficiente para o twin (decisão registrada no CHANGELOG-SDD.md — M7): chaves ordenadas
(sort_keys), separadores mínimos (`,`/`:`), UTF-8 sem escape ASCII. Diferença
consciente vs RFC 8785 pleno: números seguem o repr do `json` da stdlib (o JGC usa
inteiros e decimais simples — pcts, horas — onde ambos coincidem). Determinístico por
construção: mesmo grafo ⇒ mesmo hash em qualquer processo/plataforma.

Emenda I03 (onda 5): no RFC 8785 a ordem de ARRAY é significativa — mas `nodes` e
`edges` do JGC são CONJUNTOS (o grafo é definido por ids e refs `from`/`to`, não pela
posição na lista). O mesmo grafo lógico com as listas permutadas produzia hash
diferente → externalKey diferente → o plan do M9 marcava destruir/recriar tudo no SFMC
("reinicia contatos em espera") para um grafo IDÊNTICO. `normalizar_grafo` ordena as
duas listas-conjunto do topo — por `id`, que preserva os golden (já em ordem de id) —
e NUNCA toca arrays dentro de `data` (regras de decisionSplit têm precedência de
avaliação com `senao`; braços/classes/fields carregam ordem própria).
"""

import hashlib
import json
from typing import Any


def normalizar_grafo(grafo: dict[str, Any]) -> dict[str, Any]:
    """Ordena as listas-CONJUNTO do topo (nodes por id; edges por id, com from/to de
    desempate) — Emenda I03. Roda na PERSISTÊNCIA, não só no hash: com o grafo
    armazenado já canônico, hash, compilador, export, preview e drift enxergam a MESMA
    ordem (normalizar só o hash deixaria dois grafos de hash igual compilando
    activities em ordens diferentes — falso drift e `alterar` destrutivo no plan).

    Defensivo por contrato (como a adjacência D07): lista com item sem `id`/não-objeto
    fica INTACTA — quem reporta o erro é o `validar_grafo` (§5.3)."""
    if not isinstance(grafo, dict):
        return grafo
    novo = dict(grafo)
    nos = novo.get("nodes")
    if isinstance(nos, list) and all(isinstance(n, dict) and n.get("id") for n in nos):
        novo["nodes"] = sorted(nos, key=lambda n: str(n["id"]))
    arestas = novo.get("edges")
    if isinstance(arestas, list) and all(isinstance(a, dict) and a.get("id") for a in arestas):
        novo["edges"] = sorted(
            arestas, key=lambda a: (str(a["id"]), str(a.get("from")), str(a.get("to")))
        )
    return novo


def canonicalizar(obj: Any) -> str:
    """JSON canônico (chaves ordenadas + separadores mínimos + UTF-8)."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def hash_jgc(grafo: dict[str, Any]) -> str:
    """sha256 hex (64 chars — `jornada_versao.hash` char(64) §4.1) do JGC canônico.

    Normaliza a ordem de nodes/edges ANTES de hashear (Emenda I03): permutar as listas
    não muda o grafo, então não pode mudar o hash. INVERSÃO: remover o
    `normalizar_grafo` daqui deixa test_I03_hash_canonico vermelho."""
    return hashlib.sha256(canonicalizar(normalizar_grafo(grafo)).encode("utf-8")).hexdigest()
