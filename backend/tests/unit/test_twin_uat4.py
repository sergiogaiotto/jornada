"""Regressões do UAT #4 (docs/UAT4-VPS-2026-08-06-twin.md) — emendas D03/D05/D07.

Os três achados vieram de grafos REAIS: D07 e D03 do JGC que o gpt-oss-120b gerou na
VPS para a OS-2026-0457 (que passou na validação e derrubou o simulador com HTTP 500),
D05 de um `frequencySplit` montado conforme o §5.2.
"""

from decimal import Decimal
from typing import Any

import pytest

from adapters.aleatorio import rng_disponivel
from domain.jornada.taximetro import calcular
from domain.jornada.validacao import validar_grafo
from domain.simulacao.motor import simular

PRIORS: dict[str, Any] = {
    "entrega": {"email": 0.95, "sms": 0.98},
    "abertura": {"email": 0.25},
    "conversao": {"email": 0.03, "sms": 0.02},
    "ticket_medio": 120.0,
    "organico": 0.01,
}


def _no(id_: str, tipo: str, **data: Any) -> dict[str, Any]:
    return {"id": id_, "type": tipo, "data": data}


def _ar(id_: str, de: str, para: str, **extra: Any) -> dict[str, Any]:
    return {"id": id_, "from": de, "to": para, **extra}


