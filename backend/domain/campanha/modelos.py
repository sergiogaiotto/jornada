"""Entidades do contexto campanha — espelham 1:1 o DDL do SDD §4.1 (sem I/O).

`os`, `pendencia`, `sla_clock` e a linha do outbox `domain_event` (§2.3).
Saúde NÃO é atributo de nenhuma entidade: é sempre derivada (ver saude.py).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

FASES: tuple[str, ...] = (
    "pensada",
    "discutida",
    "criada",
    "avaliada",
    "configurada",
    "disparada",
    "monitorada",
    "encerrada",
)
TSHIRTS: tuple[str, ...] = ("P", "M", "G", "GG")
TIPOS_PENDENCIA: tuple[str, ...] = ("risk", "assumption", "issue", "dependency")
SEVERIDADES: tuple[str, ...] = ("baixa", "media", "alta")
STATUS_PENDENCIA: tuple[str, ...] = ("aberta", "resolvida", "aceita")
ESTADOS_SLA: tuple[str, ...] = ("correndo", "pausado_cliente", "bloqueado_pendencia", "concluido")
SAUDES: tuple[str, ...] = ("normal", "em_risco")


@dataclass
class OS:
    """Campanha/Ordem de Serviço (tabela `os` §4.1)."""

    id: uuid.UUID
    tenant_id: str
    codigo: str  # ex. OS-2026-0457 (unique global, como no DDL)
    nome: str
    tshirt: str  # P|M|G|GG
    fase: str  # FASES
    briefing: dict[str, Any]
    frozen: dict[str, Any] | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


@dataclass
class Pendencia:
    """Tabela `pendencia` §4.1 — item bloqueante herdado do Hike (§14).

    Sem tenant_id próprio (DDL §4.1): o escopo de tenant vem da OS referenciada.
    """

    id: uuid.UUID
    os_id: uuid.UUID
    numero: int
    tipo: str | None  # risk|assumption|issue|dependency
    titulo: str
    descricao: str | None
    severidade: str | None  # baixa|media|alta
    bloqueante: bool
    bloqueia_etapa: str | None  # None = bloqueia qualquer avanço de fase
    status: str  # aberta|resolvida|aceita
    accountable: uuid.UUID | None
    aceite: dict[str, Any] | None  # {por, em, justificativa}
    origem: str | None
    via_ai: bool
    created_at: datetime


@dataclass
class SlaClock:
    """Tabela `sla_clock` §4.1 — estados correndo|pausado_cliente|bloqueado_pendencia|concluido."""

    id: uuid.UUID
    os_id: uuid.UUID
    etapa: str
    prazo: datetime
    estado: str
    pausas: list[dict[str, Any]] = field(default_factory=list)  # [{de, ate, motivo}]


@dataclass
class EventoDominio:
    """Linha do outbox `domain_event` (§2.3/§4.1); `id` é atribuído pela persistência."""

    tenant_id: str
    type: str  # tipos mínimos do §2.3 (ex.: os.phase_changed, pendencia.opened)
    payload: dict[str, Any]
    actor: str
    via_ai: bool
    created_at: datetime
    os_id: uuid.UUID | None = None
    id: int | None = None
