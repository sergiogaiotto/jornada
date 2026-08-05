"""Entidades do contexto mesh de agentes — espelham o DDL §4.1 (sem I/O).

No M3 só a linha do ledger `invocacao` (via_ai — LGPD Art. 20: reconstruível) é
necessária; `agente`/`skill_versao`/`harness_*` entram com o Ateliê (M12). Enquanto a
tabela `agente` não tem linhas, `agente_id` é derivado deterministicamente do nome
canônico do agente (uuid5), preservando a referência estável no ledger.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def agente_uuid(nome: str) -> uuid.UUID:
    """uuid determinístico do agente pelo nome canônico (roster §7.2)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"jornada/agente/{nome}")


@dataclass
class Invocacao:
    """Linha do ledger `invocacao` §4.1 — toda ação de agente (via_ai) é reconstruível."""

    id: uuid.UUID
    tenant_id: str
    os_id: uuid.UUID | None
    agente_id: uuid.UUID | None
    skill_versao: str | None
    usuario_portador: uuid.UUID
    input: dict[str, Any] | None
    output: dict[str, Any] | None
    evidencias: list[Any] = field(default_factory=list)
    judge: dict[str, Any] | None = None
    aceito_por: uuid.UUID | None = None
    aceito_em: datetime | None = None
    tokens: int | None = None
    latencia_ms: int | None = None
    created_at: datetime | None = None
