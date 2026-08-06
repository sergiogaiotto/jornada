"""Entidades do contexto validação/War Room — espelham as tabelas auxiliares do M4
(§4.1, nota final; migração `0004_m4_validacao`): `validacao_campo`, `os_thread` e
`documento_portao` (docx gerados nos portões).

Sem tenant_id próprio (convenção das auxiliares por OS): o escopo vem da OS referenciada.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

VEREDITOS: tuple[str, ...] = ("ok", "falha")
TIPOS_CHECAGEM: tuple[str, ...] = ("contagem", "schema", "frescor")
STATUS_THREAD: tuple[str, ...] = ("aberta", "resolvida")
PORTOES: tuple[str, ...] = ("go",)  # demais portões (T9/T10) chegam com M8


@dataclass
class ValidacaoCampo:
    """Linha de `validacao_campo` — a decisão VIGENTE da checagem automática de um campo
    do briefing contra a fonte (§8-M4: contagem, schema, frescor).

    Emenda B01 (2026-08-06): a linha é única por (os_id, campo) — revalidar o mesmo campo
    ATUALIZA esta linha em vez de empilhar duplicatas (a UI hidrata dela após reload).
    O histórico de cada execução continua no outbox `domain_event` (validacao.executada,
    §2.3) — a tabela guarda o estado, o outbox guarda o filme.
    `created_at` = primeira checagem do campo · `atualizado_em`/`por` = a vigente (quando/quem).
    """

    id: uuid.UUID
    os_id: uuid.UUID
    campo: str
    veredito: str  # VEREDITOS
    checagens: list[dict[str, Any]]  # [{tipo, ok, detalhe}]
    evidencia: dict[str, Any]  # {fonte, contagem, schema, ultima_atualizacao, ...}
    created_at: datetime
    por: str | None = None  # actor da checagem vigente (email do usuário)
    atualizado_em: datetime | None = None  # None em linhas anteriores à emenda B01


@dataclass
class ThreadWarRoom:
    """Linha de `os_thread` — thread do War Room (T4) ANCORADA em campo do briefing."""

    id: uuid.UUID
    os_id: uuid.UUID
    campo: str  # âncora: campo existente no briefing da OS
    titulo: str | None
    mensagens: list[dict[str, Any]] = field(default_factory=list)  # [{autor, texto, em}]
    status: str = "aberta"  # STATUS_THREAD
    created_at: datetime | None = None


@dataclass
class DocumentoPortao:
    """Linha de `documento_portao` — .docx executivo gerado num portão (§8-M4-A3)."""

    id: uuid.UUID
    os_id: uuid.UUID
    portao: str  # PORTOES
    nome_arquivo: str
    conteudo: bytes  # bytea — o .docx em si
    hash: str  # sha256 hex do conteúdo
    created_at: datetime
