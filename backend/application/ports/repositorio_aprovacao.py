"""Porta de persistência dos portões T9 + aprovação T10 (M8 parte 2) — `snapshot` e
`aprovacao` (§4.1), leitura de jornada/segmento/criativos/certificado/experimento
(componentes do hash composto e estados dos portões), pendências (ressalvas → A3)
e outbox (§2.3).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (mesma instância por app — tipagem estrutural).
"""

import uuid
from typing import Protocol

from domain.audiencia.modelos import CertificadoElegibilidade, Segmento
from domain.campanha.modelos import OS, EventoDominio, Pendencia
from domain.criativo.modelos import Criativo
from domain.experimento.modelos import Experimento
from domain.governanca.modelos import Aprovacao, Snapshot
from domain.jornada.modelos import JornadaVersao


class RepositorioAprovacao(Protocol):
    # --- OS (escopo de tenant §4.1) ---
    def obter_os(self, tenant_id: str, os_id: uuid.UUID) -> OS | None: ...

    # --- Componentes dos portões/snapshot (leitura) ---
    def listar_jornadas(self, os_id: uuid.UUID) -> list[JornadaVersao]: ...

    def salvar_jornada(self, jornada: JornadaVersao) -> None: ...

    def listar_segmentos(self, os_id: uuid.UUID) -> list[Segmento]: ...

    def listar_criativos(self, os_id: uuid.UUID) -> list[Criativo]: ...

    def listar_certificados(self, os_id: uuid.UUID) -> list[CertificadoElegibilidade]: ...

    # --- Experimento (tabela `experimento` §4.1 — pré-registro pleno no M8) ---
    def adicionar_experimento(self, experimento: Experimento) -> None: ...

    def experimento_da_os(self, os_id: uuid.UUID) -> Experimento | None: ...

    # --- Snapshot (tabela `snapshot` §4.1) ---
    def adicionar_snapshot(self, snapshot: Snapshot) -> None: ...

    def obter_snapshot(self, snapshot_id: uuid.UUID) -> Snapshot | None: ...

    def obter_snapshot_por_hash(self, hash_: str) -> Snapshot | None:
        """`snapshot.hash` é unique (§4.1) — mesmo hash ⇒ mesmo pacote imutável."""
        ...

    def listar_snapshots(self, os_id: uuid.UUID) -> list[Snapshot]:
        """Snapshots da OS em ordem de criação (o último é o corrente)."""
        ...

    # --- Aprovação / link mágico (tabela `aprovacao` §4.1) ---
    def adicionar_aprovacao(self, aprovacao: Aprovacao) -> None: ...

    def obter_aprovacao_por_token_hash(self, token_hash: str) -> Aprovacao | None: ...

    def listar_aprovacoes(self, snapshot_id: uuid.UUID) -> list[Aprovacao]: ...

    def salvar_aprovacao(self, aprovacao: Aprovacao) -> None: ...

    # --- Pendências (ressalvas viram pendências — A3) ---
    def adicionar_pendencia(self, pendencia: Pendencia) -> None: ...

    def proximo_numero_pendencia(self, os_id: uuid.UUID) -> int: ...

    # --- Outbox (§2.3) ---
    def adicionar_evento(self, evento: EventoDominio) -> None: ...

    def listar_eventos(
        self, os_id: uuid.UUID | None = None, tipo: str | None = None
    ) -> list[EventoDominio]: ...
