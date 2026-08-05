"""Unit do domínio intake (§8-M3): completude/faltantes são CÓDIGO determinístico."""

import uuid

from domain.intake import completude
from domain.intake.modelos import CAMPOS_OBRIGATORIOS, Pedido


def _entrada(valor: object) -> dict[str, object]:
    return {"valor": valor, "inferido": False}


def _pedido(conteudo: dict[str, object]) -> Pedido:
    return Pedido(
        id=uuid.uuid4(),
        tenant_id="torre-movel",
        solicitante={"nome": "x"},
        conteudo=conteudo,
        completude=0.0,
    )


def test_campos_obrigatorios_do_sdd() -> None:
    """§8-M3: objetivo, público, oferta, verba, janela — nesta ordem canônica."""
    assert CAMPOS_OBRIGATORIOS == ("objetivo", "publico", "oferta", "verba", "janela")


def test_calcular_vazio_e_completo() -> None:
    assert completude.calcular({}) == (0.0, list(CAMPOS_OBRIGATORIOS))
    cheio = {campo: _entrada(f"v-{campo}") for campo in CAMPOS_OBRIGATORIOS}
    assert completude.calcular(cheio) == (100.0, [])


def test_valores_vazios_nao_contam_e_extras_nao_pontuam() -> None:
    conteudo = {
        "objetivo": _entrada("Upgrade 5G"),
        "publico": _entrada("   "),  # branco não conta
        "oferta": _entrada(None),  # None não conta
        "verba": _entrada(0),  # 0 é valor dado → conta
        "canais": _entrada("email"),  # extra fora dos obrigatórios não pontua
    }
    pct, faltantes = completude.calcular(conteudo)
    assert pct == 40.0  # objetivo + verba
    assert faltantes == ["publico", "oferta", "janela"]  # ordem canônica


def test_calcular_aceita_valor_cru_por_robustez() -> None:
    pct, faltantes = completude.calcular({"objetivo": "texto cru sem envelope"})
    assert pct == 20.0 and "objetivo" not in faltantes


def test_atualizar_deriva_estado_rascunho_completo_e_preserva_convertido() -> None:
    pedido = _pedido({"objetivo": _entrada("x")})
    completude.atualizar(pedido)
    assert pedido.estado == "rascunho" and pedido.completude == 20.0

    pedido.conteudo = {campo: _entrada("v") for campo in CAMPOS_OBRIGATORIOS}
    completude.atualizar(pedido)
    assert pedido.estado == "completo" and pedido.completude == 100.0 and pedido.faltantes == []

    pedido.estado = "convertido"  # terminal: atualizar não rebaixa
    completude.atualizar(pedido)
    assert pedido.estado == "convertido"
