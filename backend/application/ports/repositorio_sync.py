"""Porta de persistência do compilador plan/apply (M9) — `sync_run` e
`resource_registry` (§4.1), mais as leituras que os guardas do apply exigem
(snapshot/OS, aprovação §5.4.4, certificado M5-A3, jornada do twin) e o outbox (§2.3).
Fatia 2 do M9: `drift_check` (§4.1), `preflight_run` (tabela auxiliar — migração 0007)
e as leituras do pré-voo (segmento p/ last-mile do Guard, criativos p/ lint AMPscript).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (mesma instância por app — tipagem estrutural).
"""

import uuid
from typing import Protocol

from domain.audiencia.modelos import CertificadoElegibilidade, Segmento
from domain.campanha.modelos import OS, EventoDominio, Pendencia
from domain.criativo.modelos import Criativo
from domain.governanca.modelos import Aprovacao, Snapshot
from domain.jornada.modelos import (
    DriftCheck,
    JornadaVersao,
    PreflightRun,
    ResourceRegistry,
    SyncRun,
)


class RepositorioSync(Protocol):
    # --- OS / snapshot (escopo de tenant via OS — §4.1) ---
    def obter_os(self, tenant_id: str, os_id: uuid.UUID) -> OS | None: ...

    def obter_snapshot(self, snapshot_id: uuid.UUID) -> Snapshot | None: ...

    def obter_snapshot_por_hash(self, hash_: str) -> Snapshot | None: ...

    def listar_snapshots(self, os_id: uuid.UUID) -> list[Snapshot]: ...

    # --- Guardas do apply (§5.4.4, M5-A3) ---
    def listar_aprovacoes(self, snapshot_id: uuid.UUID) -> list[Aprovacao]: ...

    def listar_certificados(self, os_id: uuid.UUID) -> list[CertificadoElegibilidade]: ...

    # --- Twin (grafo compilado + estado `publicado` §4.1) ---
    def listar_jornadas(self, os_id: uuid.UUID) -> list[JornadaVersao]: ...

    def salvar_jornada(self, jornada: JornadaVersao) -> None: ...

    # --- sync_run (§4.1) ---
    def adicionar_sync_run(self, run: SyncRun) -> None: ...

    def obter_sync_run(self, sync_run_id: uuid.UUID) -> SyncRun | None: ...

    def salvar_sync_run(self, run: SyncRun) -> None: ...

    def listar_sync_runs(
        self, snapshot_id: uuid.UUID, ambiente: str | None = None, fase: str | None = None
    ) -> list[SyncRun]:
        """Runs do snapshot em ordem de criação (o último é o corrente)."""
        ...

    # --- resource_registry (§4.1 — unique tenant+ambiente+external_key) ---
    def upsert_registro(self, registro: ResourceRegistry) -> None: ...

    def obter_registro(
        self, tenant_id: str, ambiente: str, external_key: str
    ) -> ResourceRegistry | None: ...

    def listar_registros(self, tenant_id: str, ambiente: str) -> list[ResourceRegistry]: ...

    def remover_registro(self, tenant_id: str, ambiente: str, external_key: str) -> None: ...

    # --- Pré-voo (M9 fatia 2 — `preflight_run` migração 0007; §8-M9) ---
    def adicionar_preflight(self, run: PreflightRun) -> None: ...

    def listar_preflights(
        self, snapshot_id: uuid.UUID, ambiente: str | None = None
    ) -> list[PreflightRun]:
        """Pré-voos do snapshot em ordem de criação (o último é o vigente)."""
        ...

    # --- drift_check (§4.1 — monitor §5.4.5) ---
    def adicionar_drift_check(self, check: DriftCheck) -> None: ...

    def obter_drift_check(self, drift_id: uuid.UUID) -> DriftCheck | None: ...

    def salvar_drift_check(self, check: DriftCheck) -> None: ...

    def listar_drift_checks(self, snapshot_id: uuid.UUID) -> list[DriftCheck]:
        """Checks do snapshot em ordem de verificação (histórico do job §5.4.5)."""
        ...

    # --- Leituras do pré-voo (last-mile Guard / lint AMPscript — §8-M9) ---
    def listar_segmentos(self, os_id: uuid.UUID) -> list[Segmento]: ...

    def listar_criativos(self, os_id: uuid.UUID) -> list[Criativo]: ...

    # --- Pendências (dedupe da pendência automática de drift — A4) ---
    def listar_pendencias(self, os_id: uuid.UUID) -> list[Pendencia]: ...

    # --- Outbox (§2.3) ---
    def adicionar_evento(self, evento: EventoDominio) -> None: ...

    def listar_eventos(
        self, os_id: uuid.UUID | None = None, tipo: str | None = None
    ) -> list[EventoDominio]: ...
