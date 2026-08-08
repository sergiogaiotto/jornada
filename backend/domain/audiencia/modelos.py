"""Entidades do contexto audiência — espelham 1:1 o DDL do SDD §4.1 (sem I/O).

`segmento`, `certificado_elegibilidade` e `dc_segment_cache` (T5a: consulta, não cópia).
As 7 listas de supressão (§4.1 `lista_supressao`) são contrato FECHADO: o Guard
determinístico (agents/guard) valida presença de TODAS no WHERE do SQL público.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ORIGENS_SEGMENTO: tuple[str, ...] = ("estudio_sql", "data_cloud")

# §4.1 `lista_supressao.lista` — as 7 listas (ordem = precedência da política §11.4)
SETE_LISTAS: tuple[str, ...] = (
    "blacklist",
    "fraude",
    "nao_perturbe",
    "optout",
    "procon",
    "inadimplente",
    "reprovado_credito",
)

# Canais do volume de abordagem (§4.1 `segmento.volume_abordagem`)
CANAIS: tuple[str, ...] = ("email", "sms", "push", "whatsapp")

HOLDOUT_PCT_DEFAULT = 10.0  # DDL §4.1: `holdout_pct numeric(4,1) default 10.0`


@dataclass
class Segmento:
    """Tabela `segmento` §4.1 — audiência de uma OS (Estúdio SQL ou Data Cloud).

    Sem tenant_id próprio (DDL §4.1): o escopo vem da OS referenciada.
    """

    id: uuid.UUID
    os_id: uuid.UUID | None
    origem: str  # ORIGENS_SEGMENTO
    dc_segment_id: str | None = None
    sql_publico: str | None = None
    criterios_resumo: str | None = None
    contagem_bruta: int | None = None
    contagem_liquida: int | None = None
    waterfall: list[dict[str, Any]] = field(default_factory=list)  # [{etapa,corte,restante,motivo}]
    volume_abordagem: dict[str, Any] = field(default_factory=dict)  # {canal: {n, pct}}
    holdout_pct: float = HOLDOUT_PCT_DEFAULT
    frescor: dict[str, Any] = field(default_factory=dict)  # {fonte: ultima_atualizacao}


@dataclass
class CertificadoElegibilidade:
    """Tabela `certificado_elegibilidade` §4.1 — emitido SOMENTE pelo Guard (zero LLM).

    `last_mile` fica nulo até a re-varredura no disparo (M9/M10).
    """

    id: uuid.UUID
    os_id: uuid.UUID
    hash: str  # sha256 hex do conteúdo canônico do certificado
    suprimidos: dict[str, int]  # {lista: contagem} — as 7 listas (§4.1)
    liquido: int
    emitido_em: datetime
    valido_ate: datetime | None
    # §8-M5-A5 (K05, onda 7): PROVENIÊNCIA das contagens. False = os números vieram de
    # fixture/relatório pré-calculado (o read model NÃO executou o sql_publico); True é
    # reservado ao read model real. SEM default de propósito: cada construtor é obrigado
    # a declarar — um default aqui seria o "default otimista" que a auditoria do J01
    # apontou como a forma silenciosa de o overclaim voltar.
    contagens_derivadas_do_sql: bool
    last_mile: dict[str, Any] | None = None


@dataclass
class DcSegmentCache:
    """Tabela `dc_segment_cache` §4.1 — T5a: consulta ao Data Cloud, não cópia."""

    id: str  # id do segmento no Data Cloud (ex.: DC-SEG-001)
    tenant_id: str
    nome: str | None
    criterios_resumo: str | None
    membros: int | None
    dmos: list[str] = field(default_factory=list)
    republicado_em: datetime | None = None
    ciclo: str | None = None
    status: str | None = None
    atualizado_em: datetime | None = None
