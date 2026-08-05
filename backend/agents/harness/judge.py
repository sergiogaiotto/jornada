"""Judge do harness (M12 · §7.1/§7.3) — lado determinístico do LLM juiz.

Judge = 120B com RUBRICA FIXA (§7.1), dimensões correção/evidência/compliance/formato
(§7.3; `harness_case.dimensoes` pode restringir). Em teste, o LLMPort é SEMPRE o
LLMFake determinístico (§1.3.5) — o hub real jamais é chamado.

Guarda-corpos de CÓDIGO (a decisão de portão NUNCA é texto livre do LLM):
- resposta sem JSON ou sem `notas` → TODAS as notas 0 (reprova; nada é inventado);
- nota fora de 0–100 é clampada; dimensão ausente vale 0 (domain/atelie/harness.py);
- o veredito final (passou/score) é consolidado por CÓDIGO, não pelo judge.
"""

from __future__ import annotations

import json
from typing import Any, Final

PERFIL_JUDGE: Final = "120b"  # §3: 120B = judge do harness (Final ⇒ Literal p/ LLMPort.chat)

RUBRICA = """Você é o JUDGE do harness de skills da plataforma Jornada (rubrica fixa).
Avalie a SAÍDA do agente para a ENTRADA dada, contra o ESPERADO do golden case.
Atribua uma nota de 0 a 100 para CADA dimensão pedida:
- correcao: a saída atende à intenção e bate com o esperado no conteúdo;
- evidencia: afirmações citam evidência/fonte quando exigido; nada inventado;
- compliance: respeita as regras do SKILL.md (listas de exclusão, PII, limites);
- formato: respeita o contrato de saída (JSON/schema/campos) do SKILL.md.
Responda EXCLUSIVAMENTE com JSON:
{"notas": {"<dimensao>": <0-100>, ...}, "justificativa": "<1 frase por dimensão>"}"""


def montar_mensagens_execucao(skill_corpo: str, entrada: dict[str, Any]) -> list[dict[str, str]]:
    """Executa a skill candidata sobre o input do golden case (SEM PII — os casos são
    sintéticos, seeds §11.4)."""
    return [
        {"role": "system", "content": skill_corpo},
        {"role": "user", "content": json.dumps(entrada, ensure_ascii=False)},
    ]


def montar_mensagens_judge(
    *,
    entrada: dict[str, Any],
    esperado: dict[str, Any],
    saida: str,
    dimensoes: list[str],
) -> list[dict[str, str]]:
    contexto = {
        "entrada": entrada,
        "esperado": esperado,
        "saida_do_agente": saida,
        "dimensoes": dimensoes,
    }
    return [
        {"role": "system", "content": RUBRICA},
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


def interpretar_notas(texto: str, dimensoes: list[str]) -> dict[str, float]:
    """Saída do judge → {dimensao: nota 0-100}. Malformada/sem `notas` → tudo 0
    (reprova conservadoramente — a consolidação é de domain/atelie/harness.py)."""
    dados = _extrair_json(texto)
    notas_brutas = (dados or {}).get("notas")
    if not isinstance(notas_brutas, dict):
        return dict.fromkeys(dimensoes, 0.0)
    resultado: dict[str, float] = {}
    for dimensao in dimensoes:
        valor = notas_brutas.get(dimensao)
        if isinstance(valor, bool) or not isinstance(valor, int | float):
            resultado[dimensao] = 0.0
        else:
            resultado[dimensao] = max(0.0, min(100.0, float(valor)))
    return resultado
