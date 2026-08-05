"""Porta das 7 listas de supressão (§4.1 `lista_supressao`) — consulta por contato.

O breaker `disparo_lista_supressao` (§8-M10-A2) pergunta em QUAIS listas um
`contato_hash` está — dev/teste usa o adapter de fixtures
(adapters/fontes/lista_supressao.py, seed §11.4 "7 listas com contagens"); o adapter
Postgres real entra sem tocar domínio/serviço (hexagonal §2.1).
"""

from typing import Protocol


class ListaSupressaoPort(Protocol):
    def listas_do_contato(self, tenant_id: str, contato_hash: str) -> list[str]:
        """Listas (§4.1: blacklist..reprovado_credito) que contêm o hash ([] = limpo)."""
        ...
