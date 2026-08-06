"""Porta de persistência do núcleo OS/governança (M1) + outbox `domain_event` (§2.3).

Portas = Protocols Python (§2.1); adapters em `adapters/persistence/` implementam.
Escopo de tenant: OS por (tenant_id); pendência/sla_clock/eventos herdam o escopo da OS.
"""

import uuid
from typing import Protocol

from domain.campanha.modelos import OS, EventoDominio, Pendencia, SlaClock


class RepositorioOs(Protocol):
    # --- OS ---
    def adicionar_os(self, os_: OS) -> None: ...

    def obter_os(self, tenant_id: str, os_id: uuid.UUID) -> OS | None: ...

    def obter_os_por_codigo(self, codigo: str, tenant_id: str | None = None) -> OS | None:
        """`os.codigo` é unique POR TENANT (achado 22/UAT5 — migração 0014). Sem
        `tenant_id` a busca é GLOBAL: só para chamadores legitimamente cross-tenant."""
        ...

    def listar_os(self, tenant_id: str, limit: int, offset: int) -> list[OS]: ...

    def salvar_os(self, os_: OS) -> None: ...

    def proximo_sequencial_os(self, ano: int, tenant_id: str | None = None) -> int:
        """Sequencial para gerar codigo `OS-{ano}-{seq:04d}` quando não informado —
        contado DENTRO do tenant (achado 22/UAT5: o número não conta o volume dos
        outros clientes)."""
        ...

    # --- Pendências ---
    def adicionar_pendencia(self, pendencia: Pendencia) -> None: ...

    def obter_pendencia(self, pendencia_id: uuid.UUID) -> Pendencia | None: ...

    def listar_pendencias(self, os_id: uuid.UUID) -> list[Pendencia]: ...

    def proximo_numero_pendencia(self, os_id: uuid.UUID) -> int: ...

    def salvar_pendencia(self, pendencia: Pendencia) -> None: ...

    # --- SLA clocks ---
    def adicionar_sla_clock(self, clock: SlaClock) -> None: ...

    def listar_sla_clocks(self, os_id: uuid.UUID) -> list[SlaClock]: ...

    def salvar_sla_clock(self, clock: SlaClock) -> None: ...

    # --- Outbox (§2.3) ---
    def adicionar_evento(self, evento: EventoDominio) -> None: ...

    def listar_eventos(
        self, os_id: uuid.UUID | None = None, tipo: str | None = None
    ) -> list[EventoDominio]: ...
