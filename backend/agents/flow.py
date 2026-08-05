"""Agente flow (roster §7.2: perfil 120b, etapa T7) — lado determinístico.

Contrato de saída §7.2: "JGC válido + premissas[] + resumo". Guarda-corpos de CÓDIGO
(§1.3.5):
- JSON malformado ou sem objeto `grafo` → degrada para resposta textual SEM grafo
  (nada é inventado); o serviço traduz em `SaidaDoFlowInvalida` 422;
- `meta.osCodigo`/`meta.tenant` são SEMPRE reescritos pelo serviço com os valores da
  OS (o agente não escolhe escopo);
- a VALIDADE do JGC não vem do LLM: `jgc_validate` (§5.3) reprova a cada save.
PII: o prompt recebe briefing/instruções/grafo atual — jamais contatos (§1.3.5).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.consultor import Skill, carregar_skill

SKILL_PATH = Path(__file__).resolve().parent / "skills" / "flow.skill.md"


def carregar() -> Skill:
    """SKILL.md do flow (§7.1) — parser compartilhado (cacheado)."""
    return carregar_skill(SKILL_PATH)


@dataclass(frozen=True)
class SaidaFlow:
    """Contrato §7.2: JGC + premissas[] + resumo (resposta = texto quando não há grafo)."""

    grafo: dict[str, Any] | None
    premissas: tuple[str, ...]
    resumo: str
    resposta: str


def montar_mensagens(
    skill: Skill,
    briefing: dict[str, Any],
    instrucoes: str,
    *,
    quiet_hours: dict[str, Any] | None = None,
    grafo_atual: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Mensagens OpenAI-style. SEM PII: briefing (valores), política e grafo (§1.3.5)."""
    resumo_briefing = {
        campo: (entrada.get("valor") if isinstance(entrada, dict) else entrada)
        for campo, entrada in briefing.items()
    }
    contexto: dict[str, Any] = {
        "briefing": resumo_briefing,
        "instrucoes": instrucoes,
        "quiet_hours": quiet_hours,
    }
    if grafo_atual is not None:
        contexto["grafo_atual"] = grafo_atual  # modo ajuste (POST /jornadas/{id}/ajustar)
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


def interpretar_saida(texto: str) -> SaidaFlow:
    """Saída do LLM → SaidaFlow com guarda-corpos determinísticos (docstring)."""
    dados = _extrair_json(texto)
    if dados is None:  # JSON malformado: degrada sem grafo — nada é inventado
        return SaidaFlow(grafo=None, premissas=(), resumo="", resposta=texto.strip())
    grafo = dados.get("grafo")
    if not isinstance(grafo, dict) or not grafo:
        grafo = None
    premissas = tuple(
        str(p).strip()
        for p in (dados.get("premissas") if isinstance(dados.get("premissas"), list) else [])
        if str(p).strip()
    )
    return SaidaFlow(
        grafo=grafo,
        premissas=premissas,
        resumo=str(dados.get("resumo") or "").strip(),
        resposta=str(dados.get("resposta") or "").strip(),
    )
