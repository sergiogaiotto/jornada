"""Porta de persistência do criativo (M6) — tabela auxiliar `criativo` (§4.1 nota;
migração 0003) + ledger `invocacao` e outbox (§2.3).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (mesma instância por app — tipagem estrutural).
"""

import uuid
from datetime import datetime
from typing import Protocol

from domain.agentes.modelos import Invocacao
from domain.campanha.modelos import EventoDominio
from domain.criativo.modelos import Criativo


class RepositorioCriativo(Protocol):
    # --- Criativos (tabela auxiliar `criativo` — migração 0003) ---
    def adicionar_criativo(self, criativo: Criativo) -> None: ...

    def obter_criativo(self, criativo_id: uuid.UUID) -> Criativo | None: ...

    def listar_criativos(self, os_id: uuid.UUID) -> list[Criativo]: ...

    def salvar_criativo(self, criativo: Criativo) -> None: ...

    # --- Ledger via_ai (§4.1 `invocacao`) e outbox (§2.3) ---
    def adicionar_invocacao(self, invocacao: Invocacao) -> None: ...

    # J02: gasto MEDIDO do teto de tokens (NULL conta 0 — régua do I04).
    def somar_tokens(self, tenant_id: str, desde: datetime) -> int: ...

    def adicionar_evento(self, evento: EventoDominio) -> None: ...
