"""J05 (onda 6) — a T16 renderiza `invocacao.tokens`: o fecho de UI do I04.

A medição nasceu na onda 5 (I04: o usage flui até o ledger), a API já expunha o campo
(`_invocacao_out`), e NENHUMA tela consumia — a promessa do §8-M12 ("trilha via_ai
clicável") e do guia da página /atelie existia sem o painel. O J05 cria o painel de
auditoria na T16 e este guarda-corpo o prende ao CI, porque o frontend não tem harness
de teste (mesma justificativa do espelho do I02): sem o grep, o campo pode sumir do
JSX em silêncio com a suíte verde.

Padrão do F04 bloco IV: afirmar a FORMA DE ACESSO no fonte, nunca o nome nu do campo —
buscar só "tokens" casaria com a declaração da interface TS e daria verde sem JSX
nenhum (a lição documentada em test_F04_natureza_e_limites).
"""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
TELA = RAIZ / "frontend" / "src" / "pages" / "Atelie.tsx"
TYPES = RAIZ / "frontend" / "src" / "lib" / "types.ts"


def _sem_comentarios(fonte: str) -> str:
    """Remove comentários TS/JSX — acesso citado em comentário não é acesso."""
    fonte = re.sub(r"/\*.*?\*/", "", fonte, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", fonte, flags=re.MULTILINE)


def test_J05_a_tela_acessa_tokens_pela_forma_formatada() -> None:
    corpo = _sem_comentarios(TELA.read_text(encoding="utf-8"))
    assert "fmtInt(det?.tokens)" in corpo or "fmtInt(det.tokens)" in corpo, (
        "Atelie.tsx deixou de renderizar `tokens` via fmtInt — o painel de auditoria "
        "da T16 (J05) é o único consumidor de UI da medição do I04; sem ele o campo "
        "volta a ser número que ninguém vê. Reaplique a coluna com fmtInt (null → “—”)."
    )
    assert "latencia_ms" in corpo, (
        "Atelie.tsx deixou de renderizar `latencia_ms` — a métrica vizinha do §10.8 "
        "sai da tela junto com o painel de auditoria."
    )


def test_J05_null_nunca_vira_zero_na_tela() -> None:
    """Doutrina do I04: ausência de medida (hub sem usage) aparece como “—”, jamais
    como 0 — `?? 0` sobre tokens/latência trairia o contrato na última milha."""
    corpo = _sem_comentarios(TELA.read_text(encoding="utf-8"))
    assert "tokens ?? 0" not in corpo and "latencia_ms ?? 0" not in corpo, (
        "A tela está convertendo métrica nula em 0 — ausência de medida não é medida "
        "zero (I04). Use fmtInt, que devolve “—” para null."
    )


def test_J05_o_contrato_ts_mantem_tokens_anulavel() -> None:
    tipos = TYPES.read_text(encoding="utf-8")
    assert "tokens: number | null" in tipos, (
        "types.ts perdeu `tokens: number | null` no detalhe da invocação — estreitar "
        "para `number` esconderia do compilador exatamente o caso (provedor sem usage) "
        "que a tela precisa tratar como “—”."
    )
    assert "latencia_ms: number | null" in tipos
