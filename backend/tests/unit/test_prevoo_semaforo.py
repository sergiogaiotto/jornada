"""Unit C04 (UAT #3 adversarial): o pré-voo não pode ficar verde sem ter verificado.

O achado: `drift_zero` devolvia `pass` com `{'verificados': 0}` — logicamente explicável
(nada publicado para comparar), mas numa tela de governança o operador lê "sem drift"
onde a verdade é "nada foi comparado". A regra agora é de CÓDIGO (domain/jornada/prevoo):
item não verificável é `n/a`, e `n/a` nunca vira verde — só `fail` bloqueia (§5.4.4).
"""

from domain.jornada.prevoo import FAIL, NAO_APLICAVEL, PASS, WARN, item, semaforo


def test_na_nao_conta_como_aprovacao() -> None:
    """Bateria só com `pass` fica verde; troque UM item por `n/a` e ela sai do verde."""
    todos_pass = [item(f"i{n}", PASS, {}) for n in range(4)]
    assert semaforo(todos_pass) == "verde"

    com_na = [*todos_pass[:-1], item("drift_zero", NAO_APLICAVEL, {"verificados": 0})]
    assert semaforo(com_na) == "amarelo"


def test_na_sozinho_nao_pinta_verde() -> None:
    """Nenhum item verificado (tudo `n/a`) não é bateria aprovada."""
    assert semaforo([item("drift_zero", NAO_APLICAVEL, {"verificados": 0})]) == "amarelo"


def test_na_nao_bloqueia_como_fail() -> None:
    """`n/a` é aviso, não reprovação: quem pinta de vermelho (e bloqueia o apply
    em §5.4.4) continua sendo exclusivamente o `fail`."""
    assert semaforo([item("a", PASS, {}), item("b", NAO_APLICAVEL, {})]) != "vermelho"
    assert semaforo([item("a", PASS, {}), item("b", WARN, {})]) == "amarelo"
    assert semaforo([item("a", NAO_APLICAVEL, {}), item("b", FAIL, {})]) == "vermelho"
