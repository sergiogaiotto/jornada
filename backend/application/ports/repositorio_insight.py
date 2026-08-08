"""Porta de persistência do Pergunte aos Dados (M10 parte 3) — leituras que a
camada semântica consome (OS, snapshot com Previsto congelado, telemetria,
segmentos p/ fallback de holdout) + ledger `invocacao` (via_ai §4.1) e outbox (§2.3).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (mesma instância por app — tipagem estrutural).
"""

import uuid
from datetime import datetime
from typing import Protocol

from domain.agentes.modelos import Invocacao
from domain.audiencia.modelos import Segmento
from domain.campanha.modelos import OS, EventoDominio
from domain.governanca.modelos import Snapshot
from domain.lancamento.modelos import Launch, TelemetryEvent


class RepositorioInsight(Protocol):
    # --- OS / snapshot (escopo de tenant via OS — §4.1) ---
    def obter_os(self, tenant_id: str, os_id: uuid.UUID) -> OS | None: ...

    def listar_snapshots(self, os_id: uuid.UUID) -> list[Snapshot]: ...

    def listar_launches(self, snapshot_id: uuid.UUID) -> list[Launch]:
        """Régua do realizado = snapshot do launch de referência (mesma regra do
        monitor T13 — §1.1.2)."""
        ...

    def listar_segmentos(self, os_id: uuid.UUID) -> list[Segmento]:
        """Fallback de `holdout_pct` quando a OS não congelou experimento (§4.1)."""
        ...

    # --- telemetry_event (§4.1) ---
    def listar_telemetria(
        self, os_id: uuid.UUID, apos_id: int | None = None
    ) -> list[TelemetryEvent]: ...

    # --- Ledger via_ai (`invocacao` §4.1) + outbox (§2.3) ---
    def adicionar_invocacao(self, invocacao: Invocacao) -> None: ...

    # J02: gasto MEDIDO do teto de tokens (NULL conta 0 — régua do I04).
    def somar_tokens(self, tenant_id: str, desde: datetime) -> int: ...

    def adicionar_evento(self, evento: EventoDominio) -> None: ...
