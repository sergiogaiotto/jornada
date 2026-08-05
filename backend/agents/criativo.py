"""Agentes do T6 — visual/copy/content (roster §7.2: perfil 120b, etapa criativos) —
lado determinístico.

Pipeline do §8-M6 (`POST /os/{id}/criativos/gerar`): visual (diretrizes por canal) →
copy (textos por canal×variante) → content (matriz final). Cada agente tem seu
SKILL.md canônico (§7.1, parser compartilhado do consultor); só a saída do CONTENT
vira matriz — interpretada aqui com guarda-corpos de CÓDIGO (§1.3.5):
- JSON malformado ou sem células → SEM matriz (nada é inventado);
- células fora dos canais×variantes pedidos são DESCARTADAS;
- estado NUNCA vem do LLM: toda célula nasce `gerado` (aprovação é humana — A3).
O veredito de compliance NÃO é destes agentes: os validadores determinísticos
(domain/criativo/validadores.py) reprovam SMS>160/template/termos (regras); o LLM 20b
só ACRESCENTA warnings não bloqueantes (`compliance warn` — "regras + warn LLM").
PII: prompts recebem KV master/briefing/instruções — jamais contatos (§1.3.5/§10.2).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.consultor import Skill, carregar_skill
from domain.criativo.modelos import CANAIS_CRIATIVO

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"

AGENTES_T6: tuple[str, ...] = ("visual", "copy", "content")  # ordem do pipeline


def carregar(nome: str) -> Skill:
    """SKILL.md de um agente do T6 (§7.1) — cacheado pelo parser compartilhado."""
    if nome not in AGENTES_T6:
        raise ValueError(f"Agente fora do roster T6 (§7.2): {nome!r}")
    return carregar_skill(_SKILLS_DIR / f"{nome}.skill.md")


@dataclass(frozen=True)
class CelulaProposta:
    """Célula proposta pelo content — SEM estado (estado nunca vem do LLM)."""

    canal: str
    variante: str
    conteudo: dict[str, Any]


@dataclass(frozen=True)
class SaidaCriativo:
    """Contrato de saída do roster §7.2: matriz canal×variante (+ evidências)."""

    celulas: tuple[CelulaProposta, ...]
    evidencias: tuple[str, ...]
    resposta: str


def montar_mensagens(
    skill: Skill,
    *,
    kv_master: dict[str, Any],
    canais: list[str],
    variantes: list[str],
    briefing: dict[str, Any],
    instrucoes: str | None,
    contexto_anterior: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    """Mensagens OpenAI-style para qualquer agente do pipeline. SEM PII (§1.3.5):
    só KV master + valores do briefing + instruções (+ saídas dos agentes anteriores)."""
    resumo_briefing = {
        campo: (entrada.get("valor") if isinstance(entrada, dict) else entrada)
        for campo, entrada in briefing.items()
    }
    contexto: dict[str, Any] = {
        "kv_master": kv_master,
        "canais": canais,
        "variantes": variantes,
        "briefing": resumo_briefing,
        "instrucoes": instrucoes or "",
    }
    if contexto_anterior:
        contexto["saidas_anteriores"] = contexto_anterior
    return [
        {"role": "system", "content": skill.corpo},
        {"role": "user", "content": json.dumps(contexto, ensure_ascii=False)},
    ]


def _extrair_json(texto: str) -> dict[str, Any] | None:
    try:
        dados = json.loads(texto)
        return dados if isinstance(dados, dict) else None
    except ValueError:
        inicio, fim = texto.find("{"), texto.rfind("}")
        if 0 <= inicio < fim:
            try:
                dados = json.loads(texto[inicio : fim + 1])
                return dados if isinstance(dados, dict) else None
            except ValueError:
                return None
    return None


def interpretar_matriz(texto: str, *, canais: list[str], variantes: list[str]) -> SaidaCriativo:
    """Saída do CONTENT → SaidaCriativo com guarda-corpos determinísticos (docstring).

    Só canais×variantes pedidos entram; duplicata mantém a primeira; conteúdo precisa
    ser objeto. JSON malformado → sem células (a service traduz para 422).
    """
    dados = _extrair_json(texto)
    if dados is None:
        return SaidaCriativo(celulas=(), evidencias=(), resposta=texto.strip())

    validos = [c for c in canais if c in CANAIS_CRIATIVO]
    vistas: set[tuple[str, str]] = set()
    celulas: list[CelulaProposta] = []
    brutas = dados.get("celulas")
    for bruta in brutas if isinstance(brutas, list) else []:
        if not isinstance(bruta, dict):
            continue
        canal, variante = bruta.get("canal"), bruta.get("variante")
        conteudo = bruta.get("conteudo")
        if canal not in validos or variante not in variantes:
            continue  # nunca célula fora do pedido (§1.3.5)
        if not isinstance(conteudo, dict) or (canal, variante) in vistas:
            continue
        vistas.add((canal, variante))
        celulas.append(CelulaProposta(canal=canal, variante=variante, conteudo=dict(conteudo)))

    cruas = dados.get("evidencias")
    evidencias = tuple(
        str(e).strip() for e in (cruas if isinstance(cruas, list) else []) if str(e).strip()
    )
    resposta = str(dados.get("resposta") or "").strip()
    return SaidaCriativo(celulas=tuple(celulas), evidencias=evidencias, resposta=resposta)


# ------------------------------------------------ Compliance warn (LLM 20b — §8-M6)
_SISTEMA_COMPLIANCE = (
    "Você revisa LINGUAGEM de criativos de marketing (pt-BR) da plataforma Jornada. "
    "Aponte avisos NÃO bloqueantes: tom enganoso, promessa vaga, urgência artificial, "
    "juridiquês. As regras duras (SMS>160, template, termos proibidos) já foram "
    "checadas por código determinístico — não as repita. "
    'Responda EXCLUSIVAMENTE com JSON: {"avisos": ["<aviso curto>"]} '
    '(sem avisos, {"avisos": []}).'
)


def montar_mensagens_compliance(textos: list[str]) -> list[dict[str, str]]:
    """Prompt do warn de linguagem (perfil 20b — §3: classificação leve). SEM PII."""
    return [
        {"role": "system", "content": _SISTEMA_COMPLIANCE},
        {"role": "user", "content": json.dumps({"textos": textos}, ensure_ascii=False)},
    ]


def interpretar_avisos(texto: str) -> list[str]:
    """Saída do warn → lista de avisos; malformada → [] (warn NUNCA bloqueia)."""
    dados = _extrair_json(texto)
    if dados is None:
        return []
    brutos = dados.get("avisos")
    return [str(a).strip() for a in (brutos if isinstance(brutos, list) else []) if str(a).strip()]
