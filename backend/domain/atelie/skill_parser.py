"""Parser do SKILL.md canônico (§7.1) — front-matter YAML simples + corpo; sem I/O.

Este é o parser PLENO prometido no M3 (agents/consultor.py delega para cá): valida
CAMPOS, não só a forma. Obrigatórios: `name` (minúsculo, [a-z0-9_]), `version`
(numérica pontuada, ex. 3.2), `camada` (§4.1: maestro|triagem|especialista),
`modelo_perfil` (§3: 120b|20b) e corpo não-vazio. Opcionais validados: `bases_rag`
(lista dentro do conjunto fechado do §4.1 `agente_evidence.base`), `exige_evidencia`
(true|false), `max_retries` (inteiro ≥ 0), `saida` ({formato, schema?}). Qualquer
violação → `SkillMdInvalido` com TODOS os erros acumulados (422 na API).

Forma aceita (exemplo do §7.1): mais de um `chave: valor` por linha, separados por
2+ espaços; listas `[a, b]` e dicts `{k: v, ...}` inline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from domain.atelie.erros import SkillMdInvalido
from domain.atelie.modelos import CAMADAS

# Conjunto fechado §4.1 (`agente_evidence.base`) — bases RAG autorizáveis a uma skill.
BASES_RAG_VALIDAS: tuple[str, ...] = (
    "dicionario_dados",
    "criativos",
    "governanca",
    "inventario_jornadas",
    "resultados",
    "historico_campanhas",
    "ofertas",
    "tarifario",
)

PERFIS_VALIDOS: tuple[str, ...] = ("120b", "20b")  # §3

_SEGMENTOS = re.compile(r"\s{2,}")  # §7.1 admite mais de um `chave: valor` por linha
_NOME_VALIDO = re.compile(r"^[a-z][a-z0-9_]*$")  # roster §7.2 (inclui triagem_*)
_VERSAO_VALIDA = re.compile(r"^\d+(\.\d+)*$")  # ex. 1.0, 3.2


@dataclass(frozen=True)
class SkillMd:
    """SKILL.md canônico parseado e VALIDADO (§7.1)."""

    nome: str
    versao: str
    camada: str
    modelo_perfil: str
    etapa: str
    bases_rag: tuple[str, ...]
    exige_evidencia: bool
    max_retries: int
    saida: dict[str, str]
    corpo: str
    meta: dict[str, str] = field(default_factory=dict)  # front-matter cru

    def execution_profile(self) -> dict[str, Any]:
        """Front-matter executável → `skill_versao.execution_profile` (jsonb §4.1)."""
        return {
            "modelo_perfil": self.modelo_perfil,
            "etapa": self.etapa,
            "exige_evidencia": self.exige_evidencia,
            "max_retries": self.max_retries,
            "saida": self.saida,
        }


def _parse_front_matter(bloco: str) -> dict[str, str]:
    chaves: dict[str, str] = {}
    for linha in bloco.splitlines():
        for segmento in _SEGMENTOS.split(linha.strip()):
            if ":" in segmento:
                chave, _, valor = segmento.partition(":")
                if chave.strip():
                    chaves[chave.strip()] = valor.strip()
    return chaves


def _parse_lista(valor: str) -> list[str]:
    """`[a, b]` → ["a", "b"]; valor simples vira lista de um item."""
    interno = valor.strip()
    if interno.startswith("[") and interno.endswith("]"):
        interno = interno[1:-1]
    return [item.strip() for item in interno.split(",") if item.strip()]


def _parse_dict(valor: str) -> dict[str, str] | None:
    """`{formato: json, schema: x.schema.json}` → dict; malformado → None."""
    interno = valor.strip()
    if not (interno.startswith("{") and interno.endswith("}")):
        return None
    saida: dict[str, str] = {}
    for par in interno[1:-1].split(","):
        chave, sep, item = par.partition(":")
        if not sep or not chave.strip():
            return None
        saida[chave.strip()] = item.strip()
    return saida


def parse_skill_md(texto: str) -> SkillMd:
    """Valida o SKILL.md canônico (§7.1); erros ACUMULADOS em `SkillMdInvalido`."""
    partes = texto.split("---", 2)
    if len(partes) < 3 or partes[0].strip():
        raise SkillMdInvalido(
            "SKILL.md sem front-matter delimitado por '---' no início (§7.1).",
            erros=["front-matter ausente ou fora do início do arquivo"],
        )
    meta = _parse_front_matter(partes[1])
    corpo = partes[2].strip()
    erros: list[str] = []

    nome = meta.get("name", "")
    if not _NOME_VALIDO.match(nome):
        erros.append(f"name obrigatório em minúsculas [a-z0-9_] (roster §7.2): {nome!r}")
    versao = meta.get("version", "")
    if not _VERSAO_VALIDA.match(versao):
        erros.append(f"version obrigatória no formato numérico pontuado (§7.1): {versao!r}")
    camada = meta.get("camada", "")
    if camada not in CAMADAS:
        erros.append(f"camada deve ser uma de {list(CAMADAS)} (§4.1): {camada!r}")
    perfil = meta.get("modelo_perfil", "")
    if perfil not in PERFIS_VALIDOS:
        erros.append(f"modelo_perfil deve ser um de {list(PERFIS_VALIDOS)} (§3): {perfil!r}")

    bases = _parse_lista(meta["bases_rag"]) if "bases_rag" in meta else []
    for base in bases:
        if base not in BASES_RAG_VALIDAS:
            erros.append(f"bases_rag fora do conjunto fechado §4.1: {base!r}")

    exige = meta.get("exige_evidencia", "false").lower()
    if exige not in ("true", "false"):
        erros.append(f"exige_evidencia deve ser true|false (§7.1): {meta['exige_evidencia']!r}")

    retries_cru = meta.get("max_retries", "2")  # default do subgrafo §7.3 (retry ≤ 2)
    max_retries = -1
    if retries_cru.isdigit():
        max_retries = int(retries_cru)
    else:
        erros.append(f"max_retries deve ser inteiro ≥ 0 (§7.1): {retries_cru!r}")

    saida: dict[str, str] = {}
    if "saida" in meta:
        parseada = _parse_dict(meta["saida"])
        if parseada is None or "formato" not in parseada:
            erros.append(f"saida deve ser dict inline com `formato` (§7.1): {meta['saida']!r}")
        else:
            saida = parseada

    if not corpo:
        erros.append("corpo (prompt de sistema) vazio após o front-matter (§7.1)")

    if erros:
        raise SkillMdInvalido(
            f"SKILL.md fora do canônico §7.1 — {len(erros)} erro(s) de validação.", erros=erros
        )
    return SkillMd(
        nome=nome,
        versao=versao,
        camada=camada,
        modelo_perfil=perfil,
        etapa=meta.get("etapa", ""),
        bases_rag=tuple(bases),
        exige_evidencia=exige == "true",
        max_retries=max_retries,
        saida=saida,
        corpo=corpo,
        meta=meta,
    )
