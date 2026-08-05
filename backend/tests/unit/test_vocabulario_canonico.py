"""A20 — guarda-corpo de vocabulário canônico (regressão real: agentes reintroduziram
"RAID" no guia visível ao usuário). Termos banidos em texto de UI: RAID (é pendência,
ex-Hike). Varre frontend/src e as skills; docstrings/backend técnico ficam de fora."""

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
BANIDOS = ["RAID"]
ALVOS = [RAIZ / "frontend" / "src", RAIZ / "backend" / "agents" / "skills"]


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
