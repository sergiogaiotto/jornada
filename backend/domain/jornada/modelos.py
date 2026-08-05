"""Entidades do contexto jornada — espelham 1:1 o DDL do SDD §4.1 (sem I/O).

`jornada_versao` é o TWIN (§1.1.1): versões do grafo canônico (JGC §5), snapshot
imutável por hash sha256 do JGC canonicalizado (RFC 8785 — canonico.py).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ESTADOS_JORNADA: tuple[str, ...] = ("rascunho", "simulado", "aprovado", "publicado", "arquivado")

# §4.1 `sync_run` — compilador plan/apply (M9)
AMBIENTES_SYNC: tuple[str, ...] = ("homolog", "prod")
FASES_SYNC: tuple[str, ...] = ("plan", "apply")
ESTADOS_SYNC: tuple[str, ...] = ("pendente", "ok", "parcial", "revertido", "falhou")
ACOES_PLANO: tuple[str, ...] = ("criar", "alterar", "manter", "destruir")

# §5.1 `meta.reentrada` — contrato de re-entrada (A3)
REENTRADAS: tuple[str, ...] = ("nao", "apos_saida", "qualquer_momento")

# §4.1 `drift_check` — monitor de drift (M9 fatia 2, §5.4.5)
ESTADOS_DRIFT: tuple[str, ...] = ("em_sincronia", "drift_sfmc", "twin_a_frente")
RESOLUCOES_DRIFT: tuple[str, ...] = ("adopt", "enforce", "excecao")

# `preflight_run` (tabela auxiliar §4.1 nota final — migração 0007, M9 fatia 2)
RESULTADOS_PREVOO: tuple[str, ...] = ("verde", "amarelo", "vermelho")
STATUS_ITEM_PREVOO: tuple[str, ...] = ("pass", "warn", "fail")

# Estados em que o grafo ainda pode ser editado (PUT /jornadas/{id}/grafo);
# editar um `simulado` invalida a simulação → volta a `rascunho` (§1.1.2: o
# Previsto congelado pertence ao snapshot, não à versão em edição).
ESTADOS_EDITAVEIS: tuple[str, ...] = ("rascunho", "simulado")


@dataclass
class JornadaVersao:
    """Tabela `jornada_versao` §4.1 — o twin: versões do grafo canônico.

    Sem tenant_id próprio (DDL §4.1): o escopo vem da OS referenciada.
    """

    id: uuid.UUID
    os_id: uuid.UUID
    versao: int
    grafo: dict[str, Any]  # JGC (§5), validado por JSON Schema + §5.3
    hash: str  # sha256 do JGC canonicalizado (RFC 8785 — canonico.py)
    estado: str = "rascunho"  # ESTADOS_JORNADA
    premissas: list[str] = field(default_factory=list)
    custo_projetado: float | None = None  # numeric(12,2) — taxímetro (taximetro.py)
    # M8 (migração 0005 — emenda §4.1): saída do Ensaio Geral (§6) e Previsto congelado
    simulacao: dict[str, Any] | None = None  # funil, P10/P50/P90, poder, semáforo (§6)
    previsto: dict[str, Any] | None = None  # régua do pós-disparo (§1.1.2)


@dataclass
class SyncRun:
    """Tabela `sync_run` §4.1 — compilador plan/apply (M9, §5.4).

    `plano` = lista `{recurso, acao: criar|alterar|manter|destruir, aviso?}` (§5.4.1);
    `resultado` = execução por recurso + contagem de mutações; `api_calls` = chamadas
    SFMC consumidas (orçamento `SFMC_API_BUDGET_PER_APPLY` — §5.4.2).
    Sem tenant_id próprio (DDL §4.1): o escopo vem do snapshot → OS.
    """

    id: uuid.UUID
    snapshot_id: uuid.UUID
    ambiente: str  # AMBIENTES_SYNC
    fase: str  # FASES_SYNC
    plano: list[dict[str, Any]] | None = None
    resultado: dict[str, Any] | None = None
    estado: str = "pendente"  # ESTADOS_SYNC
    api_calls: int = 0
    created_at: datetime | None = None


@dataclass
class DriftCheck:
    """Tabela `drift_check` §4.1 — monitor twin ↔ SFMC (§5.4.5, M9 fatia 2).

    `diff` (jsonb) carrega evidência: {ambiente, hash_twin, hash_sfmc, campos:
    {campo: {twin, sfmc}}} e, após resolução, `resolucao_meta` = {por, em,
    justificativa?, prazo_ate?} (excecao EXIGE prazo — §8-M9).
    Sem tenant_id próprio (DDL §4.1): o escopo vem do snapshot → OS.
    """

    id: uuid.UUID
    snapshot_id: uuid.UUID
    recurso: str  # external_key do recurso verificado (resource_registry §4.1)
    estado: str  # ESTADOS_DRIFT
    diff: dict[str, Any] = field(default_factory=dict)
    resolucao: str | None = None  # RESOLUCOES_DRIFT (None = pendente de decisão)
    checked_at: datetime | None = None


@dataclass
class PreflightRun:
    """Tabela auxiliar `preflight_run` (§4.1 nota final; migração 0007) — pré-voo T11.

    `itens` = bateria §8-M9 com evidência: [{item, status pass|warn|fail, evidencia}];
    `resultado` = semáforo agregado (fail⇒vermelho, warn⇒amarelo). Fail bloqueia apply;
    apply em prod exige pré-voo executado e não-vermelho (§5.4.4).
    """

    id: uuid.UUID
    snapshot_id: uuid.UUID
    ambiente: str  # AMBIENTES_SYNC
    resultado: str  # RESULTADOS_PREVOO
    itens: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime | None = None


@dataclass
class ResourceRegistry:
    """Tabela `resource_registry` §4.1 — vínculo twin ↔ SFMC por externalKey.

    `unique(tenant_id, ambiente, external_key)` — idempotência do apply (§5.4.1);
    `snapshot_hash` = hash do snapshot que materializou o recurso.
    """

    id: uuid.UUID
    tenant_id: str
    no_jgc: str
    tipo_sfmc: str  # dataExtension|eventDefinition|journey|asset|automation (§4.1)
    external_key: str
    sfmc_id: str | None = None
    ambiente: str | None = None
    snapshot_hash: str | None = None
