"""Guarda-corpos de TEXTO DE UI — o que o usuário lê é contrato, e regrediu na prática:

- A20: agentes reintroduziram "RAID" no guia visível ao usuário (é pendência, ex-Hike);
- B03 (UAT #2): a Sala de Ideação mostrava uma régua só ("0 de 5 campos confirmados")
  ao lado de um medidor em 100% — números certos, leitura de contradição.

Varre frontend/src e as skills; docstrings/backend técnico ficam de fora."""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
BANIDOS = ["RAID"]
ALVOS = [RAIZ / "frontend" / "src", RAIZ / "backend" / "agents" / "skills"]
IDEACAO = RAIZ / "frontend" / "src" / "pages" / "Ideacao.tsx"


def test_vocabulario_canonico_sem_termos_banidos():
    violacoes = []
    for alvo in ALVOS:
        for arq in alvo.rglob("*"):
            if arq.suffix not in {".ts", ".tsx", ".md"}:
                continue
            texto = arq.read_text(encoding="utf-8", errors="ignore")
            for termo in BANIDOS:
                if termo in texto:
                    violacoes.append(f"{arq.relative_to(RAIZ)}: '{termo}'")
    assert not violacoes, "Vocabulário banido reintroduzido (use 'pendência'): " + "; ".join(
        violacoes
    )


def test_ideacao_mostra_as_duas_reguas_de_campos():
    """B03: preenchido (o que o medidor mede) e confirmado (toque humano sobre a
    inferência) são réguas DIFERENTES — o cabeçalho tem de nomear as duas, nas duas
    Salas (modo pedido e modo OS). "N de M campos confirmados" sozinho está banido:
    é a frase que convivia com 100% e lia como contradição."""
    # comentários CITAM a frase banida ao explicar o achado — o contrato é o código
    corpo = re.sub(r"/\*.*?\*/", "", IDEACAO.read_text(encoding="utf-8"), flags=re.DOTALL)
    assert "campos confirmados" not in corpo, "régua única ambígua reintroduzida (B03)"
    assert "preenchidos" in corpo and "confirmados" in corpo
    assert corpo.count("<ReguasCampos") == 2, "as duas Salas (pedido e OS) mostram as réguas"
