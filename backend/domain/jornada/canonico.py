"""Canonicalização do JGC (§5): sha256 do JSON canônico = hash da versão.

Implementação PRÓPRIA e simples da canonicalização no espírito do RFC 8785 (JCS),
suficiente para o twin (decisão registrada no CHANGELOG-SDD.md — M7): chaves ordenadas
(sort_keys), separadores mínimos (`,`/`:`), UTF-8 sem escape ASCII. Diferença
consciente vs RFC 8785 pleno: números seguem o repr do `json` da stdlib (o JGC usa
inteiros e decimais simples — pcts, horas — onde ambos coincidem). Determinístico por
construção: mesmo grafo ⇒ mesmo hash em qualquer processo/plataforma.
"""

import hashlib
import json
from typing import Any


def canonicalizar(obj: Any) -> str:
    """JSON canônico (chaves ordenadas + separadores mínimos + UTF-8)."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def hash_jgc(grafo: dict[str, Any]) -> str:
    """sha256 hex (64 chars — `jornada_versao.hash` char(64) §4.1) do JGC canônico."""
    return hashlib.sha256(canonicalizar(grafo).encode("utf-8")).hexdigest()
