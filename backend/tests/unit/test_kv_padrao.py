"""A8 — KV master default DERIVADO do briefing (domain/criativo/kv_padrao.py).

Regressão real do UAT 2026-08-05: o Estúdio Criativo abria com copy fixa da campanha de
franquia ("Chega de estourar a franquia"), que aparecia até em OS de recarga. Aqui:
função pura (código, ZERO LLM §1.1.3) + guarda-corpo contra reintrodução do texto fixo
no front (mesmo padrão do vocabulário canônico A20).
"""

from pathlib import Path
from typing import Any

from domain.criativo.kv_padrao import (
    PLACEHOLDER_CTA,
    PLACEHOLDER_HEADLINE,
    PLACEHOLDER_OFERTA,
    PLACEHOLDER_TOM,
    campos_derivados,
    canais_do_briefing,
    derivar_kv_master,
    suficiente,
)

RAIZ = Path(__file__).resolve().parents[3]

# Copy da campanha de franquia que era o default hardcoded (A8) — não pode voltar.
COPY_FIXA_BANIDA = [
    "Chega de estourar a franquia",
    "2× de dados pelo mesmo valor",
    "claro.com/up",
]

BRIEFING_RECARGA: dict[str, Any] = {  # shape do briefing da OS (§8-M3)
    "objetivo": {"valor": "Reativar pré-pago sem recarga há 30 dias", "inferido": False},
    "oferta": {"valor": "Bônus de 2 GB na recarga de R$ 30", "inferido": True},
    "canais": {"valor": ["sms", "whatsapp"], "inferido": False},
    "tom_de_marca": {"valor": "Simples e direto, sem jargão", "inferido": False},
}


def test_kv_padrao_deriva_do_briefing_da_os() -> None:
    """OS de recarga → KV do PRÓPRIO briefing; nada da campanha de franquia."""
    kv = derivar_kv_master(BRIEFING_RECARGA)
    assert kv["headline"] == "Reativar pré-pago sem recarga há 30 dias"
    assert kv["oferta"] == "Bônus de 2 GB na recarga de R$ 30"
    assert kv["cta"] == "Responda SIM"  # canais REAIS só conversacionais (sms/whatsapp)
    assert kv["tom"] == "Simples e direto, sem jargão"
    junto = " ".join(kv.values()).lower()
    assert "franquia" not in junto and "estourar" not in junto
    assert campos_derivados(BRIEFING_RECARGA) == ["objetivo", "oferta", "tom_de_marca", "canais"]
    assert suficiente(BRIEFING_RECARGA)


def test_kv_padrao_aceita_briefing_cru_e_canais_em_texto() -> None:
    """`POST /os` aceita briefing com valores crus; `canais` pode vir como texto livre."""
    briefing = {
        "objetivo": "Upgrade de clientes pós-pago para planos 5G. Meta: 248 conversões.",
        "oferta": "2× dados por 6 meses",
        "canais": "E-mail e Push Minha Claro",
    }
    assert canais_do_briefing(briefing) == ["email", "push"]
    kv = derivar_kv_master(briefing)
    assert kv["headline"] == "Upgrade de clientes pós-pago para planos 5G"  # 1ª frase
    assert kv["cta"] == "Fazer upgrade agora"  # verbo da intenção + canal de clique
    assert kv["tom"] == PLACEHOLDER_TOM  # sem tom_de_marca → placeholder, não copy alheia


def test_kv_padrao_sem_briefing_e_placeholder_neutro() -> None:
    """Briefing insuficiente → placeholder explícito, JAMAIS o texto de outra campanha."""
    for vazio in (None, {}, {"verba": "R$ 10.000"}):
        kv = derivar_kv_master(vazio)
        assert kv == {
            "headline": PLACEHOLDER_HEADLINE,
            "oferta": PLACEHOLDER_OFERTA,
            "cta": PLACEHOLDER_CTA,
            "tom": PLACEHOLDER_TOM,
        }
        assert not suficiente(vazio) and campos_derivados(vazio) == []


def test_kv_padrao_headline_truncada_sem_picar_palavra() -> None:
    objetivo = "Reativar " + "clientes inativos " * 12
    headline = derivar_kv_master({"objetivo": objetivo})["headline"]
    assert len(headline) <= 91 and headline.endswith("…") and not headline.endswith(" …")


def test_sem_copy_fixa_de_campanha_no_front() -> None:
    """Guarda-corpo A8: nenhum default de campanha hardcoded no front (nem no back)."""
    alvos = [RAIZ / "frontend" / "src", RAIZ / "backend"]
    violacoes = [
        f"{arq.relative_to(RAIZ)}: {termo!r}"
        for alvo in alvos
        for arq in alvo.rglob("*")
        if arq.suffix in {".ts", ".tsx", ".py"} and arq.name != Path(__file__).name
        for termo in COPY_FIXA_BANIDA
        if termo in arq.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not violacoes, (
        "KV default voltou a ser copy fixa de campanha (A8) — derive do briefing: "
        + "; ".join(violacoes)
    )
