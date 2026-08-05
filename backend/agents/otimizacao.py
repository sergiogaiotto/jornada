"""Agente optimize (roster §7.2: perfil 120b, etapa T15) — lado determinístico.

Contrato de saída §7.2: "proposta = diff JGC + impacto simulado". O LLM só PROPÕE
grafos candidatos; TODO o resto é código (§1.3.5/§10.6): validação §5.3, diff,
pré-simulação (SimuladorService §6) e ranking lift×esforço×risco (ranking.py).
PROPOR é a única ação autônoma (§8-M11) — aplicar exige humano (aprovar/rejeitar).

Guarda-corpos de CÓDIGO:
- JSON malformado ou sem lista `propostas` → degrada para resposta textual SEM
  propostas (nada é inventado); o serviço traduz em `SaidaDoOptimizeInvalida` 422;
- item sem `grafo` dict ou sem `titulo` é DESCARTADO;
- `meta.osCodigo`/`meta.tenant` são SEMPRE reescritos pelo serviço (escopo nunca vem
  do LLM); grafo proposto passa por `jgc_validate` (§5.3) antes de persistir.
PII: o prompt recebe grafo/P50s/sinais de rejeição — jamais contatos (§1.3.5).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.consultor import Skill, carregar_skill

SKILL_PATH = Path(__file__).resolve().parent / "skills" / "optimize.skill.md"

MAX_PROPOSTAS = 3  # teto por rodada (o ranking §8-M11 ordena o que passar)


def carregar() -> Skill:
    """SKILL.md do optimize (§7.1) — parser compartilhado (cacheado)."""
    return carregar_skill(SKILL_PATH)


@dataclass(frozen=True)
class PropostaBruta:
    """Proposta como veio do LLM — ANTES dos guarda-corpos do serviço."""

    titulo: str
    motivacao: str
    grafo: dict[str, Any]


@dataclass(frozen=True)
class SaidaOptimize:
    propostas: tuple[PropostaBruta, ...]
    resumo: str
    resposta: str


def montar_mensagens(
    skill: Skill,
    *,
    grafo_atual: dict[str, Any],
    p50_atual: dict[str, Any],
    sinais: list[str],
    quiet_hours: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Mensagens OpenAI-style. SEM PII (§1.3.5): grafo, P50s agregados e sinais
    (motivos de rejeição anteriores — §8-M11: "motivo vira sinal")."""
    contexto: dict[str, Any] = {
        "grafo_atual": grafo_atual,
        "p50_simulacao_atual": p50_atual,
        "sinais_de_rejeicao": sinais,
        "quiet_hours": quiet_hours,
        "max_propostas": MAX_PROPOSTAS,
    }
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


def interpretar_saida(texto: str) -> SaidaOptimize:
    """Saída do LLM → SaidaOptimize com guarda-corpos determinísticos (docstring)."""
    dados = _extrair_json(texto)
    if dados is None:  # JSON malformado: degrada sem propostas — nada é inventado
        return SaidaOptimize(propostas=(), resumo="", resposta=texto.strip())
    brutas: list[PropostaBruta] = []
    itens = dados.get("propostas")
    for item in itens if isinstance(itens, list) else []:
        if not isinstance(item, dict):
            continue
        grafo = item.get("grafo")
        titulo = str(item.get("titulo") or "").strip()
        if not isinstance(grafo, dict) or not grafo or not titulo:
            continue  # item sem grafo/título é descartado (nada é inventado)
        brutas.append(
            PropostaBruta(
                titulo=titulo,
                motivacao=str(item.get("motivacao") or "").strip(),
                grafo=grafo,
            )
        )
        if len(brutas) >= MAX_PROPOSTAS:
            break
    return SaidaOptimize(
        propostas=tuple(brutas),
        resumo=str(dados.get("resumo") or "").strip(),
        resposta=str(dados.get("resposta") or "").strip(),
    )
