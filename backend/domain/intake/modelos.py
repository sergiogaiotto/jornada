"""Entidades do contexto intake — espelham 1:1 a tabela `pedido` do SDD §4.1 (sem I/O).

`pedido` é o intake do Consultor (T2/portal). `conteudo` é jsonb com uma entrada por
campo do briefing: `{campo: {valor, inferido, evidencias?}}` — `inferido:true` quando o
valor veio do consultor (LLM) e ainda não foi confirmado por humano (§8-M3).
`completude`/`faltantes` são SEMPRE derivados por código determinístico (completude.py);
LLM só conversa/infere (§8-M3, §1.1.3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Campos obrigatórios do briefing para completude (§8-M3: "sem verba/janela →
# completude<100 e faltantes lista exatamente esses campos"). Ordem canônica = ordem
# em que `faltantes` é reportado.
CAMPOS_OBRIGATORIOS: tuple[str, ...] = ("objetivo", "publico", "oferta", "verba", "janela")

ESTADOS_PEDIDO: tuple[str, ...] = ("rascunho", "completo", "convertido", "arquivado")


@dataclass
class Pedido:
    """Tabela `pedido` §4.1 — intake do Consultor (T2/portal).

    `created_at/updated_at` seguem a convenção geral do §4 (toda tabela de negócio).
    """

    id: uuid.UUID
    tenant_id: str
    solicitante: dict[str, Any]  # jsonb not null — nunca vai em prompt de LLM (§1.3.5)
    conteudo: dict[str, Any]  # {campo: {valor, inferido, evidencias?}}
    completude: float  # numeric(4,1) — derivada (completude.py)
    faltantes: list[str] = field(default_factory=list)  # text[] — derivada
    estado: str = "rascunho"  # ESTADOS_PEDIDO
    os_id: uuid.UUID | None = None  # preenchido na conversão (§8-M3)
    created_at: datetime | None = None
    updated_at: datetime | None = None
