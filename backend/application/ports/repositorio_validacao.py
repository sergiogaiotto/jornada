"""Porta de persistência da validação/War Room (M4) — `validacao_campo`, `os_thread`,
`documento_portao` (§4.1 nota final; migração 0003).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (mesma instância por app — tipagem estrutural). Inclui `listar_etapas` (o GO
congela SLAs a partir do workflow da esteira, quando materializado) e o outbox (§2.3).
"""

import uuid
from typing import Protocol

from domain.campanha.modelos import EventoDominio
from domain.esteira.modelos import EtapaWorkflow
from domain.validacao.modelos import DocumentoPortao, ThreadWarRoom, ValidacaoCampo


class RepositorioValidacao(Protocol):
    # --- Validações campo-a-campo (validacao_campo) ---
    def adicionar_validacao(self, validacao: ValidacaoCampo) -> None: ...

    def listar_validacoes(self, os_id: uuid.UUID, campo: str | None = None) -> list[ValidacaoCampo]:
        """Validações da OS em ordem cronológica (a última do campo é a vigente)."""
        ...

    # --- Threads do War Room (os_thread) ---
    def adicionar_thread(self, thread: ThreadWarRoom) -> None: ...

    def listar_threads(self, os_id: uuid.UUID) -> list[ThreadWarRoom]: ...

    # --- Documentos de portão (documento_portao) ---
    def adicionar_documento(self, documento: DocumentoPortao) -> None: ...

    def listar_documentos(
        self, os_id: uuid.UUID, portao: str | None = None
    ) -> list[DocumentoPortao]: ...

    # --- Esteira (leitura p/ congelar SLAs no GO) ---
    def listar_etapas(self, os_id: uuid.UUID) -> list[EtapaWorkflow]: ...

    # --- Outbox (§2.3) ---
    def adicionar_evento(self, evento: EventoDominio) -> None: ...
