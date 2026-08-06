"""RepositorioPurge — porta do purge de retenção (§10.4), atrás de porta (§2.1).

Implementada por `RepositorioOsMemoria` e `RepositorioSql` na MESMA instância das
demais portas (tipagem estrutural §2.1). Só as operações de DESTRUIÇÃO vivem aqui: a
régua (`retencao_dias`) vem da `PublicacoesPort`, fonte única da política em runtime
(achado 8 do UAT #5) — o purge não tem, nem pode ter, uma fonte própria.

Contrato deliberado das operações: **uma** função por tabela, com `aplicar` como
parâmetro, em vez de um par contar/remover. Dry-run e execução compartilham
literalmente o mesmo predicado — assim o relatório do dry-run não pode divergir do que
a execução apaga (divergência aqui seria o pior bug possível: o operador aprova um
número e o sistema destrói outro). Devolvem SEMPRE a quantidade de linhas ELEGÍVEIS.
"""

from datetime import datetime
from typing import Protocol

from domain.campanha.modelos import EventoDominio


class RepositorioPurge(Protocol):
    def purgar_telemetria(self, tenant_id: str, corte: datetime, *, aplicar: bool) -> int:
        """`telemetry_event` do tenant com `ts` < `corte` (§10.4). `aplicar=False` só
        conta. Devolve o total elegível."""
        ...

    def purgar_dc_cache(self, tenant_id: str, corte: datetime, *, aplicar: bool) -> int:
        """`dc_segment_cache` do tenant com `atualizado_em` < `corte` (§10.4). Linha SEM
        `atualizado_em` NUNCA é elegível: sem data não há como provar que expirou, e o
        default de dado irreversível é preservar."""
        ...

    def adicionar_evento(self, evento: EventoDominio) -> None:
        """Outbox §2.3 — a destruição é registrada em `domain_event` (§10.4)."""
        ...