def _base(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    """`meta` completo (§5.1) — via HTTP quem o preenche é `_normalizar_meta`."""
    return {
        "jgcVersion": "1.0",
        "meta": {"osCodigo": "OS-2026-0457", "tenant": "torre-movel", "reentrada": "nao"},
        "nodes": nodes,
        "edges": edges,
    }


ENTRADA = _no("n1", "entrySource", deRef="DE_x", modo="fire_once", reentrada="nao")
META = _no("n9", "goal", metrica="conversao", deRef="DE_m")
SAIDA = _no("n0", "exit", motivo="fim")


# ------------------------------------------------------------------ D07 (crítico)
def _grafo_do_120b() -> dict[str, Any]:
    """decisionSplit com `regras` SEM `to` — o roteamento vive nas arestas `cond`.

    Forma exata gerada pelo Flow na VPS. É um grafo VÁLIDO: as duas saídas existem
    como arestas. O motor é que assumia `regra["to"]`.
    """
    return _base(
        [
            ENTRADA,
            _no("n2", "decisionSplit", regras=[{"id": "eligible", "cond": "optIn"}]),
            _no("n3", "channel.email", assetRef="ast-1", optIn=True),
            META,
            SAIDA,
        ],
        [
            _ar("e1", "n1", "n2"),
            _ar("e2", "n2", "n3", cond="eligible"),
            _ar("e3", "n2", "n0", cond="ineligible"),
            _ar("e4", "n3", "n9"),
            _ar("e5", "n9", "n0"),
        ],
    )


def test_D07_grafo_do_120b_e_valido() -> None:
    """Premissa do achado: o validador aprova — o 500 vinha depois, no simulador."""
    assert validar_grafo(_grafo_do_120b()) == []


def _simular(grafo: dict[str, Any], *, runs: int = 20, seed: int = 42) -> dict[str, Any]:
    return simular(
        grafo,
        volume_entrada=1000,
        personas={},
        priors=PRIORS,
        tarifas={"email": Decimal("0.0018")},
        politica={},
        ger=rng_disponivel().gerador(seed),
        runs=runs,
        ticket_medio=120.0,
        hora_inicio=9.0,
    )


def test_D07_simular_nao_estoura_com_regra_sem_to() -> None:
    """Era `KeyError: 'to'` em motor.py::_saidas → HTTP 500 em POST /simular."""
    resultado = _simular(_grafo_do_120b())
    assert resultado["funil"]["n3"]["p50"] > 0, "o e-mail tem de receber volume"


def test_D07_taximetro_e_simulador_veem_a_mesma_adjacencia() -> None:
    """Fonte única (domain/jornada/adjacencia.py): mesmo grafo, mesmo caminho."""
    custo, memoria, _ = calcular(
        _grafo_do_120b(), volume_entrada=1000, tarifas={"email": Decimal("0.0018")}
    )
    assert [linha["no"] for linha in memoria] == ["n3"]
    assert custo > 0


@pytest.mark.parametrize(
    "malformado",
    [
        {"id": "r1"},  # regra sem `to` nem nada
        {"id": "r1", "to": None},
        "regra_string_em_vez_de_objeto",
    ],
)
def test_D07_regra_malformada_nunca_estoura(malformado: Any) -> None:
    """A13 estendida ao motor: dado torto é ignorado na adjacência, não explode."""
    grafo = _base(
        [ENTRADA, _no("n2", "decisionSplit", regras=[malformado]), META, SAIDA],
        [_ar("e1", "n1", "n2"), _ar("e2", "n2", "n9"), _ar("e3", "n9", "n0")],
    )
    _simular(grafo, runs=5, seed=1)


# ---------------------------------------------------------------------- D03 (wait)
@pytest.mark.parametrize(
    "duracao",
    ["imediato_apos_quiet_hours", "3 dias", "P90", "PT90D", "", "P"],
)
def test_D03_duracao_fora_do_iso_e_rejeitada(duracao: str) -> None:
    """`imediato_apos_quiet_hours` é o valor real que o 120b emitiu e passou."""
    grafo = _base(
        [ENTRADA, _no("w", "wait", duracao=duracao), META, SAIDA],
        [_ar("e1", "n1", "w"), _ar("e2", "w", "n9"), _ar("e3", "n9", "n0")],
    )
    erros = validar_grafo(grafo)
    assert [e["regra"] for e in erros] == ["duracao_invalida"]


@pytest.mark.parametrize("duracao", ["P1D", "P2W", "PT12H", "PT30M", "P1DT6H"])
def test_D03_duracao_iso_valida_passa(duracao: str) -> None:
    grafo = _base(
        [ENTRADA, _no("w", "wait", duracao=duracao), META, SAIDA],
        [_ar("e1", "n1", "w"), _ar("e2", "w", "n9"), _ar("e3", "n9", "n0")],
    )
    assert validar_grafo(grafo) == []


def test_D03_wait_por_data_ate_segue_valendo() -> None:
    """O anyOf do §5.2 é `duracao` OU `ate` — quem usa `ate` não é afetado."""
    grafo = _base(
        [ENTRADA, _no("w", "wait", ate="2026-11-20T10:00:00Z"), META, SAIDA],
        [_ar("e1", "n1", "w"), _ar("e2", "w", "n9"), _ar("e3", "n9", "n0")],
    )
    assert validar_grafo(grafo) == []


# ------------------------------------------------------------- D05 (frequencySplit)
def test_D05_classes_como_objeto_com_arestas_certas_e_valido() -> None:
    """A forma do §5.2 (classe com faixa) era impossível de salvar: o validador
    comparava a repr do dict contra as conds e nunca casava."""
    grafo = _base(
        [
            ENTRADA,
            _no(
                "fq",
                "frequencySplit",
                classes=[{"id": "baixa", "max": 2}, {"id": "alta", "min": 3}],
                fonte="DE_freq",
            ),
            _no("a", "channel.sms", assetRef="s1", optIn=True),
            _no("b", "channel.push", assetRef="s2", optIn=True),
            META,
            SAIDA,
        ],
        [
            _ar("e1", "n1", "fq"),
            _ar("e2", "fq", "a", cond="baixa"),
            _ar("e3", "fq", "b", cond="alta"),
            _ar("e4", "a", "n9"),
            _ar("e5", "b", "n9"),
            _ar("e6", "n9", "n0"),
        ],
    )
    assert validar_grafo(grafo) == []


def test_D05_classe_objeto_sem_destino_ainda_e_barrada() -> None:
    """O fix não pode cegar a regra: classe sem aresta continua erro — e a mensagem
    passa a nomear a classe (`'alta'`), não despejar o dict."""
    grafo = _base(
        [
            ENTRADA,
            _no(
                "fq",
                "frequencySplit",
                classes=[{"id": "baixa", "max": 2}, {"id": "alta", "min": 3}],
                fonte="DE_freq",
            ),
            _no("a", "channel.sms", assetRef="s1", optIn=True),
            META,
            SAIDA,
        ],
        [
            _ar("e1", "n1", "fq"),
            _ar("e2", "fq", "a", cond="baixa"),
            _ar("e4", "a", "n9"),
            _ar("e6", "n9", "n0"),
        ],
    )
    erros = validar_grafo(grafo)
    assert [e["regra"] for e in erros] == ["braco_sem_destino"]
    assert "'alta'" in erros[0]["mensagem"]


def test_D05_classes_como_string_seguem_valendo() -> None:
    grafo = _base(
        [
            ENTRADA,
            _no("fq", "frequencySplit", classes=["baixa", "alta"], fonte="DE_freq"),
            _no("a", "channel.sms", assetRef="s1", optIn=True),
            _no("b", "channel.push", assetRef="s2", optIn=True),
            META,
            SAIDA,
        ],
        [
            _ar("e1", "n1", "fq"),
            _ar("e2", "fq", "a", cond="baixa"),
            _ar("e3", "fq", "b", cond="alta"),
            _ar("e4", "a", "n9"),
            _ar("e5", "b", "n9"),
            _ar("e6", "n9", "n0"),
        ],
    )
    assert validar_grafo(grafo) == []
