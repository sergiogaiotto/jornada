"""I02 (onda 5) — decisionSplit híbrido é RECUSADO: `roteamento_ambiguo` (§5.3).

O achado (CHANGELOG-SDD.md, "achado novo" do E05): a adjacência única (D07) SOMA
`edges` + `regras[].to` sem exclusão mútua. Um nó roteado das duas formas duplica a
saída — o taxímetro dividia o volume pelas saídas DUPLICADAS (braço repetido levava
2/3 em vez de 1/2 = +33%), o motor §6 idem, e o compilador emitia DOIS outcomes para
o mesmo destino no Journey Builder. A decisão registrada: recusar na validação; NUNCA
deduplicar mudo na adjacência (dedupe mudaria o payload compilado em silêncio).

INVERSÃO (verificada): remover o bloco `roteamento_ambiguo` de `_validar_semantica`
(backend/domain/jornada/validacao.py) deixa `test_I02_hibrido_no_mesmo_no_e_recusado`
vermelho — e `test_I02_a_duplicacao_existe_de_verdade` continua verde, porque ele
prova a DOENÇA (a adjacência mescla mesmo), não o remédio.
"""

from pathlib import Path
from typing import Any

from domain.jornada.adjacencia import saidas_do_grafo
from domain.jornada.validacao import validar_grafo

RAIZ = Path(__file__).resolve().parents[3]


def _grafo(no_decisao: dict[str, Any], edges_extras: list[dict[str, Any]]) -> dict[str, Any]:
    """entrada → decisionSplit d1 → {A, B}; as saídas do d1 vêm do caso de teste."""
    return {
        "jgcVersion": "1.0",
        "meta": {"osCodigo": "OS-I02", "tenant": "torre-movel", "reentrada": "nao"},
        "nodes": [
            {
                "id": "n1",
                "type": "entrySource",
                "data": {"deRef": "DE_e", "modo": "fire_once", "reentrada": "nao"},
            },
            no_decisao,
            {"id": "A", "type": "goal", "data": {"metrica": "conversion", "deRef": "DE_c"}},
            {"id": "B", "type": "exit", "data": {"motivo": "fora"}},
        ],
        "edges": [{"id": "e1", "from": "n1", "to": "d1", "cond": None}, *edges_extras],
    }


def _hibrido_assimetrico() -> dict[str, Any]:
    """As DUAS regras roteiam por `to` E uma aresta manual duplica o destino A —
    o caso assimétrico em que o desvio de volume é observável (A: 2/3 em vez de 1/2)."""
    return _grafo(
        {
            "id": "d1",
            "type": "decisionSplit",
            "data": {
                "regras": [
                    {"expr": "score > 90", "to": "A"},
                    {"expr": "senao", "to": "B"},
                ]
            },
        },
        [{"id": "e2", "from": "d1", "to": "A", "cond": None}],  # a aresta que o editor deixava
    )


def test_I02_a_duplicacao_existe_de_verdade() -> None:
    """A doença, documentada: a adjacência única MESCLA as duas formas — 3 saídas para
    2 braços lógicos. O taxímetro e o motor §6 dividem por `len(saidas)`: o braço
    duplicado (A) levaria 2/3 do volume em vez de 1/2 (+33,3%)."""
    saidas = saidas_do_grafo(_hibrido_assimetrico())["d1"]
    assert len(saidas) == 3  # 2 regras + 1 aresta manual
    assert [s["to"] for s in saidas].count("A") == 2  # o mesmo destino, duas vezes


def test_I02_hibrido_no_mesmo_no_e_recusado() -> None:
    erros = validar_grafo(_hibrido_assimetrico())
    ambiguos = [e for e in erros if e["regra"] == "roteamento_ambiguo"]
    assert len(ambiguos) == 1, erros
    assert ambiguos[0]["no"] == "d1"
    # mensagem PRESCRITIVA: o retry §7.3 precisa saber COMO consertar, não só que errou
    assert "mutuamente exclusivas" in ambiguos[0]["mensagem"]


def test_I02_regras_mistas_sem_aresta_tambem_sao_ambiguas() -> None:
    """Regra com `to` + regra SEM `to` no mesmo nó: a segunda não tem como rotear
    (a forma clássica exige aresta, que a forma nova proíbe) — ambíguo por construção."""
    grafo = _grafo(
        {
            "id": "d1",
            "type": "decisionSplit",
            "data": {"regras": [{"expr": "score > 90", "to": "A"}, {"id": "resto"}]},
        },
        [],
    )
    erros = validar_grafo(grafo)
    assert any(e["regra"] == "roteamento_ambiguo" and e["no"] == "d1" for e in erros), erros


