"""Validadores DETERMINÍSTICOS do criativo (§8-M6) — CÓDIGO PURO, ZERO LLM.

Compliance é código determinístico, nunca LLM (§1.1.3): estas regras REPROVAM
(CriativoInvalido → 422); o LLM 20b apenas ACRESCENTA warnings não bloqueantes
(agents/criativo.py::montar_mensagens_compliance — "regras + warn LLM").

Regras v1:
1. SMS: `mensagem` ≤ 160 caracteres (A1 — 161 → 422).
2. WhatsApp: célula exige `template` {nome, status} com status `aprovado` (template
   fora do ciclo de aprovação Meta não dispara).
3. Compliance de linguagem: termos proibidos (promessa absoluta/enganosa) em qualquer
   texto da célula ou do KV master. Lista v1 mínima — a política editorial do tenant
   (policy_versao §4.1) poderá estendê-la sem tocar este módulo.
"""

from __future__ import annotations

from typing import Any

from domain.criativo.erros import CriativoInvalido
from domain.criativo.modelos import CelulaCriativo

LIMITE_SMS = 160  # §8-M6-A1

STATUS_TEMPLATE_APROVADO = "aprovado"

# Compliance de linguagem v1 (promessas absolutas/enganosas — regra determinística)
TERMOS_PROIBIDOS: tuple[str, ...] = (
    "100% grátis",
    "totalmente grátis",
    "sem nenhum custo",
    "custo zero garantido",
    "garantia total",
    "garantido para sempre",
    "melhor do mercado",
    "imbatível",
)


def _textos(conteudo: dict[str, Any]) -> list[str]:
    """Todos os valores textuais (1 nível) — campos de texto da célula/KV."""
    return [valor for valor in conteudo.values() if isinstance(valor, str)]


def termos_proibidos_no_texto(conteudo: dict[str, Any]) -> list[str]:
    """Termos da lista v1 presentes em algum texto (case-insensitive)."""
    junto = " ".join(_textos(conteudo)).lower()
    return [termo for termo in TERMOS_PROIBIDOS if termo in junto]


def problemas_da_celula(canal: str, variante: str, conteudo: dict[str, Any]) -> list[str]:
    """Problemas BLOQUEANTES da célula ([] quando conforme). Regras na docstring."""
    rotulo = f"{canal}/{variante}"
    problemas: list[str] = []
    mensagem = conteudo.get("mensagem")
    if not isinstance(mensagem, str) or not mensagem.strip():
        problemas.append(f"{rotulo}: célula sem `mensagem` (contrato da matriz §8-M6).")
        mensagem = ""
    if canal == "sms" and len(mensagem) > LIMITE_SMS:
        problemas.append(
            f"{rotulo}: SMS com {len(mensagem)} caracteres — limite {LIMITE_SMS} (A1)."
        )
    if canal == "whatsapp":
        template = conteudo.get("template")
        status = template.get("status") if isinstance(template, dict) else None
        if status != STATUS_TEMPLATE_APROVADO:
            problemas.append(
                f"{rotulo}: template WhatsApp com status {status!r} — "
                f"exigido {STATUS_TEMPLATE_APROVADO!r} (§8-M6)."
            )
    for termo in termos_proibidos_no_texto(conteudo):
        problemas.append(f"{rotulo}: termo proibido de linguagem: {termo!r} (compliance §8-M6).")
    return problemas


def problemas_do_kv_master(kv_master: dict[str, Any]) -> list[str]:
    """Compliance de linguagem sobre o KV master (edição também é validada — A2)."""
    return [
        f"kv_master: termo proibido de linguagem: {termo!r} (compliance §8-M6)."
        for termo in termos_proibidos_no_texto(kv_master)
    ]


def validar_celulas(celulas: list[CelulaCriativo]) -> None:
    """Veredito por código: qualquer problema bloqueante → CriativoInvalido (422)."""
    problemas = [
        problema
        for celula in celulas
        for problema in problemas_da_celula(celula.canal, celula.variante, celula.conteudo)
    ]
    if problemas:
        raise CriativoInvalido(
            "Validadores determinísticos reprovaram a matriz (§8-M6): " + " · ".join(problemas),
            problemas=problemas,
        )


def validar_kv_master(kv_master: dict[str, Any]) -> None:
    """KV master com termo proibido → CriativoInvalido (422)."""
    problemas = problemas_do_kv_master(kv_master)
    if problemas:
        raise CriativoInvalido(
            "Compliance de linguagem reprovou o KV master (§8-M6): " + " · ".join(problemas),
            problemas=problemas,
        )
