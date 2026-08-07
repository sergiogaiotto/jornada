"""I01 (onda 5) — o jgc.schema.json passa a valer por VALOR, não só por presença.

É o P2 do UAT #5 ("validação por presença, nunca por valor") fechado: até aqui o
schema — que o §5 chama de fonte da verdade — era lido só para o enum de tipos e os
`required` de `$defs.data.*`. Toda restrição de valor era decorativa, e a VPS provou:
201 para STO de -72h, metrica "telepatia" e throttle -5000; `throttlePorHora: "mil"`
salvava e derrubava o simulador com 500 (jornada 34309e21). Estes aceites usam
EXATAMENTE esses exemplos reais.

INVERSÃO (verificada): remover a linha `erros.extend(_erros_do_schema(grafo))` de
`_validar_estrutura` (backend/domain/jornada/validacao.py) deixa este arquivo inteiro
vermelho — menos os testes das formas D05/D07, que provam a EMENDA do schema e ficam
verdes com ou sem a camada (são o outro lado: o schema emendado não pode rejeitar o
que o §5.3 legalizou).
"""

import uuid
from typing import Any

from fastapi import FastAPI
from starlette.testclient import TestClient

from adapters.llm.fake import LLMFake
from app.errors import PROBLEM_CONTENT_TYPE
from domain.audiencia.modelos import Segmento
from domain.jornada.validacao import validar_grafo

TENANT = "torre-movel"


def _h(token: str = "dev-analista") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _grafo_base() -> dict[str, Any]:
    """JGC §5 mínimo e CONFORME: entrada → sto → e-mail → goal."""
    return {
        "jgcVersion": "1.0",
        "meta": {"osCodigo": "OS-I01", "tenant": TENANT, "reentrada": "nao"},
        "nodes": [
            {
                "id": "n1",
                "type": "entrySource",
                "data": {"deRef": "DE_entrada", "modo": "fire_once", "reentrada": "nao"},
            },
            {"id": "n2", "type": "sto", "data": {"janelaHoras": 24, "fallback": "09:00"}},
            {
                "id": "n3",
                "type": "channel.email",
                "data": {"assetRef": "asset-1", "optIn": True, "throttlePorHora": 1000},
            },
            {"id": "n4", "type": "goal", "data": {"metrica": "conversion", "deRef": "DE_conv"}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "n2", "cond": None},
            {"id": "e2", "from": "n2", "to": "n3", "cond": None},
            {"id": "e3", "from": "n3", "to": "n4", "cond": None},
        ],
    }


def _erros_do_no(erros: list[dict[str, Any]], no: str) -> list[dict[str, Any]]:
    return [e for e in erros if e["no"] == no]


def test_I01_grafo_conforme_continua_valido() -> None:
    assert validar_grafo(_grafo_base()) == []


def test_I01_janela_sto_negativa_e_recusada_apontando_o_no() -> None:
    """O caso literal da VPS: STO de -72h recebia 201 e ia para o export SFMC."""
    grafo = _grafo_base()
    grafo["nodes"][1]["data"]["janelaHoras"] = -72
    erros = _erros_do_no(validar_grafo(grafo), "n2")
    assert any(e["regra"] == "valor_fora_da_faixa" for e in erros), erros
    assert any("janelaHoras" in e["mensagem"] for e in erros)


def test_I01_metrica_fora_do_enum_e_recusada() -> None:
    """O caso literal da VPS: engagementSplit com metrica "telepatia" recebia 201."""
    grafo = _grafo_base()
    grafo["nodes"][1] = {
        "id": "n2",
        "type": "engagementSplit",
        "data": {"metrica": "telepatia", "janela": "P7D"},
    }
    grafo["nodes"].append({"id": "n5", "type": "exit", "data": {"motivo": "nao_engajou"}})
    grafo["edges"] = [
        {"id": "e1", "from": "n1", "to": "n2", "cond": None},
        {"id": "e2", "from": "n2", "to": "n3", "cond": "sim"},
        {"id": "e3", "from": "n2", "to": "n5", "cond": "nao"},
        {"id": "e4", "from": "n3", "to": "n4", "cond": None},
    ]
    erros = _erros_do_no(validar_grafo(grafo), "n2")
    assert any(e["regra"] == "valor_fora_do_enum" for e in erros), erros
    # e a MESMA forma com metrica válida passa — o teste enxerga o valor, não a forma
    grafo["nodes"][1]["data"]["metrica"] = "open"
    assert validar_grafo(grafo) == []


