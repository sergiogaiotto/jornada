"""Porta de persistência do intake (M3) — `pedido` + ledger `invocacao` (§4.1).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (`RepositorioOs`, `RepositorioWorkflow`) na mesma instância — tipagem estrutural.
Inclui o outbox `adicionar_evento` (§2.3) para o serviço registrar `agent.invoked` etc.
"""

import uuid
from datetime import datetime
from typing import Protocol

from domain.agentes.modelos import Invocacao
from domain.campanha.modelos import EventoDominio
from domain.intake.modelos import Pedido


class RepositorioIntake(Protocol):
    # --- Pedido (§4.1) ---
    def adicionar_pedido(self, pedido: Pedido) -> None: ...

    def obter_pedido(self, tenant_id: str, pedido_id: uuid.UUID) -> Pedido | None: ...

    def listar_pedidos(self, tenant_id: str) -> list[Pedido]: ...

    def salvar_pedido(self, pedido: Pedido) -> None: ...

    # --- Ledger via_ai (`invocacao` §4.1 — LGPD Art. 20) ---
    def adicionar_invocacao(self, invocacao: Invocacao) -> None: ...

    # J02: gasto MEDIDO do teto de tokens (NULL conta 0 — régua do I04).
    def somar_tokens(self, tenant_id: str, desde: datetime) -> int: ...

    def listar_invocacoes(self, tenant_id: str) -> list[Invocacao]: ...

    # --- Outbox (§2.3) ---
    def adicionar_evento(self, evento: EventoDominio) -> None: ...
