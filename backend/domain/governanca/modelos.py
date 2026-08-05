"""Entidades do contexto governança — espelham 1:1 o DDL do SDD §4.1 (sem I/O).

`snapshot` (pacote imutável de aprovação — hash COMPOSTO sha256 de
JGC+SQL+criativos+política+custo+experimento, §8-M8) e `aprovacao` (link mágico:
token armazenado apenas como hash, uso único, expira; A4: variação de custo >10%
após aprovação INVALIDA a aprovação — colunas `invalidada_em/invalidada_motivo`,
emenda §4.1 / migração 0006).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

DECISOES: tuple[str, ...] = ("aprovado", "aprovado_ressalvas", "reprovado")

# A4 (§8-M8): tolerância de variação de custo entre o snapshot aprovado e o custo
# previsto corrente — acima disso a aprovação é invalidada (snapshot novo obrigatório).
VARIACAO_CUSTO_MAX = 0.10


@dataclass
class Snapshot:
    """Tabela `snapshot` §4.1 — pacote imutável de aprovação.

    `hash` = sha256 do JSON canônico dos componentes (JGC+SQL+criativos+política+
    custo+experimento — snapshot.py); `previsto` = Previsto congelado da simulação.
    Sem tenant_id próprio (DDL §4.1): o escopo vem da OS referenciada.
    """

    id: uuid.UUID
    os_id: uuid.UUID
    hash: str  # char(64) unique — hash composto (snapshot.py)
    conteudo: dict[str, Any]
    previsto: dict[str, Any] | None
    created_at: datetime | None = None


@dataclass
class Aprovacao:
    """Tabela `aprovacao` §4.1 — link mágico (T10).

    O token em claro NUNCA é persistido: só `token_hash` (sha256). Uso único: uma
    `decisao` preenchida encerra o link (A3). `decidido_meta` registra ip/device.
    """

    id: uuid.UUID
    snapshot_id: uuid.UUID
    token_hash: str  # char(64) — sha256 do token em claro (retornado uma única vez)
    expira_em: datetime
    alcada: str  # papel da faixa de alçada da política (§11.4 `alcadas`)
    decisao: str | None = None  # DECISOES
    decidido_em: datetime | None = None
    decidido_meta: dict[str, Any] | None = None  # {ip, device, decidido_por?}
    ressalvas: list[dict[str, Any]] = field(default_factory=list)  # viram pendências (A3)
    # A4 — emenda §4.1 (migração 0006): variação de custo >10% pós-aprovação
    invalidada_em: datetime | None = None
    invalidada_motivo: str | None = None
