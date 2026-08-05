"""Porta de persistência do chat de ajuda do Guia Interativo (M-Guia) — só o
ledger `invocacao` (via_ai §4.1): o chat é informativo (nenhuma ação de domínio,
nenhuma OS envolvida — `invocacao.os_id` fica NULL).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (mesma instância por app — tipagem estrutural).
"""

from typing import Protocol

from domain.agentes.modelos import Invocacao


class RepositorioAjuda(Protocol):
    def adicionar_invocacao(self, invocacao: Invocacao) -> None: ...
