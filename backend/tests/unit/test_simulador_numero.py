"""Regressão da auditoria MS8: `_numero` (simulador_service) precisa aceitar campos
do briefing na forma §4.1 (`{valor, inferido}`) e valores humanos pt-BR ("R$ 500.000")
— antes o `simular` estourava 500 (`float(dict)`) na OS nascida do intake real."""

import pytest

from application.services.simulador_service import _numero


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (260.0, 260.0),
        (32_000, 32_000.0),
        ({"valor": 260.0, "inferido": False}, 260.0),  # forma §4.1 do briefing
        ({"valor": "R$ 500.000", "inferido": False}, 500_000.0),
        ("R$ 500.000", 500_000.0),  # moeda pt-BR (milhar com ponto)
        ("R$ 1.234,56", 1_234.56),  # decimal com vírgula
        ("1234.5", 1_234.5),  # decimal com ponto (2 casas ≠ milhar)
        ("R$ 32.000.000", 32_000_000.0),  # múltiplos milhares
        (None, None),
        (True, None),  # bool não é verba
        ("a definir", None),  # não-numérico → None (não bloqueia o Ensaio)
        ({"valor": None, "inferido": True}, None),
    ],
)
def test_numero_coercao_tolerante(valor: object, esperado: float | None) -> None:
    assert _numero(valor) == esperado