def test_I01_pct_como_string_e_tipo_invalido_nao_500() -> None:
    """`pct: "cinquenta"` antes ESTOURAVA a semântica (`float("cinquenta")` → 500 no
    save). Agora a camada de valor recusa ANTES, com o nó apontado — a semântica só
    roda em grafo estruturalmente são."""
    grafo = _grafo_base()
    grafo["nodes"][1] = {
        "id": "n2",
        "type": "randomSplit",
        "data": {"braços": [{"id": "a", "pct": "cinquenta"}, {"id": "b", "pct": 50}]},
    }
    grafo["nodes"].append({"id": "n5", "type": "exit", "data": {"motivo": "b"}})
    grafo["edges"] = [
        {"id": "e1", "from": "n1", "to": "n2", "cond": None},
        {"id": "e2", "from": "n2", "to": "n3", "cond": "a"},
        {"id": "e3", "from": "n2", "to": "n5", "cond": "b"},
        {"id": "e4", "from": "n3", "to": "n4", "cond": None},
    ]
    erros = _erros_do_no(validar_grafo(grafo), "n2")  # não pode levantar exceção
    assert any(e["regra"] == "tipo_invalido" for e in erros), erros


def test_I01_throttle_como_string_e_tipo_invalido() -> None:
    """`throttlePorHora: "mil"` salvava com 201 e derrubava o simulador com 500 — a
    jornada 34309e21 da VPS ficou travada assim."""
    grafo = _grafo_base()
    grafo["nodes"][2]["data"]["throttlePorHora"] = "mil"
    erros = _erros_do_no(validar_grafo(grafo), "n3")
    assert any(e["regra"] == "tipo_invalido" for e in erros), erros


def test_I01_throttle_negativo_e_fora_da_faixa() -> None:
    """O quarto exemplo literal da VPS: throttle -5000 recebia 201 e ia ao export."""
    grafo = _grafo_base()
    grafo["nodes"][2]["data"]["throttlePorHora"] = -5000
    erros = _erros_do_no(validar_grafo(grafo), "n3")
    assert any(e["regra"] == "valor_fora_da_faixa" for e in erros), erros


def test_I01_chave_desconhecida_no_topo_e_recusada() -> None:
    """`additionalProperties: false` da raiz passa a valer — chave fora do contrato
    §5.1 é apontada por NOME (o retry §7.3 precisa saber O QUE remover)."""
    grafo = _grafo_base()
    grafo["confianca"] = 0.98  # chave que um LLM inventa no topo
    erros = validar_grafo(grafo)
    assert any(
        e["regra"] == "campo_desconhecido" and "confianca" in e["mensagem"] for e in erros
    ), erros


def test_I01_chave_desconhecida_dentro_de_data_tambem_e_recusada() -> None:
    """Auditoria da onda 5: o fechamento valia SÓ na raiz — um typo de campo
    (`throtlePorHora: -5000`) passava limpo e o cap da política não o via, recriando a
    doença da VPS que a onda declara fechada. `additionalProperties: false` agora
    fecha meta, node, edge e todos os `data.*`."""
    typo = _grafo_base()
    typo["nodes"][2]["data"] = {"assetRef": "asset-1", "optIn": True, "throtlePorHora": -5000}
    erros = _erros_do_no(validar_grafo(typo), "n3")
    assert any(
        e["regra"] == "campo_desconhecido" and "throtlePorHora" in e["mensagem"] for e in erros
    ), erros

    no_no = _grafo_base()
    no_no["nodes"][1]["confianca"] = 0.9  # chave extra no PRÓPRIO nó
    erros = _erros_do_no(validar_grafo(no_no), "n2")
    assert any(e["regra"] == "campo_desconhecido" for e in erros), erros


def test_I01_meta_null_e_jgcversion_null_nao_atravessam() -> None:
    """Auditoria da onda 5: `meta: null` e `jgcVersion: null` PRESENTES atravessavam
    as duas camadas — o filtro do schema assumia cobertura artesanal, e a artesanal
    tolerava null (`elif meta is not None` / `not in (None, "1.0")`). O `setdefault`
    do save não conserta chave presente, então null PERSISTIA. Alcançável hoje: o
    ensaiar_grafo do M11 valida o grafo CRU, sem `_normalizar_meta`."""
    com_meta_null = _grafo_base()
    com_meta_null["meta"] = None
    erros = validar_grafo(com_meta_null)
    assert any("meta deve ser objeto" in e["mensagem"] for e in erros), erros

    com_versao_null = _grafo_base()
    com_versao_null["jgcVersion"] = None
    erros = validar_grafo(com_versao_null)
    assert any("jgcVersion" in e["mensagem"] for e in erros), erros


def test_I01_erro_de_meta_nao_some_atras_de_erros_de_aresta() -> None:
    """Auditoria da onda 5: o teto de erros era por `no`, e raiz/meta/edges dividiam o
    balde None — 3 erros de aresta escondiam o erro de meta da MESMA resposta. O teto
    agora é por LOCALIZAÇÃO: cada aresta, o meta e a raiz contam separado."""
    grafo = _grafo_base()
    for aresta in grafo["edges"]:
        aresta["cond"] = 7  # três erros de tipo em edges (cond numérico)
    grafo["meta"]["quietHours"] = {"inicio": 20, "fim": "08:00"}  # erro de meta
    erros = validar_grafo(grafo)
    assert any("quietHours" in e["mensagem"] for e in erros), erros


