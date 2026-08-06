"""KV master DEFAULT derivado do briefing da OS (§8-M6 — achado A8 do UAT 2026-08-05).

CÓDIGO PURO, ZERO LLM (§1.1.3): o Estúdio Criativo abria com um KV master fixo — copy
da campanha de franquia — que aparecia até em OS de outro tema (recarga, portabilidade…).
Aqui o default nasce do BRIEFING da própria OS:

- `headline` ← `objetivo` (1ª frase, capitalizada, truncada);
- `oferta`   ← `oferta` (truncada);
- `cta`      ← verbo canônico da intenção do `objetivo` + forma do canal real
  (`canais` só conversacionais → "Responda SIM"; caso contrário "{verbo} agora");
- `tom`      ← `tom_de_marca` quando houver.

Campo sem fonte no briefing → PLACEHOLDER neutro e explícito (`PLACEHOLDER_HEADLINE`
= "(defina o Key Visual)"): o default JAMAIS inventa copy de uma campanha alheia
(§1.3.5 — nada é inventado; o KV é ponto de partida que o humano edita).

Nota de compliance: a derivação NÃO censura o briefing — se o texto do briefing tiver
termo proibido (validadores.py), o `POST /criativos/gerar` reprova com 422 apontando o
termo, que é o veredito determinístico correto.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from domain.criativo.modelos import CANAIS_CRIATIVO

# Placeholders neutros (nunca copy de outra campanha — A8)
PLACEHOLDER_HEADLINE = "(defina o Key Visual)"
PLACEHOLDER_OFERTA = "(defina a oferta)"
PLACEHOLDER_CTA = "(defina o CTA)"
PLACEHOLDER_TOM = "(defina o tom de marca)"

LIMITE_HEADLINE = 90
LIMITE_OFERTA = 120

# Canais que respondem no próprio canal — CTA vira resposta, não clique (§8-M6)
CANAIS_CONVERSACIONAIS: tuple[str, ...] = ("sms", "whatsapp")

# Intenção do objetivo → verbo do CTA. Varredura determinística NA ORDEM declarada
# (radicais sem acento, casados por substring no objetivo normalizado).
VERBOS_POR_INTENCAO: tuple[tuple[str, str], ...] = (
    ("recarg", "Recarregar"),
    ("upgrade", "Fazer upgrade"),
    ("upsell", "Fazer upgrade"),
    ("migra", "Migrar"),
    ("portabilidade", "Portar meu número"),
    ("renov", "Renovar"),
    ("reten", "Continuar"),
    ("churn", "Continuar"),
    ("ativa", "Ativar"),
    ("assin", "Assinar"),
    ("contrat", "Contratar"),
    ("ades", "Aderir"),
    ("adquir", "Adquirir"),
    ("compra", "Comprar"),
    ("agenda", "Agendar"),
)

CTA_CONVERSACIONAL = "Responda SIM"
CTA_GENERICO = "Saiba mais"


def _sem_acento(texto: str) -> str:
    normalizado = unicodedata.normalize("NFD", texto)
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn")


def _valor(briefing: Mapping[str, Any], campo: str) -> Any:
    """Briefing da OS é `{campo: {valor, inferido}}` (§8-M3), mas a OS pode ser criada
    com valores crus (`POST /os` com `briefing={"objetivo": "..."}`) — aceita os dois."""
    entrada = briefing.get(campo)
    if isinstance(entrada, Mapping) and "valor" in entrada:
        return entrada.get("valor")
    return entrada


def _texto(briefing: Mapping[str, Any], campo: str) -> str:
    valor = _valor(briefing, campo)
    return " ".join(valor.split()) if isinstance(valor, str) else ""


def _truncar(texto: str, limite: int) -> str:
    """Corta na última palavra inteira dentro do limite (sem picar palavra)."""
    if len(texto) <= limite:
        return texto
    corte = texto[: limite - 1].rstrip()
    if " " in corte:
        corte = corte[: corte.rindex(" ")].rstrip()
    return f"{corte}…"


def _primeira_frase(texto: str) -> str:
    return re.split(r"(?<=[.!?])\s|[;\n]", texto, maxsplit=1)[0].strip(" .;")


def _capitalizar(texto: str) -> str:
    return texto[:1].upper() + texto[1:] if texto else texto


def canais_do_briefing(briefing: Mapping[str, Any]) -> list[str]:
    """Canais REAIS do briefing (`canais` como lista ou texto livre) na ordem canônica
    de CANAIS_CRIATIVO; o que não é canal da matriz é ignorado."""
    valor = _valor(briefing, "canais")
    if isinstance(valor, str):
        bruto = valor
    elif isinstance(valor, list | tuple | set):
        bruto = " ".join(str(item) for item in valor)
    else:
        return []
    texto = _sem_acento(bruto).lower().replace("-", "")
    return [canal for canal in CANAIS_CRIATIVO if canal in texto]


def _cta(objetivo: str, canais: list[str]) -> str:
    if canais and all(canal in CANAIS_CONVERSACIONAIS for canal in canais):
        return CTA_CONVERSACIONAL  # SMS/WhatsApp: o cliente responde no próprio canal
    alvo = _sem_acento(objetivo).lower()
    for radical, verbo in VERBOS_POR_INTENCAO:
        if radical in alvo:
            return f"{verbo} agora"
    return CTA_GENERICO if (objetivo or canais) else PLACEHOLDER_CTA


def derivar_kv_master(briefing: Mapping[str, Any] | None) -> dict[str, str]:
    """KV master default da OS — determinístico, a partir do briefing (A8).

    Sem `objetivo`/`oferta`/`tom_de_marca` no briefing os campos correspondentes saem
    como placeholder explícito; NUNCA como copy de outra campanha.
    """
    briefing = briefing or {}
    objetivo = _texto(briefing, "objetivo")
    oferta = _texto(briefing, "oferta")
    tom = _texto(briefing, "tom_de_marca")
    canais = canais_do_briefing(briefing)

    headline = (
        _capitalizar(_truncar(_primeira_frase(objetivo), LIMITE_HEADLINE))
        if objetivo
        else PLACEHOLDER_HEADLINE
    )
    return {
        "headline": headline,
        "oferta": _capitalizar(_truncar(oferta, LIMITE_OFERTA)) if oferta else PLACEHOLDER_OFERTA,
        "cta": _cta(objetivo, canais),
        "tom": tom if tom else PLACEHOLDER_TOM,
    }


def campos_derivados(briefing: Mapping[str, Any] | None) -> list[str]:
    """Campos do briefing que alimentaram o default (rastro honesto para a UI)."""
    briefing = briefing or {}
    usados = [campo for campo in ("objetivo", "oferta", "tom_de_marca") if _texto(briefing, campo)]
    if canais_do_briefing(briefing):
        usados.append("canais")
    return usados


def suficiente(briefing: Mapping[str, Any] | None) -> bool:
    """Há briefing suficiente para um KV de partida? (objetivo OU oferta)."""
    briefing = briefing or {}
    return bool(_texto(briefing, "objetivo") or _texto(briefing, "oferta"))
