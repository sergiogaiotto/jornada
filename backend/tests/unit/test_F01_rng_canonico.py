"""Emenda F01 — o backend de RNG é ÚNICO e declarado (§6 / M8-A1).

`adapters/aleatorio.rng_disponivel()` escolhe entre `RngNumpy` (binomial exata
vetorizada) e `RngPadrao` (stdlib) conforme o numpy esteja instalado. Como o numpy não
constava do `requirements.txt`, a escolha era ACIDENTAL: máquina de dev com numpy
produzia conversões P50 1625,0 e o CI/VPS sem numpy produzia 1736,5 — para o MESMO
grafo e a MESMA seed. O §6 promete o contrário, e o "Previsto congelado" (§1.1.2) é a
régua contra a qual o realizado é medido depois do lançamento: um número aprovado em
homologação não se reproduzia em produção.

Estes testes falham se alguém tirar o numpy das dependências ou trocar o backend sem
emendar o SDD — o custo de descobrir isso de novo por um assert numérico quebrado no CI
já foi pago uma vez.
"""

from decimal import Decimal
from typing import Any

from adapters.aleatorio import RngNumpy, rng_disponivel
from domain.simulacao.motor import simular
from domain.simulacao.personas import gerar_personas
from domain.simulacao.priors import PRIORS_DEFAULT

PRIORS: dict[str, Any] = PRIORS_DEFAULT

GRAFO: dict[str, Any] = {
    "jgcVersion": "1.0",
    "meta": {"osCodigo": "OS-F01", "tenant": "torre-movel", "reentrada": "nao"},
    "nodes": [
        {
            "id": "n1",
            "type": "entrySource",
            "data": {"deRef": "DE_x", "modo": "fire_once", "reentrada": "nao"},
        },
        {"id": "em", "type": "channel.email", "data": {"assetRef": "ast-1", "optIn": True}},
        {"id": "n9", "type": "goal", "data": {"metrica": "conversao", "deRef": "DE_c"}},
        {"id": "n0", "type": "exit", "data": {"motivo": "fim"}},
    ],
    "edges": [
        {"id": "e1", "from": "n1", "to": "em"},
        {"id": "e2", "from": "em", "to": "n9"},
        {"id": "e3", "from": "n9", "to": "n0"},
    ],
}


def _simular(seed: int) -> dict[str, Any]:
    """Mesma montagem do `SimuladorService`: as PERSONAS também saem do gerador.

    Sem elas o motor vira determinístico (o volume atravessa o grafo sem amostragem) e
    a seed não tem o que influenciar — foi assim que a primeira versão deste teste deu
    resultado idêntico para seeds distintas e quase virou "achado"."""
    ger = rng_disponivel().gerador(seed)
    personas = gerar_personas(n=10_000, priors=PRIORS, ger=ger)
    return simular(
        GRAFO,
        volume_entrada=10_000,
        personas=personas,
        priors=PRIORS,
        tarifas={"email": Decimal("0.0018")},
        politica={},
        ger=ger,
        runs=50,
        ticket_medio=120.0,
        hora_inicio=9.0,
    )


def test_F01_backend_de_rng_e_o_numpy() -> None:
    """numpy é dependência declarada (§3.2) — o fallback stdlib não é o caminho normal.

    Se este teste falhar, o ambiente está rodando OUTRO algoritmo de amostragem e os
    percentis NÃO são comparáveis com os de outro ambiente.
    """
    assert isinstance(rng_disponivel(), RngNumpy), (
        "numpy ausente: a simulação cairia no RngPadrao e produziria percentis "
        "diferentes dos de produção (emenda F01 — §6/M8-A1)."
    )


def test_F01_mesma_seed_reproduz_os_percentis() -> None:
    """M8-A1 dentro do mesmo backend — o contrato que o §6 escreve."""
    a, b = _simular(42), _simular(42)
    for campo in ("funil", "conversoes", "custo", "receita", "roas", "poder"):
        assert a.get(campo) == b.get(campo), f"{campo} variou entre execuções com a mesma seed"


def test_F01_seeds_diferentes_produzem_resultados_diferentes() -> None:
    """Guarda-corpo do teste acima: se tudo fosse constante, ele passaria à toa.

    Compara o resultado INTEIRO (menos o carimbo de execução): num volume grande os
    percentis de `conversoes` chegam a coincidir entre seeds por arredondamento — foi o
    que derrubou a primeira versão deste teste."""
    a, b = _simular(42), _simular(7)
    a.pop("executada_em", None)
    b.pop("executada_em", None)
    assert a != b, "seeds distintas produziram simulação idêntica — a seed não está sendo usada"
