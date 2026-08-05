"""Hash composto do snapshot (§4.1/§8-M8) — CÓDIGO PURO, determinístico.

`snapshot.hash` = sha256 do JSON canônico (mesma canonicalização do JGC — RFC 8785
simplificado, domain/jornada/canonico.py) do dicionário de componentes com EXATAMENTE
as seis chaves do contrato: JGC + SQL + criativos + política + custo + experimento.
Qualquer mudança em qualquer componente ⇒ hash novo ⇒ snapshot novo (imutável §1.1.1).
"""

import hashlib
from typing import Any

from domain.jornada.canonico import canonicalizar

COMPONENTES: tuple[str, ...] = ("jgc", "sql", "criativos", "politica", "custo", "experimento")


def hash_composto(componentes: dict[str, Any]) -> str:
    """sha256 hex (64 chars — `snapshot.hash` char(64) §4.1) dos 6 componentes."""
    faltantes = set(COMPONENTES) - set(componentes)
    if faltantes:
        raise ValueError(f"Componentes ausentes no hash composto (§8-M8): {sorted(faltantes)}")
    base = {chave: componentes[chave] for chave in COMPONENTES}
    return hashlib.sha256(canonicalizar(base).encode("utf-8")).hexdigest()
