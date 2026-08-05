"""Guarda-corpo determinístico de telemetria (§10.2) — CÓDIGO PURO.

`telemetry_event` JAMAIS carrega msisdn/e-mail em claro: contato só como
`contato_hash` (sha256). O ingest (webhook ENS/extract loader) REJEITA payloads com
chaves de PII conhecidas ou valores com cara de e-mail — 422, nada é gravado.
"""

from __future__ import annotations

import re
from typing import Any

# Chaves proibidas em payload de telemetria (case-insensitive; §10.2)
CHAVES_PII: tuple[str, ...] = (
    "msisdn",
    "email",
    "e_mail",
    "e-mail",
    "telefone",
    "phone",
    "celular",
    "cpf",
)

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_CONTATO_HASH = re.compile(r"^[0-9a-f]{64}$")


def contato_hash_valido(contato_hash: str | None) -> bool:
    """`contato_hash` char(64) §4.1 — sha256 hex minúsculo (ou ausente)."""
    return contato_hash is None or bool(_CONTATO_HASH.fullmatch(contato_hash))


def pii_no_payload(payload: dict[str, Any] | None) -> str | None:
    """Motivo da rejeição quando o payload contém PII (None = limpo)."""
    if not payload:
        return None
    for chave, valor in payload.items():
        if chave.strip().lower().replace("-", "_") in {c.replace("-", "_") for c in CHAVES_PII}:
            return f"payload contém chave de PII proibida: {chave!r} (§10.2)."
        if isinstance(valor, str) and _EMAIL.search(valor):
            return f"payload contém valor com formato de e-mail em {chave!r} (§10.2)."
    return None
