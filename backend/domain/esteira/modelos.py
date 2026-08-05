"""Entidades do contexto esteira — espelham 1:1 o DDL do SDD §4.1 (sem I/O).

`etapa_workflow` (T4a: esteira ex-Hike) e a linha da tabela auxiliar `hike_import_log`
(§4.1, nota final: colunas na migração 0002). Checklist é jsonb `[{item, feito, por, em}]`
— subtarefas de Criativos/Acompanhamento; `em` gravado como ISO-8601 (paridade jsonb).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Ordem canônica das 7 etapas (comentário do DDL §4.1):
# briefing|discovery|audiencia|criativos|configuracao|disparo|acompanhamento
ETAPAS: tuple[str, ...] = (
    "briefing",
    "discovery",
    "audiencia",
    "criativos",
    "configuracao",
    "disparo",
    "acompanhamento",
)
ESTADOS_ETAPA: tuple[str, ...] = ("pendente", "em_andamento", "concluida", "bloqueada")

# Subtarefas padrão (§8-M2-A1: Criativos nasce com as 4; Acompanhamento com os
# checkpoints D+1/D+7/D+15). Conteúdo alinhado ao fluxo do M6/T6 — ver CHANGELOG-SDD.md.
SUBTAREFAS_CRIATIVOS: tuple[str, ...] = (
    "KV master definido",
    "Matriz canal×variante gerada",
    "Compliance de linguagem validado",
    "Células aprovadas",
)
CHECKPOINTS_ACOMPANHAMENTO: tuple[str, ...] = (
    "Checkpoint D+1",
    "Checkpoint D+7",
    "Checkpoint D+15",
)


@dataclass
class EtapaWorkflow:
    """Tabela `etapa_workflow` §4.1 — T4a: esteira ex-Hike.

    Sem tenant_id próprio (DDL §4.1): o escopo de tenant vem da OS referenciada.
    """

    id: uuid.UUID
    os_id: uuid.UUID
    ordem: int
    nome: str  # ETAPAS
    responsavel: uuid.UUID | None
    sla_dias: int | None
    estado: str  # ESTADOS_ETAPA
    checklist: list[dict[str, Any]] = field(default_factory=list)  # [{item, feito, por, em}]
    dependencias: list[str] = field(default_factory=list)  # nomes de etapas anteriores
    hike_ref: dict[str, Any] | None = None  # {card_id, importado_em, url_arquivada}


@dataclass
class HikeImportLog:
    """Linha da tabela auxiliar `hike_import_log` (§4.1 nota; migração 0002)."""

    id: uuid.UUID
    tenant_id: str
    os_id: uuid.UUID | None
    hike_card_id: str
    status: str  # ok|duplicado|erro
    detalhe: dict[str, Any]
    created_at: datetime
