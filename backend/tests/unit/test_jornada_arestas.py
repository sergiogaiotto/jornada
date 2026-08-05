"""Unit A13 (UAT com gpt-oss-120b real): o modelo emite arestas com aliases
`source`/`target` e às vezes sem `to` — o domínio normaliza os aliases, o
`jgc_validate` (§5.3) EXIGE `from`/`to` presentes e apontando para nós existentes
(mensagem clara alimenta o retry §7.3) e o taxímetro (A2) jamais estoura KeyError.
"""

from decimal import Decimal
from typing import Any

from domain.jornada import taximetro
from domain.jornada.validacao import normalizar_arestas, validar_grafo


def _grafo_minimo() -> dict[str, Any]:
    return {
        "jgcVersion": "1.0",
        "meta": {"osCodigo": "OS-X", "tenant": "t", "reentrada": "nao"},
        "nodes": [
            {"id": "n1", "type": "entrySource", "data": {"deRef": "DE", "modo": "fire_once"}},
            {"id": "n2", "type": "channel.email", "data": {"assetRef": "a", "optIn": True}},
            {"id": "n3", "type": "goal", "data": {"metrica": "conversion", "deRef": "DE_c"}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "n2", "cond": None},
            {"id": "e2", "from": "n2", "to": "n3", "cond": None},
        ],
    }


def test_normalizar_arestas_source_target() -> None:
    """Aliases viram o contrato §5.1 (`from`/`to`); contrato existente PREVALECE."""
    grafo = _grafo_minimo()
    grafo["edges"] = [
        {"id": "e1", "source": "n1", "target": "n2"},
        {"id": "e2", "from": "n2", "to": "n3", "source": "lixo"},  # from/to prevalecem
    ]
    normalizado = normalizar_arestas(grafo)
    assert normalizado["edges"][0] == {"id": "e1", "from": "n1", "to": "n2"}
    assert normalizado["edges"][1] == {"id": "e2", "from": "n2", "to": "n3"}
    assert validar_grafo(normalizado) == []  # grafo normalizado é válido (§5.3)
    # idempotente: grafo já no contrato passa intacto
    assert normalizar_arestas(normalizado)["edges"] == normalizado["edges"]


def test_validacao_exige_from_to_presentes_e_nos_existentes() -> None:
    """§5.3 (emenda A13): aresta sem `to` e aresta para nó fantasma → erro CLARO."""
    sem_to = _grafo_minimo()
    del sem_to["edges"][0]["to"]
    erros = validar_grafo(sem_to)
    assert any(e["regra"] == "estrutura" and "`to`" in e["mensagem"] for e in erros)

    fantasma = _grafo_minimo()
    fantasma["edges"][1]["to"] = "n99"
    erros = validar_grafo(fantasma)
    assert any(e["regra"] == "estrutura" and "n99" in e["mensagem"] for e in erros)


def test_taximetro_nao_estoura_keyerror_em_grafo_malformado() -> None:
    """A13: aresta sem `to`/`from` e nó sem id são IGNORADOS na conta — quem aponta o
    erro é o jgc_validate; o taxímetro nunca devolve 500 por KeyError bruto."""
    grafo = _grafo_minimo()
    del grafo["edges"][0]["to"]
    grafo["edges"].append({"id": "e3", "to": "n3"})  # sem from
    grafo["nodes"].append({"type": "wait", "data": {"duracao": "P1D"}})  # sem id
    total, memoria, avisos = taximetro.calcular(
        grafo, volume_entrada=1_000, tarifas={"email": Decimal("0.0018")}
    )
    assert total == Decimal("0.00")  # n2 não recebe volume — e nada explodiu
    assert [m["no"] for m in memoria] == ["n2"]
    assert avisos == []
