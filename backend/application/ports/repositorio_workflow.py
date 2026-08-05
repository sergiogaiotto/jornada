"""Porta de persistência da esteira (M2) — `etapa_workflow` + `hike_import_log` (§4.1).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E a
`RepositorioOs` (mesma instância por app — tipagem estrutural). Inclui o outbox
`adicionar_evento` (§2.3) para o serviço registrar eventos sem depender da porta de OS.
"""

import uuid
from typing import Protocol

from domain.campanha.modelos import EventoDominio
from domain.esteira.modelos import EtapaWorkflow, HikeImportLog


class RepositorioWorkflow(Protocol):
    # --- Etapas (etapa_workflow §4.1) ---
    def adicionar_etapa(self, etapa: EtapaWorkflow) -> None: ...

    def listar_etapas(self, os_id: uuid.UUID) -> list[EtapaWorkflow]:
        """Etapas da OS ordenadas por `ordem`."""
        ...

    def salvar_etapa(self, etapa: EtapaWorkflow) -> None: ...

    # --- Log de import Hike (hike_import_log — §4.1 nota/migração 0002) ---
    def adicionar_hike_log(self, log: HikeImportLog) -> None: ...

    def listar_hike_logs(self, tenant_id: str) -> list[HikeImportLog]: ...

    # --- Outbox (§2.3) ---
    def adicionar_evento(self, evento: EventoDominio) -> None: ...
