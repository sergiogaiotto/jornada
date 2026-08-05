"""Entidades do contexto lançamento — espelham 1:1 o DDL do SDD §4.1 (sem I/O).

`launch` (T12: rampa de ondas 1%→10%→100%, breakers da política CONGELADA no armar),
`telemetry_event` (§4.1: NUNCA msisdn/e-mail — só `contato_hash` sha256) e `incidente`
(tabela auxiliar §4.1 nota final: "sev1..3, kill/retomada 2 aprovadores" — migração
0008). Caminho crítico 100% determinístico — breakers e kill JAMAIS dependem de LLM
(§10.6).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# §4.1 `launch.estado`
ESTADOS_LAUNCH: tuple[str, ...] = ("armado", "em_rampa", "pausado_breaker", "morto", "concluido")

# Estados em que o launch ainda "ocupa" o snapshot (re-armar → 409)
ESTADOS_ATIVOS: tuple[str, ...] = ("armado", "em_rampa", "pausado_breaker")

# §4.1 `launch.ondas` default — rampa 1% → 10% → 100% (§8-M10)
ONDAS_DEFAULT: tuple[dict[str, Any], ...] = ({"pct": 1}, {"pct": 10}, {"pct": 100})

# §4.1 `telemetry_event.tipo` — contrato FECHADO (comentário do DDL)
TIPOS_TELEMETRIA: tuple[str, ...] = (
    "sent",
    "delivered",
    "open",
    "click",
    "bounce",
    "optout",
    "conversion",
)
FONTES_TELEMETRIA: tuple[str, ...] = ("ens", "extract")

# `incidente` (§4.1 nota final) — severidades e estados
SEVERIDADES_INCIDENTE: tuple[str, ...] = ("sev1", "sev2", "sev3")
ESTADOS_INCIDENTE: tuple[str, ...] = ("aberto", "resolvido")

# Retomada (§8-M10): SEV1 exige 2 aprovadores DISTINTOS; demais, 1 humano (A1)
APROVADORES_RETOMADA_SEV1 = 2


@dataclass
class Launch:
    """Tabela `launch` §4.1 — Torre de Lançamento (T12).

    `breakers` = limites da política congelada no armar; `eventos` (jsonb) é o
    histórico auditável da rampa: armado, ondas, disparos de breaker, kill 2 etapas
    e aprovações de retomada (inclui `marco_telemetria` = id do último evento de
    telemetria no armar/retomada — janela de avaliação dos breakers).
    Sem tenant_id próprio (DDL §4.1): o escopo vem do snapshot → OS.
    """

    id: uuid.UUID
    snapshot_id: uuid.UUID
    ondas: list[dict[str, Any]] = field(default_factory=lambda: [dict(o) for o in ONDAS_DEFAULT])
    onda_atual: int = 0  # 0 = armado, nenhuma onda iniciada
    estado: str = "armado"  # ESTADOS_LAUNCH
    breakers: dict[str, Any] = field(default_factory=dict)
    eventos: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TelemetryEvent:
    """Tabela `telemetry_event` §4.1 — NUNCA msisdn/e-mail em claro (§10.2):
    contato só como `contato_hash` (sha256+salt do tenant). `id` é atribuído pela
    persistência (bigint identity)."""

    tenant_id: str
    tipo: str  # TIPOS_TELEMETRIA
    ts: datetime
    os_id: uuid.UUID | None = None
    no_jgc: str | None = None
    canal: str | None = None
    contato_hash: str | None = None  # char(64) — sha256 hex
    fonte: str | None = None  # FONTES_TELEMETRIA
    payload: dict[str, Any] | None = None
    id: int | None = None


@dataclass
class Incidente:
    """Tabela auxiliar `incidente` (§4.1 nota final; migração 0008) — incidentes
    TIPADOS da operação: breaker disparado (sev2), disparo p/ lista de supressão
    (SEV1 + kill automático — §8-M10-A2), kill manual.

    `meta` guarda a evidência do disparo e, na retomada, os aprovadores
    ({retomada: {aprovadores: [{por, em}]}} — SEV1 exige 2 DISTINTOS).
    Sem tenant_id próprio: o escopo vem da OS referenciada.
    """

    id: uuid.UUID
    os_id: uuid.UUID
    launch_id: uuid.UUID | None
    sev: str  # SEVERIDADES_INCIDENTE
    tipo: str  # optout|bounce|erro_entrega|burn_rate|disparo_lista_supressao|kill_manual
    titulo: str
    estado: str = "aberto"  # ESTADOS_INCIDENTE
    descricao: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    aberto_em: datetime | None = None
    resolvido_em: datetime | None = None