def test_I01_id_de_aresta_duplicado_e_recusado() -> None:
    """Auditoria da onda 5: duas arestas de mesmo id duplicam a saída na adjacência
    (a família do +33% do I02) e o diff por id as colapsa. O I03 ordena edges por id
    assumindo unicidade — agora ela é garantida na estrutura."""
    grafo = _grafo_base()
    grafo["edges"].append({"id": "e2", "from": "n2", "to": "n4", "cond": None})
    erros = validar_grafo(grafo)
    assert any("Id de aresta duplicado" in e["mensagem"] for e in erros), erros


def test_I01_required_profundo_braco_sem_pct() -> None:
    """Os `required` PROFUNDOS (braço sem `pct`) nunca tiveram checagem artesanal —
    é a camada do schema quem os enxerga."""
    grafo = _grafo_base()
    grafo["nodes"][1] = {
        "id": "n2",
        "type": "randomSplit",
        "data": {"braços": [{"id": "a"}, {"id": "b", "pct": 100}]},
    }
    grafo["nodes"].append({"id": "n5", "type": "exit", "data": {"motivo": "b"}})
    grafo["edges"] = [
        {"id": "e1", "from": "n1", "to": "n2", "cond": None},
        {"id": "e2", "from": "n2", "to": "n3", "cond": "a"},
        {"id": "e3", "from": "n2", "to": "n5", "cond": "b"},
        {"id": "e4", "from": "n3", "to": "n4", "cond": None},
    ]
    erros = _erros_do_no(validar_grafo(grafo), "n2")
    assert any(e["regra"] == "campo_obrigatorio" and "pct" in e["mensagem"] for e in erros), erros


def test_I01_formas_D05_D07_continuam_validas_com_o_schema_emendado() -> None:
    """A emenda do schema veio ANTES da camada ligar: decisionSplit clássico
    ({id, cond}, destino na aresta), classes fora do enum antigo e fonte != governor
    são formas que o §5.3 legalizou (D05/D07) e grafos REAIS usam — o schema não pode
    rejeitá-las. Reverter a emenda (required [expr, to] etc.) deixa ESTE teste vermelho."""
    grafo = _grafo_base()
    grafo["nodes"][1] = {
        "id": "n2",
        "type": "decisionSplit",
        "data": {"regras": [{"id": "vip", "cond": "score > 90"}, {"id": "resto"}]},
    }
    grafo["nodes"].append({"id": "n5", "type": "exit", "data": {"motivo": "resto"}})
    grafo["edges"] = [
        {"id": "e1", "from": "n1", "to": "n2", "cond": None},
        {"id": "e2", "from": "n2", "to": "n3", "cond": "vip"},
        {"id": "e3", "from": "n2", "to": "n5", "cond": "resto"},
        {"id": "e4", "from": "n3", "to": "n4", "cond": None},
    ]
    assert validar_grafo(grafo) == []

    freq = _grafo_base()
    freq["nodes"][1] = {
        "id": "n2",
        "type": "frequencySplit",
        "data": {
            "classes": [{"id": "baixa", "max": 2}, "alta"],  # objeto D05 + string livre
            "fonte": "DE_freq",  # o grafo v5 REAL em produção usa esta fonte
        },
    }
    freq["nodes"].append({"id": "n5", "type": "exit", "data": {"motivo": "alta"}})
    freq["edges"] = [
        {"id": "e1", "from": "n1", "to": "n2", "cond": None},
        {"id": "e2", "from": "n2", "to": "n3", "cond": "baixa"},
        {"id": "e3", "from": "n2", "to": "n5", "cond": "alta"},
        {"id": "e4", "from": "n3", "to": "n4", "cond": None},
    ]
    assert validar_grafo(freq) == []


def test_I01_http_save_recusa_valor_torto_com_422_apontando_o_no(
    client: TestClient, app: FastAPI
) -> None:
    """Ponta a ponta pela rota do save (§8-M7-A1): o mesmo STO de -72h que a VPS
    aceitou com 201 agora volta 422 problem+json com o nó e a regra."""
    resposta = client.post(
        "/api/v1/os",
        json={"nome": "I01 valor governa", "tshirt": "M", "briefing": {}},
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    os_ = resposta.json()
    app.state.repositorio_os.adicionar_segmento(
        Segmento(
            id=uuid.uuid4(),
            os_id=uuid.UUID(os_["id"]),
            origem="estudio_sql",
            contagem_bruta=1000,
            contagem_liquida=1000,
        )
    )
    app.state.llm = LLMFake(disponivel=False)  # criar_manual é SEM LLM (§10.6)

    grafo = _grafo_base()
    grafo["meta"]["osCodigo"] = os_["codigo"]
    grafo["nodes"][1]["data"]["janelaHoras"] = -72
    recusado = client.post(f"/api/v1/os/{os_['id']}/jornada", json={"grafo": grafo}, headers=_h())
    assert recusado.status_code == 422, recusado.text
    assert recusado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    erros = recusado.json()["erros"]
    assert any(e["no"] == "n2" and e["regra"] == "valor_fora_da_faixa" for e in erros), erros
    assert client.get(f"/api/v1/os/{os_['id']}/jornadas", headers=_h()).json() == []
