"""Entidades do contexto Ateliê (M12) — espelham o DDL §4.1, sem I/O.

`agente`/`skill_versao`/`harness_case`/`harness_run` constam da migração 0001_core
(§4.1 — nenhuma migração nova nesta fatia). O ciclo de vida da skill é
draft→em_revisao→publicada; publicar EXIGE harness verde (§7.1: `harness_run.passou`
com score ≥ 90 POR DIMENSÃO do judge). Campanha congela versões no GO
(`os.frozen.agent_versions` §4.1) — publicar skill nova JAMAIS toca OS em voo (A2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

CAMADAS: tuple[str, ...] = ("maestro", "triagem", "especialista")  # §4.1 `agente.camada`
ESTADOS_SKILL: tuple[str, ...] = ("draft", "em_revisao", "publicada")  # §4.1 `skill_versao`

# Dimensões do judge (§7.3: correção/evidência/compliance/formato) — default do DDL §4.1.
DIMENSOES_PADRAO: tuple[str, ...] = ("correcao", "evidencia", "compliance", "formato")

# Portão de publicação (§7.1): score ≥ 90 POR DIMENSÃO do judge.
SCORE_MINIMO_PUBLICACAO: float = 90.0


@dataclass
class Agente:
    """Linha da tabela `agente` §4.1 (roster §7.2); guard → `deterministico=True`."""

    id: uuid.UUID
    tenant_id: str
    nome: str  # unique (§4.1): consultor|engineer|...|maestro|triagem_*
    camada: str | None  # CAMADAS
    etapa_workflow: str | None
    modelo_perfil: str | None  # 120b|20b (§3)
    deterministico: bool = False  # guard=True — NÃO invoca LLM (§7.2)


@dataclass
class SkillVersao:
    """Linha da tabela `skill_versao` §4.1 — unique(agente_id, versao).

    `execution_profile` guarda o front-matter executável parseado (§7.1:
    modelo_perfil/etapa/exige_evidencia/max_retries/saida); `harness_score` e
    `publicada_em` só existem após o portão do harness (§8-M12-A1).
    """

    id: uuid.UUID
    agente_id: uuid.UUID
    versao: str
    skill_md: str
    execution_profile: dict[str, Any] = field(default_factory=dict)
    bases_rag: list[str] = field(default_factory=list)
    estado: str = "draft"  # ESTADOS_SKILL
    harness_score: float | None = None
    publicada_em: datetime | None = None


@dataclass
class HarnessCase:
    """Linha da tabela `harness_case` §4.1 — golden dataset (3 casos por agente-chave,
    seeds §11.4). `dimensoes` default = DIMENSOES_PADRAO (mesmo default do DDL)."""

    id: uuid.UUID
    agente_id: uuid.UUID
    input: dict[str, Any]
    esperado: dict[str, Any]
    dimensoes: list[str] = field(default_factory=lambda: list(DIMENSOES_PADRAO))


@dataclass
class HarnessRun:
    """Linha da tabela `harness_run` §4.1 — resultado de uma rodada do harness.

    `resultados` = {casos:[{case_id, notas, saida}], score_por_dimensao,
    dimensoes_reprovadas, skill_md_hash} — o hash amarra o run ao CONTEÚDO julgado
    (editar o draft depois do run o torna obsoleto para publicar).
    """

    id: uuid.UUID
    skill_versao_id: uuid.UUID
    resultados: dict[str, Any]
    score: float | None
    passou: bool | None
    created_at: datetime | None = None
