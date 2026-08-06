"""Agente engineer (roster §7.2: perfil 120b, etapa audiencia/T5) — lado determinístico.

Carrega o SKILL.md canônico (parser §7.1 compartilhado com o consultor), monta as
mensagens de chat e interpreta a saída do LLM com guarda-corpos de CÓDIGO (§1.3.5):
- SQL sem evidências com `exige_evidencia: true` é DESCARTADO (contrato §7.2:
  "SQL + explicação por cláusula + evidências"; sem evidência → não sabe);
- JSON malformado degrada para resposta textual SEM SQL (nada é inventado);
- cercas de código (```sql) são removidas do SQL de forma determinística.
O veredito de compliance NÃO é deste agente: o Guard determinístico
(agents/guard/elegibilidade.py) revalida as 7 listas na certificação.
PII: o prompt recebe briefing/instruções — jamais contatos ou o bloco `solicitante`.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agents.consultor import Skill, carregar_skill
from domain.audiencia.modelos import SETE_LISTAS

SKILL_PATH = Path(__file__).resolve().parent / "skills" / "engineer.skill.md"

_CERCA_CODIGO = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


def carregar() -> Skill:
    """SKILL.md do engineer (§7.1) — cacheado pelo parser compartilhado."""
    return carregar_skill(SKILL_PATH)


@dataclass(frozen=True)
class SaidaEngineer:
    """Contrato de saída do roster §7.2: SQL + explicação por cláusula + evidências."""

    sql: str | None
    explicacao: tuple[dict[str, str], ...]
    evidencias: tuple[str, ...]
    resposta: str  # texto do agente quando não há SQL (ou resumo)


def montar_mensagens(
    skill: Skill,
    briefing: dict[str, Any],
    instrucoes: str,
    evidencias_rag: Sequence[dict[str, str]] = (),
) -> list[dict[str, str]]:
    """Mensagens OpenAI-style. SEM PII: só valores do briefing + instruções (§1.3.5).

    `evidencias_rag` (A11 — §7.4): top-k do retriever nas bases da skill
    (dicionario_dados/historico_campanhas) no formato citável que a skill já espera
    ("Cite a evidência RAG de cada coluna usada"). Vazio → chave fora do contexto
    (prompt idêntico ao pré-A11; com exige_evidencia a skill responde que não sabe)."""
    resumo = {
        campo: (entrada.get("valor") if isinstance(entrada, dict) else entrada)
        for campo, entrada in briefing.items()
    }
    contexto: dict[str, Any] = {
        "briefing": resumo,
        "instrucoes": instrucoes,
        "listas_obrigatorias_no_where": list(SETE_LISTAS),
    }
    if evidencias_rag:
        contexto["evidencias_rag"] = list(evidencias_rag)
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


def interpretar_saida(texto: str, *, exige_evidencia: bool = True) -> SaidaEngineer:
    """Saída do LLM → SaidaEngineer com guarda-corpos determinísticos (docstring)."""
    dados = _extrair_json(texto)
    if dados is None:  # JSON malformado: degrada sem SQL — nada é inventado
        return SaidaEngineer(sql=None, explicacao=(), evidencias=(), resposta=texto.strip())

    sql_bruto = dados.get("sql")
    sql = _CERCA_CODIGO.sub("", sql_bruto).strip() if isinstance(sql_bruto, str) else None
    sql = sql or None

    cruas = dados.get("evidencias")
    evidencias = tuple(
        str(e).strip() for e in (cruas if isinstance(cruas, list) else []) if str(e).strip()
    )
    if exige_evidencia and sql is not None and not evidencias:
        sql = None  # contrato §7.2/§7.1: sem evidência → não sabe (SQL descartado)

    explicacao_bruta = dados.get("explicacao")
    explicacao = tuple(
        {"clausula": str(item.get("clausula", "")), "explicacao": str(item.get("explicacao", ""))}
        for item in (explicacao_bruta if isinstance(explicacao_bruta, list) else [])
        if isinstance(item, dict)
    )
    resposta = str(dados.get("resposta") or "").strip()
    return SaidaEngineer(sql=sql, explicacao=explicacao, evidencias=evidencias, resposta=resposta)
