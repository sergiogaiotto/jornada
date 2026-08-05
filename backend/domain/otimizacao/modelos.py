"""Entidades do contexto otimização/retro/calibração (M11 · T15) — sem I/O.

- `PropostaOtimizacao` / `Aprendizado`: tabelas auxiliares (§4.1 nota final; migração
  `0009_m11_otimizacao` — emenda registrada no CHANGELOG-SDD.md). Proposta do agente
  optimize (§7.2: "proposta = diff JGC + impacto simulado"); PROPOR é a única ação
  autônoma — aplicar exige humano (§1.1.3) e o aprovar apenas gera NOVA versão do twin
  que reentra no mini-ciclo M8→M9 (nova aprovação expressa antes do apply).
- `CalibracaoPrior`: espelho 1:1 da tabela `calibracao_prior` §4.1 (DDL na 0001) —
  priors versionados do simulador (§6), publicados com backtest obrigatório (§8-M11).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ESTADOS_PROPOSTA: tuple[str, ...] = ("proposta", "aprovada", "rejeitada")

# Origem/status do aprendizado (T15): aprovação vira aprendizado ACEITO; rejeição vira
# SINAL (§8-M11: "motivo vira sinal" — alimenta o prompt do optimize na próxima rodada);
# apuração significativa vira PROMOVIDO (entra na base RAG `resultados` — A3).
ORIGENS_APRENDIZADO: tuple[str, ...] = ("proposta_aprovada", "proposta_rejeitada", "experimento")
STATUS_APRENDIZADO: tuple[str, ...] = ("aceito", "sinal", "promovido")

# Herdáveis no clone (A3: "clone herda aprendizados ACEITOS"): aceito e promovido
# (promovido ⊃ aceito); sinal é insumo do optimize da PRÓPRIA OS, não é herdado.
STATUS_HERDAVEIS: tuple[str, ...] = ("aceito", "promovido")


@dataclass
class PropostaOtimizacao:
    """Tabela auxiliar `proposta_otimizacao` (migração 0009) — proposta do optimize.

    `diff` = diff estrutural JGC (mesmo formato do M7 `ajustar`); `impacto` = P50s
    base×proposto + deltas + semáforo (pré-simulação §6 via SimuladorService);
    `esforco`/`risco`/`score` = ranking determinístico lift×esforço×risco (ranking.py).
    """

    id: uuid.UUID
    os_id: uuid.UUID
    jornada_base_id: uuid.UUID  # versão do twin sobre a qual a proposta foi feita
    titulo: str
    motivacao: str
    grafo_proposto: dict[str, Any]
    diff: dict[str, Any]
    impacto: dict[str, Any]
    esforco: int
    risco: float
    score: float
    estado: str = "proposta"  # ESTADOS_PROPOSTA
    motivo_rejeicao: str | None = None
    jornada_gerada_id: uuid.UUID | None = None  # nova versão criada no aprovar
    via_ai: bool = True  # proposta do agente optimize (§7.2)
    decidido_por: str | None = None
    decidido_em: datetime | None = None
    created_at: datetime | None = None


@dataclass
class Aprendizado:
    """Tabela auxiliar `aprendizado` (migração 0009) — memória da retro (T15).

    `herdado_de` = OS de origem quando o registro veio de um clone (A3).
    """

    id: uuid.UUID
    tenant_id: str
    os_id: uuid.UUID
    origem: str  # ORIGENS_APRENDIZADO
    status: str  # STATUS_APRENDIZADO
    texto: str
    meta: dict[str, Any] = field(default_factory=dict)
    herdado_de: uuid.UUID | None = None
    created_at: datetime | None = None


@dataclass
class CalibracaoPrior:
    """Tabela `calibracao_prior` §4.1 — priors versionados do simulador (§6).

    `versao` publicada começa em 2: a v1 é o `PRIORS_DEFAULT` em código
    (domain/simulacao/priors.py). `backtest` é OBRIGATÓRIO para publicar (§8-M11).
    """

    id: uuid.UUID
    tenant_id: str
    tipo_campanha: str | None
    versao: int
    priors: dict[str, Any]
    score: float | None = None
    backtest: dict[str, Any] | None = None
    publicada_em: datetime | None = None
