"""Porta de persistência da Torre de Lançamento (M10 parte 1) — `launch`,
`telemetry_event` (§4.1) e `incidente` (tabela auxiliar — migração 0008), mais as
leituras que os guardas exigem (snapshot/OS, sync_runs do apply ok §8-M10) e o
outbox (§2.3).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (mesma instância por app — tipagem estrutural).
"""

import uuid
from typing import Protocol

from domain.audiencia.modelos import Segmento
from domain.campanha.modelos import OS, EventoDominio
from domain.governanca.modelos import Snapshot
from domain.jornada.modelos import SyncRun
from domain.lancamento.modelos import Incidente, Launch, TelemetryEvent


class RepositorioLancamento(Protocol):
    # --- OS / snapshot (escopo de tenant via OS — §4.1) ---
    def obter_os(self, tenant_id: str, os_id: uuid.UUID) -> OS | None: ...

    def obter_os_por_codigo(self, codigo: str, tenant_id: str | None = None) -> OS | None:
        """Extract referencia OS por `codigo` (§4.1) — o loader resolve p/ id.

        `tenant_id` é OBRIGATÓRIO na prática aqui: desde a emenda E22 (achado 22/UAT5,
        migração 0014) o `codigo` é unique POR TENANT, então dois clientes podem ter
        `OS-2026-0457` e a busca global devolveria uma OS arbitrária — o batch do outro
        sumiria calado em `ignorados`. O default existe só para casar com a assinatura
        da porta `RepositorioOs` (§2.1, mesma instância implementa as duas)."""
        ...

    def obter_snapshot(self, snapshot_id: uuid.UUID) -> Snapshot | None: ...

    def listar_snapshots(self, os_id: uuid.UUID) -> list[Snapshot]: ...

    def listar_segmentos(self, os_id: uuid.UUID) -> list[Segmento]:
        """Fallback do monitor: `holdout_pct` do segmento quando a OS não congelou
        experimento no snapshot (§4.1 `segmento.holdout_pct` default 10.0)."""
        ...

    # --- Guarda do armar (§8-M10: exige apply ok — sync_run §4.1) ---
    def listar_sync_runs(
        self, snapshot_id: uuid.UUID, ambiente: str | None = None, fase: str | None = None
    ) -> list[SyncRun]: ...

    # --- launch (§4.1) ---
    def adicionar_launch(self, launch: Launch) -> None: ...

    def obter_launch(self, launch_id: uuid.UUID) -> Launch | None: ...

    def listar_launches(self, snapshot_id: uuid.UUID) -> list[Launch]: ...

    def salvar_launch(self, launch: Launch) -> None: ...

    # --- telemetry_event (§4.1 — id bigint pela persistência) ---
    def adicionar_telemetria(self, evento: TelemetryEvent) -> None: ...

    def listar_telemetria(
        self, os_id: uuid.UUID, apos_id: int | None = None
    ) -> list[TelemetryEvent]:
        """Eventos da OS em ordem de ingestão; `apos_id` = janela dos breakers
        (marco gravado no armar/retomada — launch.eventos)."""
        ...

    def maior_id_telemetria(self) -> int: ...

    # --- incidente (tabela auxiliar — migração 0008) ---
    def adicionar_incidente(self, incidente: Incidente) -> None: ...

    def listar_incidentes(
        self,
        os_id: uuid.UUID | None = None,
        launch_id: uuid.UUID | None = None,
        estado: str | None = None,
    ) -> list[Incidente]: ...

    def salvar_incidente(self, incidente: Incidente) -> None: ...

    # --- Outbox (§2.3) ---
    def adicionar_evento(self, evento: EventoDominio) -> None: ...

    def listar_eventos(
        self, os_id: uuid.UUID | None = None, tipo: str | None = None
    ) -> list[EventoDominio]: ...
