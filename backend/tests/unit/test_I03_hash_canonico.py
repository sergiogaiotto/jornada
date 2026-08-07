"""I03 (onda 5) — o hash do JGC é insensível à ordem de `nodes`/`edges`.

O achado: `canonicalizar` (RFC 8785) ordena CHAVES, não arrays — e `nodes`/`edges` são
CONJUNTOS no JGC (o grafo é definido por ids e refs, não por posição). O mesmo grafo
lógico permutado produzia hash diferente → externalKey diferente → o plan do M9
marcava destruir/recriar TODOS os recursos SFMC ("reinicia contatos em espera") para
um grafo IDÊNTICO. Nenhum teste cobria isso — o gap era o próprio achado.

INVERSÃO (verificada): remover o `normalizar_grafo(...)` de dentro de `hash_jgc`
(backend/domain/jornada/canonico.py) deixa `test_I03_hash_igual_sob_permutacao`
vermelho; remover o `normalizar_grafo` do `_normalizar_meta` (jornada_service) deixa
`test_I03_persistencia_canonica_via_http` vermelho — a auditoria da onda flagrou que
a primeira versão desta docstring apontava para um aceite que NÃO existia (o teste
que passa por não enxergar, na sua forma mais literal), e o aceite foi escrito.
"""

import copy
from typing import Any

from fastapi import FastAPI
from starlette.testclient import TestClient

from domain.jornada.canonico import hash_jgc, normalizar_grafo
from tests.contract.util_golden import HASH_GOLDEN, JGC_GOLDEN, arquivos_golden


def _permutado(grafo: dict[str, Any]) -> dict[str, Any]:
    """O mesmo grafo lógico com as listas-conjunto EMBARALHADAS (reversão basta:
    qualquer permutação ≠ identidade prova a classe)."""
    torto = copy.deepcopy(grafo)
    torto["nodes"] = list(reversed(torto["nodes"]))
    torto["edges"] = list(reversed(torto["edges"]))
    return torto


def test_I03_hash_igual_sob_permutacao() -> None:
    assert hash_jgc(_permutado(JGC_GOLDEN)) == hash_jgc(JGC_GOLDEN)


def test_I03_normalizar_ordena_topo_e_nao_toca_data() -> None:
    """`data.*` NUNCA é ordenado: as `regras` do decisionSplit têm precedência de
    avaliação (o `senao` do n7 é a última por contrato) — ordenar mudaria semântica
    e payload compilado."""
    canonico = normalizar_grafo(_permutado(JGC_GOLDEN))
    assert [n["id"] for n in canonico["nodes"]] == [f"n{i}" for i in range(1, 9)]
    assert [a["id"] for a in canonico["edges"]] == [f"e{i}" for i in range(1, 8)]
    n7 = next(n for n in canonico["nodes"] if n["id"] == "n7")
    assert n7["data"]["regras"][-1]["expr"] == "senao"  # precedência intacta


def test_I03_golden_ja_e_canonico_hash_e_bytes_intactos() -> None:
    """A regra de ordenação foi escolhida por `id` EXATAMENTE para o JGC de referência
    (n1..n8, e1..e7) já estar canônico: HASH_GOLDEN e os golden files do M9-A2 não
    mudam um byte. Se este teste quebrar, alguém mudou a regra de ordenação — isso é
    mudança de CONTRATO (regenerar goldens + emenda no CHANGELOG, ver util_golden)."""
    assert normalizar_grafo(JGC_GOLDEN) == JGC_GOLDEN
    assert hash_jgc(JGC_GOLDEN) == HASH_GOLDEN


def test_I03_compilacao_identica_para_grafos_permutados_normalizados() -> None:
    """Não basta o hash coincidir: dois grafos de MESMO hash compilando em ordens
    diferentes gerariam falso drift e falso `alterar` destrutivo no plan. Com a
    normalização na persistência, o compilado é idêntico byte a byte."""
    import tests.contract.util_golden as golden

    original = arquivos_golden()
    permutado_normalizado = normalizar_grafo(_permutado(JGC_GOLDEN))
    assert permutado_normalizado == JGC_GOLDEN  # mesma estrutura ⇒ mesmos bytes
    recompilado = {
        golden.nome_arquivo(item): golden.serializar(item)
        for item in golden.compilar_recursos(permutado_normalizado, HASH_GOLDEN)
    }
    assert recompilado == original


def test_I03_defensivo_lista_torta_fica_intacta() -> None:
    """Contrato defensivo (mesmo da adjacência D07): item sem `id`/não-objeto não
    estoura nem some — a lista fica como veio e quem acusa é o validar_grafo."""
    torto = {"nodes": [{"type": "wait"}, {"id": "n1"}], "edges": "nao-e-lista"}
    assert normalizar_grafo(torto) == torto
    assert normalizar_grafo("nao-e-grafo") == "nao-e-grafo"  # type: ignore[arg-type]


def test_I03_persistencia_canonica_via_http(client: TestClient, app: FastAPI) -> None:
    """A metade PERSISTÊNCIA da emenda (auditoria da onda 5): salvar um grafo com as
    listas embaralhadas tem de devolver — e persistir — nodes/edges em ordem canônica.
    Sem isso, dois grafos de MESMO hash compilariam activities em ordens diferentes
    (falso drift, falso `alterar` destrutivo), e nada na suíte denunciava.

    INVERSÃO: trocar `return normalizar_grafo(grafo)` por `return grafo` no
    `_normalizar_meta` de jornada_service deixa este teste vermelho."""
    from tests.acceptance.test_M7 import _criar_os_com_segmento, _grafo, _h

    os_ = _criar_os_com_segmento(client, app)
    embaralhado = _grafo(os_["codigo"])
    embaralhado["nodes"] = list(reversed(embaralhado["nodes"]))
    embaralhado["edges"] = list(reversed(embaralhado["edges"]))
    criada = client.post(
        f"/api/v1/os/{os_['id']}/jornada", json={"grafo": embaralhado}, headers=_h()
    )
    assert criada.status_code == 201, criada.text
    persistido = criada.json()["jornada"]["grafo"]
    assert [n["id"] for n in persistido["nodes"]] == sorted(n["id"] for n in persistido["nodes"]), (
        "nodes devem persistir em ordem canônica (por id)"
    )
    assert [a["id"] for a in persistido["edges"]] == sorted(a["id"] for a in persistido["edges"]), (
        "edges devem persistir em ordem canônica (por id)"
    )
