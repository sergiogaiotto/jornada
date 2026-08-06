"""Agente insight (roster §7.2: perfil 120b, T13/T14) — lado determinístico do
Pergunte aos Dados (§8-M10 parte 3).

Carrega o SKILL.md canônico (parser §7.1 compartilhado), monta as mensagens de chat
(catálogo da camada semântica + pergunta — NUNCA dados brutos nem PII §1.3.5) e
interpreta a saída do LLM com guarda-corpos de CÓDIGO:
- o LLM só COMPÕE: NL → consulta nomeada `vw_metricas_*` + parâmetros; qualquer
  saída fora do dicionário (SQL livre, view desconhecida, parâmetro fora da
  whitelist, JSON malformado) vira RECUSA PADRÃO — nada é executado (§7.2/A4);
- pré-guarda determinística de escopo: pergunta pedindo dado individual/PII (CPF,
  msisdn, telefone, "quem converteu"...) é recusada SEM sequer chamar o LLM —
  PII jamais entra em prompt (§1.3.5/§10.2) e zero consulta executa (A4);
- a detecção da pré-guarda usa `domain.privacidade.contem_pii` — a MESMA regra do
  sanitizador único (C02), para que detectar e mascarar nunca divirjam; o
  mascaramento em si é do serviço, na fronteira (prompt e ledger §10.2);
- `consulta_por_sinonimo` (A17 — UAT real): sinônimos de negócio ('conversão por
  real gasto', 'custo-benefício por canal', 'ROI'...) mapeiam para a métrica
  CANÔNICA antes de qualquer recusa — vocabulário livre não derruba pergunta
  legítima; o alvo é sempre consulta do dicionário (nunca SQL livre).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.consultor import Skill, carregar_skill
from domain.lancamento.semantica import CAMADA_SEMANTICA, VERSAO_CAMADA
from domain.lancamento.semantica import normalizar_parametros as semantica_normalizar
from domain.privacidade import contem_pii

SKILL_PATH = Path(__file__).resolve().parent / "skills" / "insight.skill.md"

RECUSA_PADRAO = (
    "Fora do escopo do Pergunte aos Dados: respondo apenas métricas agregadas da "
    "camada semântica (vw_metricas_*: roas, lift, custo_por_pedido, atingimento_meta) "
    "— nunca dados individuais/PII nem SQL livre (§7.2/§10.2)."
)

# Pergunta que pede dado INDIVIDUAL (PII §10.2) — recusa determinística SEM LLM (A4)
_PADROES_PII = tuple(
    re.compile(padrao, re.IGNORECASE)
    for padrao in (
        r"\bcpf\b",
        r"\brg\b",
        r"\bmsisdn\b",
        r"\btelefone\b",
        r"\bcelular\b",
        r"\bendere[çc]o\b",
        r"\bdados\s+pessoais\b",
        r"\be-?mail\s+d[oa]\b",  # "e-mail do cliente" (canal 'email' segue válido)
        r"\bquem\b",  # pergunta por indivíduo ("quem converteu...")
        r"\bqua(?:l|is)\s+(?:o\s+|a\s+)?cliente",
        r"\bnome\s+d[oa]\b",
        r"\bcontato_hash\b",
    )
)
# A17 (UAT real): sinônimos de negócio → métrica CANÔNICA da camada semântica.
# Mapa determinístico consultado ANTES de recusar (o LLM recebe a mesma regra via
# skill; o código garante que pergunta legítima com vocabulário livre não é recusada).
_SINONIMOS_CANONICOS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(padrao, re.IGNORECASE), consulta)
    for padrao, consulta in (
        (
            r"convers(?:[ãa]o|[õo]es)\s+por\s+rea(?:l|is)(?:\s+gasto)?",
            "vw_metricas_custo_por_pedido",
        ),
        (r"custo[\s-]*benef[íi]cio", "vw_metricas_custo_por_pedido"),
        (
            r"custo\s+(?:m[ée]dio\s+)?por\s+(?:convers[ãa]o|venda|pedido|aquisi[çc][ãa]o)",
            "vw_metricas_custo_por_pedido",
        ),
        (r"\bcpa\b|\bcac\b", "vw_metricas_custo_por_pedido"),
        (r"retorno\s+(?:sobre|do)\s+(?:o\s+)?investimento|\broi\b", "vw_metricas_roas"),
        (
            r"\bincremental(?:idade)?\b|efeito\s+da\s+campanha|(?:vs\.?|contra|versus)\s+"
            r"(?:o\s+)?holdout",
            "vw_metricas_lift",
        ),
        (
            r"(?:batemos|atingimos|alcan[çc]amos|cumprimos)\s+(?:a[s]?\s+)?metas?",
            "vw_metricas_atingimento_meta",
        ),
    )
)


def consulta_por_sinonimo(pergunta: str) -> str | None:
    """Mapa sinônimo→métrica canônica (A17): 'conversão por real gasto' e
    'custo-benefício por canal' são `custo_por_pedido` etc. None = sem mapeamento
    (aí sim a recusa padrão vale). Código puro — nunca inventa consulta fora do
    dicionário (todos os alvos existem em CAMADA_SEMANTICA)."""
    for padrao, consulta in _SINONIMOS_CANONICOS:
        if padrao.search(pergunta):
            return consulta
    return None


def carregar() -> Skill:
    """SKILL.md do insight (§7.1) — cacheado pelo parser compartilhado."""
    return carregar_skill(SKILL_PATH)


@dataclass(frozen=True)
class SaidaInsight:
    """Composição interpretada: consulta nomeada + parâmetros OU recusa (motivo em
    `recusa` — determinado por CÓDIGO, nunca pelo LLM)."""

    consulta: str | None
    parametros: dict[str, Any]
    resposta: str
    recusa: str | None


def motivo_fora_do_escopo(pergunta: str) -> str | None:
    """Pré-guarda determinística (A4): dado individual/PII na pergunta ⇒ motivo da
    recusa (o serviço NÃO chama o LLM nem executa nada); None = pergunta segue."""
    for padrao in _PADROES_PII:
        encontrado = padrao.search(pergunta)
        if encontrado:
            return (
                f"pergunta pede dado individual/PII ({encontrado.group(0).strip()!r}) — "
                "a camada semântica só expõe métricas agregadas (§10.2)."
            )
    if contem_pii(pergunta):  # C02: MESMA regra do sanitizador único (§10.2)
        return (
            "pergunta contém identificador pessoal (CPF/telefone/e-mail/cartão) — "
            "PII jamais entra em prompt ou consulta (§1.3.5/§10.2)."
        )
    return None


def montar_mensagens(skill: Skill, pergunta: str) -> list[dict[str, str]]:
    """Mensagens OpenAI-style: catálogo da camada semântica + pergunta — nenhum dado
    bruto, nenhuma PII (§1.3.5). O LLM escolhe consulta+parâmetros; código executa."""
    contexto = {
        "camada_semantica": {
            "versao": VERSAO_CAMADA,
            "consultas": [
                {
                    "nome": consulta.nome,
                    "metrica": consulta.metrica,
                    "descricao": consulta.descricao,
                    "parametros": consulta.parametros,
                }
                for consulta in CAMADA_SEMANTICA.values()
            ],
        },
        "pergunta": pergunta,
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


def interpretar_saida(texto: str) -> SaidaInsight:
    """Saída do LLM → SaidaInsight com guarda-corpos determinísticos (docstring):
    só consulta do dicionário passa; TODO desvio vira recusa padrão sem execução."""
    dados = _extrair_json(texto)
    if dados is None:  # JSON malformado: nada é executado, nada é inventado (§1.3.5)
        return SaidaInsight(
            consulta=None,
            parametros={},
            resposta=RECUSA_PADRAO,
            recusa="saída do agente fora do contrato JSON (§7.1) — nada foi executado.",
        )
    consulta = dados.get("consulta")
    if consulta is None:  # o próprio agente recusou — recusa PADRÃO (não o texto do LLM)
        return SaidaInsight(
            consulta=None,
            parametros={},
            resposta=RECUSA_PADRAO,
            recusa="agente classificou a pergunta como fora da camada semântica (§7.2).",
        )
    if not isinstance(consulta, str) or consulta not in CAMADA_SEMANTICA:
        return SaidaInsight(  # SQL livre/view desconhecida NUNCA executa (§7.2/A4)
            consulta=None,
            parametros={},
            resposta=RECUSA_PADRAO,
            recusa=(
                "composição fora da camada semântica (consulta não é uma vw_metricas_* "
                "do dicionário) — SQL livre nunca é executado (§7.2)."
            ),
        )
    brutos = dados.get("parametros")
    parametros = semantica_normalizar(
        CAMADA_SEMANTICA[consulta], dict(brutos) if isinstance(brutos, dict) else {}
    )
    if parametros is None:  # parâmetro fora da whitelist da consulta ⇒ recusa (§7.2)
        return SaidaInsight(
            consulta=None,
            parametros={},
            resposta=RECUSA_PADRAO,
            recusa=(
                f"parâmetros fora da whitelist da consulta {consulta} (§7.2) — nada foi executado."
            ),
        )
    resposta = str(dados.get("resposta") or "").strip()
    return SaidaInsight(consulta=consulta, parametros=parametros, resposta=resposta, recusa=None)
