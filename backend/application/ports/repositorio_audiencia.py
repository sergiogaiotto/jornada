"""Porta de persistência da audiência (M5) — `segmento`, `certificado_elegibilidade`,
`dc_segment_cache` (§4.1) + ledger `invocacao` e outbox (§2.3).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (mesma instância por app — tipagem estrutural).
"""

import uuid
from datetime import datetime
from typing import Protocol

from domain.agentes.modelos import Invocacao
from domain.audiencia.modelos import CertificadoElegibilidade, DcSegmentCache, Segmento
from domain.campanha.modelos import EventoDominio


class RepositorioAudiencia(Protocol):
    # --- Segmentos (tabela `segmento` §4.1) ---
    def adicionar_segmento(self, segmento: Segmento) -> None: ...

    def obter_segmento(self, segmento_id: uuid.UUID) -> Segmento | None: ...

    def listar_segmentos(self, os_id: uuid.UUID) -> list[Segmento]: ...

    def salvar_segmento(self, segmento: Segmento) -> None: ...

    # --- Certificados (tabela `certificado_elegibilidade` §4.1) ---
    def adicionar_certificado(self, certificado: CertificadoElegibilidade) -> None: ...

    def listar_certificados(self, os_id: uuid.UUID) -> list[CertificadoElegibilidade]:
        """Certificados da OS em ordem de emissão (o último é o vigente)."""
        ...

    # --- Cache Data Cloud (tabela `dc_segment_cache` §4.1 — T5a) ---
    def salvar_dc_cache(self, entrada: DcSegmentCache) -> None: ...

    def obter_dc_cache(self, tenant_id: str, segmento_id: str) -> DcSegmentCache | None: ...

    def listar_dc_cache(self, tenant_id: str) -> list[DcSegmentCache]: ...

    # --- Ledger via_ai (§4.1 `invocacao`) e outbox (§2.3) ---
    def adicionar_invocacao(self, invocacao: Invocacao) -> None: ...

    # J02: gasto MEDIDO do teto de tokens (NULL conta 0 — régua do I04).
    def somar_tokens(self, tenant_id: str, desde: datetime) -> int: ...

    def adicionar_evento(self, evento: EventoDominio) -> None: ...
