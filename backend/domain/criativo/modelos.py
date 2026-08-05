"""Entidades do contexto criativo — espelham a tabela auxiliar `criativo` (SDD §4.1,
nota final: "matriz canal×variante, estado por célula, kv_master_ref"; colunas na
migração 0003). Sem I/O.

A matriz canal×variante nasce do KV master (T6): cada célula tem estado próprio;
`aprovado` SÓ por usuário analista+ (§8-M6-A3 — nunca por agente) e edição do KV
master marca as células derivadas `adaptado_revisar` (A2).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Canais da matriz (mesmos do volume de abordagem §4.1 `segmento.volume_abordagem`)
CANAIS_CRIATIVO: tuple[str, ...] = ("email", "sms", "push", "whatsapp")

VARIANTES_DEFAULT: tuple[str, ...] = ("A", "B")

# Estados por célula (§8-M6): `gerado` (prévia do agente — via_ai) · `aprovado` (SÓ
# usuário analista+ — A3) · `revisar` (devolvida pelo analista) · `adaptado_revisar`
# (KV master editado após a geração — A2).
ESTADOS_CELULA: tuple[str, ...] = ("gerado", "aprovado", "revisar", "adaptado_revisar")


@dataclass
class CelulaCriativo:
    """Célula da matriz canal×variante — vira item do jsonb `celulas` (migração 0003)."""

    canal: str  # CANAIS_CRIATIVO
    variante: str  # ex.: A, B
    conteudo: dict[str, Any]  # por canal: {assunto?, titulo?, mensagem, cta?, template?}
    estado: str = "gerado"  # ESTADOS_CELULA
    aprovada_por: uuid.UUID | None = None  # A3: sempre um usuário humano analista+
    aprovada_em: datetime | None = None
    observacao: str | None = None  # motivo de `revisar` / nota do analista


@dataclass
class Criativo:
    """Tabela auxiliar `criativo` (§4.1 nota; migração 0003) — matriz da OS.

    Sem tenant_id próprio: o escopo vem da OS referenciada (mesmo padrão de `segmento`).
    """

    id: uuid.UUID
    os_id: uuid.UUID
    kv_master: dict[str, Any]  # conceito-chave (KV) que deriva todas as células
    kv_master_ref: str | None = None  # referência do asset do KV (quando houver)
    celulas: list[CelulaCriativo] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
