"""Porta de persistência da jornada (M7) — `jornada_versao` (o twin §4.1), leitura de
`experimento` (validação §5.3/A3) e de `segmento` (volume do taxímetro A2) + ledger
`invocacao` e outbox (§2.3).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (mesma instância por app — tipagem estrutural).
"""

import uuid
from typing import Protocol

from domain.agentes.modelos import Invocacao
from domain.audiencia.modelos import Segmento
from domain.campanha.modelos import EventoDominio
from domain.experimento.modelos import Experimento
from domain.jornada.modelos import JornadaVersao


class RepositorioJornada(Protocol):
    # --- Twin (tabela `jornada_versao` §4.1) ---
    def adicionar_jornada(self, jornada: JornadaVersao) -> None: ...

    def obter_jornada(self, jornada_id: uuid.UUID) -> JornadaVersao | None: ...

    def listar_jornadas(self, os_id: uuid.UUID) -> list[JornadaVersao]:
        """Versões da OS em ordem de `versao` (a última é a corrente)."""
        ...

    def salvar_jornada(self, jornada: JornadaVersao) -> None: ...

    def proxima_versao(self, os_id: uuid.UUID) -> int:
        """Próximo `versao` da OS (unique(os_id, versao) §4.1)."""
        ...

    # --- Experimento (tabela `experimento` §4.1 — leitura p/ validação §5.3) ---
    def adicionar_experimento(self, experimento: Experimento) -> None: ...

    def experimento_da_os(self, os_id: uuid.UUID) -> Experimento | None:
        """Experimento mais recente da OS (None quando não há pré-registro)."""
        ...

    # --- Segmento (volume líquido p/ o taxímetro — A2) ---
    def listar_segmentos(self, os_id: uuid.UUID) -> list[Segmento]: ...

    # --- Ledger via_ai (§4.1 `invocacao`) e outbox (§2.3) ---
    def adicionar_invocacao(self, invocacao: Invocacao) -> None: ...

    def adicionar_evento(self, evento: EventoDominio) -> None: ...