def test_I02_as_duas_formas_puras_continuam_validas() -> None:
    """O remédio não pode matar as formas legais: nova (regras[].to, sem aresta) e
    clássica (regras {id, cond}, destino nas arestas) seguem passando."""
    nova = _grafo(
        {
            "id": "d1",
            "type": "decisionSplit",
            "data": {"regras": [{"expr": "score > 90", "to": "A"}, {"expr": "senao", "to": "B"}]},
        },
        [],
    )
    assert validar_grafo(nova) == []

    classica = _grafo(
        {
            "id": "d1",
            "type": "decisionSplit",
            "data": {"regras": [{"id": "vip", "cond": "score > 90"}, {"id": "resto"}]},
        },
        [
            {"id": "e2", "from": "d1", "to": "A", "cond": "vip"},
            {"id": "e3", "from": "d1", "to": "B", "cond": "resto"},
        ],
    )
    assert validar_grafo(classica) == []


def test_I02_regra_com_to_vazio_nao_e_regra_morta_silenciosa() -> None:
    """Auditoria da onda 5: `to: ""` satisfazia o `required` do schema (presença sem
    valor), o I02 a classificava como sem_to, a adjacência a ignorava — e a expr do
    usuário sumia do compilado com validar_grafo == []. Era o estado que o próprio
    dataDefault do catálogo fabricava. O minLength do schema agora recusa."""
    grafo = _grafo(
        {
            "id": "d1",
            "type": "decisionSplit",
            "data": {"regras": [{"expr": "score > 90", "to": ""}]},
        },
        [
            {"id": "e2", "from": "d1", "to": "A", "cond": None},
            {"id": "e3", "from": "d1", "to": "B", "cond": None},
        ],
    )
    erros = validar_grafo(grafo)
    # O `to` PRESENTE satisfaz o required do anyOf — quem recusa o vazio é o
    # minLength das properties do item (regra `valor_fora_da_faixa`), apontando d1.
    assert any(
        e["no"] == "d1" and e["regra"] == "valor_fora_da_faixa" and ".to" in e["mensagem"]
        for e in erros
    ), erros


def test_I02_braco_classico_morto_e_recusado() -> None:
    """Auditoria da onda 5 — o vizinho descoberto: regra {id} sem aresta com o cond
    correspondente não roteia ninguém (randomSplit e frequencySplit sempre tiveram o
    check análogo; o decisionSplit clássico nunca teve). INVERSÃO: reverter o bloco
    `elif not com_to` de _validar_semantica deixa este teste vermelho."""
    grafo = _grafo(
        {
            "id": "d1",
            "type": "decisionSplit",
            "data": {"regras": [{"id": "vip", "cond": "score > 90"}, {"id": "resto"}]},
        },
        [{"id": "e2", "from": "d1", "to": "A", "cond": "vip"}],  # "resto" sem aresta
    )
    grafo["nodes"] = [n for n in grafo["nodes"] if n["id"] != "B"]  # nada fica órfão
    erros = validar_grafo(grafo)
    assert any(
        e["no"] == "d1" and e["regra"] == "braco_sem_destino" and "resto" in e["mensagem"]
        for e in erros
    ), erros


def test_I02_espelho_no_lint_do_canvas_existe() -> None:
    """Guarda-corpo do espelho (mesmo padrão do bloco IV do F04): o lint local
    (frontend/src/canvas/lint.ts) precisa carregar a MESMA regra, senão o painel de
    problemas só acusa depois do save (origem "servidor") — e o editor precisa recusar
    a conexão que cria o híbrido (EditorJornada.tsx). Grep, não execução: o frontend
    não tem harness de teste (e2e Playwright segue inexistente — HANDOFF §8.3)."""
    lint = (RAIZ / "frontend" / "src" / "canvas" / "lint.ts").read_text(encoding="utf-8")
    assert "roteamento_ambiguo" in lint, (
        "frontend/src/canvas/lint.ts perdeu a regra `roteamento_ambiguo` — o espelho "
        "do §5.3 no painel de problemas do canvas. Reaplique o bloco do decisionSplit."
    )
    editor = (RAIZ / "frontend" / "src" / "canvas" / "EditorJornada.tsx").read_text(
        encoding="utf-8"
    )
    assert "regras.some((r) => r.to)" in editor, (
        "EditorJornada.tsx perdeu o guarda do aoConectar — sem ele a UI volta a criar "
        "a aresta manual sobre decisionSplit roteado por regras[].to (o híbrido nasce lá)."
    )
