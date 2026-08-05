"""Aceites do módulo M7 · Twin Canvas T7 (SDD §5, §8-M7) — IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker e SEM REDE: o flow usa o LLMFake (§1.3.5 — único
adapter de LLM permitido em teste); validação §5.3, taxímetro (A2) e sfmc-preview são
código determinístico. O segmento recontado (volume do taxímetro) é semeado direto no
repositório em memória (`app.state.repositorio_os` — padrão dos aceites M8); o
experimento do A3 nasce pelo próprio `POST /experimentos` (M8 parte 2 — já travado).
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from lxml import etree

from adapters.llm.fake import LLMFake
from app.errors import PROBLEM_CONTENT_TYPE
from domain.audiencia.modelos import Segmento
from domain.jornada.sfmc_preview import external_key

XSD_PATH = Path(__file__).resolve().parents[2] / "domain" / "jornada" / "journey_export.xsd"

TENANT = "torre-movel"
VOLUME_LIQUIDO = 50_000


def _h(token: str = "dev-analista") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _grafo(os_codigo: str) -> dict[str, Any]:
    """JGC §5 válido: entrada → randomSplit 90/10 (holdout) → e-mail → whatsapp → goal;
    braço holdout → exit. Volumes/tarifas §11.4 dão o valor EXATO do taxímetro (A2)."""
    return {
        "jgcVersion": "1.0",
        "meta": {
            "osCodigo": os_codigo,
            "tenant": TENANT,
            "reentrada": "nao",
            "quietHours": {"inicio": "20:00", "fim": "08:00"},
        },
        "nodes": [
            {
                "id": "n1",
                "type": "entrySource",
                "data": {"deRef": "DE_entrada", "modo": "fire_once", "reentrada": "nao"},
            },
            {
                "id": "n2",
                "type": "randomSplit",
                "data": {"braços": [{"id": "tratado", "pct": 90}, {"id": "holdout", "pct": 10}]},
            },
            {
                "id": "n3",
                "type": "channel.email",
                "data": {"assetRef": "asset-email-1", "optIn": True, "throttlePorHora": 25_000},
            },
            {
                "id": "n4",
                "type": "channel.whatsapp",
                "data": {"assetRef": "asset-wpp-1", "optIn": True},
            },
            {"id": "n5", "type": "goal", "data": {"metrica": "conversion", "deRef": "DE_conv"}},
            {"id": "n6", "type": "exit", "data": {"motivo": "holdout"}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "n2", "cond": None},
            {"id": "e2", "from": "n2", "to": "n3", "cond": "tratado"},
            {"id": "e3", "from": "n2", "to": "n6", "cond": "holdout"},
            {"id": "e4", "from": "n3", "to": "n4", "cond": None},
            {"id": "e5", "from": "n4", "to": "n5", "cond": None},
        ],
    }


def _resposta_flow(grafo: dict[str, Any]) -> str:
    """Resposta enlatada do flow no contrato §7.2 (JSON com grafo+premissas+resumo)."""
    return json.dumps(
        {
            "grafo": grafo,
            "premissas": ["Janela da oferta de 30 dias", "Opt-in vigente por canal"],
            "resumo": "Entrada única, holdout de 10%, e-mail seguido de WhatsApp.",
        },
        ensure_ascii=False,
    )


def _criar_os_com_segmento(client: TestClient, app: FastAPI) -> dict[str, Any]:
    """OS via API + segmento recontado (volume do taxímetro) direto no repo (M5)."""
    resposta = client.post(
        "/api/v1/os",
        json={
            "nome": "Upgrade Pós-Pago 5G",
            "tshirt": "G",
            "briefing": {"publico": {"valor": "Pós-pago sem 5G", "inferido": False}},
        },
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    os_ = resposta.json()
    app.state.repositorio_os.adicionar_segmento(
        Segmento(
            id=uuid.uuid4(),
            os_id=uuid.UUID(os_["id"]),
            origem="estudio_sql",
            contagem_bruta=61_000,
            contagem_liquida=VOLUME_LIQUIDO,
            volume_abordagem={"email": {"n": VOLUME_LIQUIDO, "pct": 100.0}},
        )
    )
    return os_


def _gerar_jornada(client: TestClient, app: FastAPI) -> tuple[dict[str, Any], dict[str, Any]]:
    """OS + segmento + `POST /os/{id}/jornada/gerar` com o flow fake → corpo da resposta."""
    os_ = _criar_os_com_segmento(client, app)
    app.state.llm = LLMFake(resposta=_resposta_flow(_grafo(os_["codigo"])))
    resposta = client.post(f"/api/v1/os/{os_['id']}/jornada/gerar", headers=_h())
    assert resposta.status_code == 201, resposta.text
    return os_, resposta.json()


# ---------------------------------------------------------------------- Aceites §8-M7


def test_M7_A1(client: TestClient, app: FastAPI) -> None:
    """A1: grafo com braço órfão → 422 com apontamento do nó (problem+json, `erros[]`)."""
    _, corpo = _gerar_jornada(client, app)
    jornada = corpo["jornada"]

    # braço `holdout` do randomSplit n2 fica SEM aresta de destino (braço órfão §5.3)
    grafo = jornada["grafo"]
    grafo["edges"] = [e for e in grafo["edges"] if e["id"] != "e3"]
    grafo["nodes"] = [n for n in grafo["nodes"] if n["id"] != "n6"]
    resposta = client.put(
        f"/api/v1/jornadas/{jornada['id']}/grafo", json={"grafo": grafo}, headers=_h()
    )
    assert resposta.status_code == 422, resposta.text
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    erros = resposta.json()["erros"]
    assert any(e["no"] == "n2" and e["regra"] == "braco_sem_destino" for e in erros)

    # nada foi salvo: o grafo persistido segue com o braço holdout intacto
    persistida = app.state.repositorio_os.obter_jornada(uuid.UUID(jornada["id"]))
    assert any(e["id"] == "e3" for e in persistida.grafo["edges"])

    # o mesmo guarda-corpo vale na GERAÇÃO: flow que propõe braço órfão → 422 (§1.3.5)
    os2 = _criar_os_com_segmento(client, app)
    grafo_orfao = _grafo(os2["codigo"])
    grafo_orfao["edges"] = [e for e in grafo_orfao["edges"] if e["id"] != "e3"]
    app.state.llm = LLMFake(resposta=_resposta_flow(grafo_orfao))
    gerar = client.post(f"/api/v1/os/{os2['id']}/jornada/gerar", headers=_h())
    assert gerar.status_code == 422
    assert any(e["regra"] == "braco_sem_destino" for e in gerar.json()["erros"])


def test_M7_A2(client: TestClient, app: FastAPI) -> None:
    """A2: taxímetro = Σ(volume esperado × tarifa vigente) — fixture bate valor EXATO.

    50.000 líquidos × 90% = 45.000 no braço tratado; e-mail 0,0018 + whatsapp 0,3597
    (§11.4) ⇒ 45.000×0,0018 + 45.000×0,3597 = 81,00 + 16.186,50 = R$ 16.267,50.
    """
    _, corpo = _gerar_jornada(client, app)
    assert corpo["jornada"]["custo_projetado"] == 16_267.50
    assert corpo["taximetro"]["custo_projetado"] == 16_267.50
    memoria = {m["no"]: m for m in corpo["taximetro"]["memoria"]}
    assert memoria["n3"] == {
        "no": "n3",
        "canal": "email",
        "volume": 45_000,
        "tarifa": "0.0018",
        "custo": "81.00",
    }
    assert memoria["n4"]["custo"] == "16186.50"
    assert corpo["taximetro"]["avisos"] == []

    # PUT recalcula (§8-M7): split 80/20 ⇒ 40.000×(0,0018+0,3597) = R$ 14.460,00
    grafo = corpo["jornada"]["grafo"]
    for no in grafo["nodes"]:
        if no["id"] == "n2":
            no["data"]["braços"] = [{"id": "tratado", "pct": 80}, {"id": "holdout", "pct": 20}]
    salvo = client.put(
        f"/api/v1/jornadas/{corpo['jornada']['id']}/grafo", json={"grafo": grafo}, headers=_h()
    )
    assert salvo.status_code == 200, salvo.text
    assert salvo.json()["jornada"]["custo_projetado"] == 14_460.00


def test_M7_A3(client: TestClient, app: FastAPI) -> None:
    """A3: `reentrada=qualquer_momento` + experimento travado → 422 (contrato de
    re-entrada §5.3); o pré-registro do M8 nasce TRAVADO (anti-p-hacking)."""
    os_, corpo = _gerar_jornada(client, app)
    jornada = corpo["jornada"]
    pre_registro = client.post(
        "/api/v1/experimentos",
        json={"os_id": os_["id"], "mde_pp": 1.0, "janela_dias": 14},
        headers=_h(),
    )
    assert pre_registro.status_code == 201, pre_registro.text
    assert pre_registro.json()["experimento"]["travado_em"]  # travado desde o registro

    grafo = jornada["grafo"]
    grafo["meta"]["reentrada"] = "qualquer_momento"
    for no in grafo["nodes"]:
        if no["type"] == "entrySource":
            no["data"]["reentrada"] = "qualquer_momento"
    resposta = client.put(
        f"/api/v1/jornadas/{jornada['id']}/grafo", json={"grafo": grafo}, headers=_h()
    )
    assert resposta.status_code == 422, resposta.text
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    erros = resposta.json()["erros"]
    assert any(e["regra"] == "reentrada_com_experimento" for e in erros)
    assert any(e["no"] == "n1" for e in erros)  # apontamento da entrada

    # com reentrada=nao o mesmo grafo (com holdout) segue aceito sob experimento travado
    grafo["meta"]["reentrada"] = "nao"
    for no in grafo["nodes"]:
        if no["type"] == "entrySource":
            no["data"]["reentrada"] = "nao"
    assert (
        client.put(
            f"/api/v1/jornadas/{jornada['id']}/grafo", json={"grafo": grafo}, headers=_h()
        ).status_code
        == 200
    )


# ------------------------------------------------- Contrato das demais rotas §8-M7


def test_M7_ajustar_propoe_diff_sem_aplicar(client: TestClient, app: FastAPI) -> None:
    """`POST /jornadas/{id}/ajustar`: texto livre → diff proposto; NUNCA aplica direto
    (aplicar = PUT humano do grafo proposto — §1.1.3)."""
    os_, corpo = _gerar_jornada(client, app)
    jornada = corpo["jornada"]

    proposto = _grafo(os_["codigo"])
    for no in proposto["nodes"]:
        if no["id"] == "n2":
            no["data"]["braços"] = [{"id": "tratado", "pct": 80}, {"id": "holdout", "pct": 20}]
    app.state.llm = LLMFake(resposta=_resposta_flow(proposto))

    resposta = client.post(
        f"/api/v1/jornadas/{jornada['id']}/ajustar",
        json={"instrucoes": "aumente o holdout para 20%"},
        headers=_h(),
    )
    assert resposta.status_code == 200, resposta.text
    proposta = resposta.json()
    assert proposta["aplicado"] is False and proposta["via_ai"] is True
    assert proposta["diff"]["nodes"]["alterados"] == ["n2"]
    assert proposta["diff"]["nodes"]["adicionados"] == []
    assert proposta["valido"] is True and proposta["erros"] == []
    assert proposta["custo_projetado_atual"] == 16_267.50
    assert proposta["custo_projetado_proposto"] == 14_460.00

    # o twin NÃO mudou: grafo e taxímetro persistidos seguem os da geração
    persistida = app.state.repositorio_os.obter_jornada(uuid.UUID(jornada["id"]))
    assert persistida.grafo == jornada["grafo"]
    assert persistida.custo_projetado == 16_267.50


def test_M7_sfmc_preview_e_via_ai(client: TestClient, app: FastAPI) -> None:
    """`GET .../sfmc-preview`: payload determinístico + externalKey idempotente
    `jrn-{hash[0:12]}-{noId}` (§5.4); geração registra ledger via_ai (§4.1)."""
    _, corpo = _gerar_jornada(client, app)
    jornada = corpo["jornada"]

    preview = client.get(f"/api/v1/jornadas/{jornada['id']}/no/n3/sfmc-preview", headers=_h())
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["externalKey"] == f"jrn-{jornada['hash'][:12]}-n3"
    assert payload["tipoSfmc"] == "emailSend" and payload["compilavel"] is True
    assert payload["payload"]["outcomes"] == [{"id": "e4", "to": "n4", "cond": None}]

    # nó inexistente → 404 problem+json
    ausente = client.get(f"/api/v1/jornadas/{jornada['id']}/no/nx/sfmc-preview", headers=_h())
    assert ausente.status_code == 404
    assert ausente.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    # ledger da geração: invocacao via_ai + evento agent.invoked (§4.1/§2.3)
    repo = app.state.repositorio_os
    assert any(str(i.id) == corpo["invocacao_id"] for i in repo.listar_invocacoes(TENANT))
    assert repo.listar_eventos(os_id=uuid.UUID(jornada["os_id"]), tipo="jornada.versao_criada")


def test_M7_arestas_source_target_normalizadas(client: TestClient, app: FastAPI) -> None:
    """A13 (UAT com o 120b real): o modelo gera arestas com aliases `source`/`target`
    — gerar e PUT normalizam para `from`/`to` ANTES de validar; o grafo persistido
    fica no contrato §5.1 (hash canônico estável)."""
    os_ = _criar_os_com_segmento(client, app)
    grafo_alias = _grafo(os_["codigo"])
    grafo_alias["edges"] = [
        {"id": a["id"], "source": a["from"], "target": a["to"], "cond": a["cond"]}
        for a in grafo_alias["edges"]
    ]
    app.state.llm = LLMFake(resposta=_resposta_flow(grafo_alias))
    gerada = client.post(f"/api/v1/os/{os_['id']}/jornada/gerar", headers=_h())
    assert gerada.status_code == 201, gerada.text
    persistido = gerada.json()["jornada"]["grafo"]
    assert all("from" in a and "to" in a for a in persistido["edges"])
    assert all("source" not in a and "target" not in a for a in persistido["edges"])
    # taxímetro calculado normalmente sobre o grafo normalizado (A2 — sem KeyError)
    assert gerada.json()["jornada"]["custo_projetado"] == 16_267.50

    # PUT com aliases também é aceito e normalizado (mesma borda §5.1)
    jornada_id = gerada.json()["jornada"]["id"]
    salvo = client.put(
        f"/api/v1/jornadas/{jornada_id}/grafo", json={"grafo": grafo_alias}, headers=_h()
    )
    assert salvo.status_code == 200, salvo.text
    assert all("from" in a and "to" in a for a in salvo.json()["jornada"]["grafo"]["edges"])


def test_M7_aresta_sem_to_e_no_inexistente_422(client: TestClient, app: FastAPI) -> None:
    """A13: aresta SEM `to` (ou apontando para nó inexistente) → 422 problem+json com
    mensagem clara (alimenta o retry §7.3) — nunca KeyError/500 no taxímetro."""
    _, corpo = _gerar_jornada(client, app)
    jornada = corpo["jornada"]

    sem_to = _grafo(corpo["jornada"]["grafo"]["meta"]["osCodigo"])
    del sem_to["edges"][3]["to"]  # e4 (n3 → n4) perde o destino
    resposta = client.put(
        f"/api/v1/jornadas/{jornada['id']}/grafo", json={"grafo": sem_to}, headers=_h()
    )
    assert resposta.status_code == 422, resposta.text  # jamais 500 (KeyError bruto)
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    erros = resposta.json()["erros"]
    assert any("`to`" in e["mensagem"] and e["regra"] == "estrutura" for e in erros)

    # aresta apontando para nó INEXISTENTE → 422 com o alvo na mensagem
    fantasma = _grafo(corpo["jornada"]["grafo"]["meta"]["osCodigo"])
    fantasma["edges"][3]["to"] = "n99"
    resposta = client.put(
        f"/api/v1/jornadas/{jornada['id']}/grafo", json={"grafo": fantasma}, headers=_h()
    )
    assert resposta.status_code == 422, resposta.text
    assert any("n99" in e["mensagem"] for e in resposta.json()["erros"])

    # nada foi salvo: o twin persistido segue íntegro
    persistida = app.state.repositorio_os.obter_jornada(uuid.UUID(jornada["id"]))
    assert all(a.get("to") for a in persistida.grafo["edges"])


def test_M7_get_jornada_ultima_versao(client: TestClient, app: FastAPI) -> None:
    """Emenda A14 (§8-M7): `GET /os/{id}/jornada` devolve a ÚLTIMA versão do twin
    (o canvas T7 reabre o grafo persistido); OS sem versão → 404 problem+json."""
    os_, corpo = _gerar_jornada(client, app)

    lida = client.get(f"/api/v1/os/{os_['id']}/jornada", headers=_h())
    assert lida.status_code == 200, lida.text
    assert lida.json()["id"] == corpo["jornada"]["id"]
    assert lida.json()["versao"] == 1
    assert lida.json()["grafo"] == corpo["jornada"]["grafo"]

    # nova geração cria a v2 — o GET passa a devolver a versão mais recente
    segunda = client.post(f"/api/v1/os/{os_['id']}/jornada/gerar", headers=_h())
    assert segunda.status_code == 201, segunda.text
    lida = client.get(f"/api/v1/os/{os_['id']}/jornada", headers=_h())
    assert lida.status_code == 200 and lida.json()["versao"] == 2

    # OS nova (sem twin) → 404 problem+json
    outra = _criar_os_com_segmento(client, app)
    ausente = client.get(f"/api/v1/os/{outra['id']}/jornada", headers=_h())
    assert ausente.status_code == 404
    assert ausente.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)


# ------------------- Versionamento & exportação (emenda §8-M7 2026-08-05) — B1..B5


class _RelogioFixo:
    """Dublê do ClockPort (§2.1 — padrão do M11): o determinismo do export XML é
    função do RELÓGIO injetado (`app.state.relogio`), nunca do wall time."""

    def __init__(self, instante: datetime) -> None:
        self._instante = instante

    def agora(self) -> datetime:
        return self._instante


def _grafo_modificado(os_codigo: str) -> dict[str, Any]:
    """Variante do JGC de referência p/ o diff (B3): n2 alterado (80/20), n4
    (whatsapp) REMOVIDO, n7 (sms) ADICIONADO no lugar — e4/e5 religadas via n7."""
    grafo = _grafo(os_codigo)
    for no in grafo["nodes"]:
        if no["id"] == "n2":
            no["data"]["braços"] = [{"id": "tratado", "pct": 80}, {"id": "holdout", "pct": 20}]
    grafo["nodes"] = [n for n in grafo["nodes"] if n["id"] != "n4"] + [
        {"id": "n7", "type": "channel.sms", "data": {"assetRef": "asset-sms-1", "optIn": True}}
    ]
    for aresta in grafo["edges"]:
        if aresta["id"] == "e4":
            aresta["to"] = "n7"  # n3 → n7
        if aresta["id"] == "e5":
            aresta["from"] = "n7"  # n7 → n5
    return grafo


def test_M7_B1(client: TestClient, app: FastAPI) -> None:
    """B1: `GET /os/{id}/jornadas` lista TODAS as versões em ordem de `versao`,
    resumidas (id, versao, estado, hash, custo, created — SEM grafo)."""
    os_, corpo = _gerar_jornada(client, app)
    v1 = corpo["jornada"]
    restaurada = client.post(f"/api/v1/jornadas/{v1['id']}/restaurar", headers=_h())
    assert restaurada.status_code == 201, restaurada.text

    resposta = client.get(f"/api/v1/os/{os_['id']}/jornadas", headers=_h())
    assert resposta.status_code == 200, resposta.text
    versoes = resposta.json()
    assert [v["versao"] for v in versoes] == [1, 2]  # ordem de versao (§4.1)
    assert versoes[0]["id"] == v1["id"]
    for versao in versoes:  # resumo: contrato fechado, sem o grafo (payload leve)
        assert set(versao) == {"id", "versao", "estado", "hash", "custo_projetado", "created_at"}
        assert versao["created_at"] is not None
    assert versoes[0]["hash"] == versoes[1]["hash"]  # restaurada = mesmo grafo (B2)
    assert versoes[1]["estado"] == "rascunho"

    # OS existente sem versão → lista vazia (não 404 — a OS existe)
    outra = _criar_os_com_segmento(client, app)
    vazia = client.get(f"/api/v1/os/{outra['id']}/jornadas", headers=_h())
    assert vazia.status_code == 200 and vazia.json() == []

    # OS inexistente → 404 problem+json
    ausente = client.get(f"/api/v1/os/{uuid.uuid4()}/jornadas", headers=_h())
    assert ausente.status_code == 404
    assert ausente.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)


def test_M7_B2(client: TestClient, app: FastAPI) -> None:
    """B2: `POST /jornadas/{id}/restaurar` clona como NOVA versão `rascunho` com
    grafo idêntico e hash igual — versões NUNCA são editadas retroativamente."""
    _, corpo = _gerar_jornada(client, app)
    v1 = corpo["jornada"]

    resposta = client.post(f"/api/v1/jornadas/{v1['id']}/restaurar", headers=_h())
    assert resposta.status_code == 201, resposta.text
    nova = resposta.json()["jornada"]
    assert nova["id"] != v1["id"]  # NOVA versão — a origem permanece intocada
    assert nova["versao"] == 2 and nova["estado"] == "rascunho"
    assert nova["grafo"] == v1["grafo"] and nova["hash"] == v1["hash"]
    assert nova["custo_projetado"] == 16_267.50  # taxímetro RECALCULADO (A2)
    assert resposta.json()["taximetro"]["custo_projetado"] == 16_267.50

    # a v1 persistida segue exatamente como estava (imutabilidade retroativa)
    persistida = app.state.repositorio_os.obter_jornada(uuid.UUID(v1["id"]))
    assert persistida.versao == 1 and persistida.grafo == v1["grafo"]

    # `GET /jornadas/{id}` devolve a versão específica completa (grafo incluso)
    especifica = client.get(f"/api/v1/jornadas/{v1['id']}", headers=_h())
    assert especifica.status_code == 200 and especifica.json()["grafo"] == v1["grafo"]

    # restaurar exige papel de escrita (RBAC §8-M0) e 404 para id desconhecido
    proibido = client.post(f"/api/v1/jornadas/{v1['id']}/restaurar", headers=_h("dev-solicitante"))
    assert proibido.status_code == 403
    ausente = client.post(f"/api/v1/jornadas/{uuid.uuid4()}/restaurar", headers=_h())
    assert ausente.status_code == 404
    assert ausente.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)


def test_M7_B3(client: TestClient, app: FastAPI) -> None:
    """B3: `GET /jornadas/{a}/diff/{b}` acusa nó adicionado (n7), alterado (n2) e
    removido (n4) + arestas religadas — o MESMO diff.py do ajustar/M11."""
    os_, corpo = _gerar_jornada(client, app)
    v1 = corpo["jornada"]
    v2_id = client.post(f"/api/v1/jornadas/{v1['id']}/restaurar", headers=_h()).json()["jornada"][
        "id"
    ]
    salvo = client.put(
        f"/api/v1/jornadas/{v2_id}/grafo",
        json={"grafo": _grafo_modificado(os_["codigo"])},
        headers=_h(),
    )
    assert salvo.status_code == 200, salvo.text

    resposta = client.get(f"/api/v1/jornadas/{v1['id']}/diff/{v2_id}", headers=_h())
    assert resposta.status_code == 200, resposta.text
    diff = resposta.json()
    assert diff["de"] == {"id": v1["id"], "versao": 1, "hash": v1["hash"]}
    assert diff["para"]["versao"] == 2 and diff["para"]["hash"] != v1["hash"]
    assert diff["nodes"]["adicionados"] == ["n7"]
    assert diff["nodes"]["removidos"] == ["n4"]
    assert diff["nodes"]["alterados"] == ["n2"]
    assert diff["edges"]["alterados"] == ["e4", "e5"]  # religadas via n7
    assert diff["edges"]["adicionados"] == [] and diff["edges"]["removidos"] == []
    assert diff["meta_alterada"] is False

    # diff de uma versão com ela mesma → vazio (sanidade do determinismo)
    identico = client.get(f"/api/v1/jornadas/{v1['id']}/diff/{v1['id']}", headers=_h()).json()
    assert identico["nodes"] == {"adicionados": [], "removidos": [], "alterados": []}

    # versões de OSs DIFERENTES não são comparáveis → 409 problem+json
    _, outro_corpo = _gerar_jornada(client, app)
    cruzado = client.get(
        f"/api/v1/jornadas/{v1['id']}/diff/{outro_corpo['jornada']['id']}", headers=_h()
    )
    assert cruzado.status_code == 409
    assert cruzado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)


def test_M7_B4(client: TestClient, app: FastAPI) -> None:
    """B4: export JSON = spec de interaction do JB (import nativo — REST
    /interaction/v1/interactions) com TODAS as activities do grafo, externalKeys
    idempotentes (§5.4.1), triggers dos entrySources e goals."""
    os_, corpo = _gerar_jornada(client, app)
    jornada = corpo["jornada"]
    hash12 = jornada["hash"][:12]

    resposta = client.get(f"/api/v1/jornadas/{jornada['id']}/export?formato=json", headers=_h())
    assert resposta.status_code == 200, resposta.text
    assert resposta.headers["content-type"].startswith("application/json")
    assert (
        resposta.headers["content-disposition"]
        == f'attachment; filename="jornada-{os_["codigo"]}-v1.json"'
    )
    interaction = resposta.json()
    assert interaction["key"] == f"jrn-{hash12}"
    assert interaction["name"] == os_["codigo"]
    # triggers = entrySources; activities = TODOS os demais nós, com externalKey §5.4.1
    assert [t["key"] for t in interaction["triggers"]] == [external_key(jornada["hash"], "n1")]
    assert {a["key"] for a in interaction["activities"]} == {
        external_key(jornada["hash"], no) for no in ("n2", "n3", "n4", "n5", "n6")
    }
    por_no = {a["key"]: a for a in interaction["activities"]}
    email = por_no[external_key(jornada["hash"], "n3")]
    assert email["type"] == "emailSend"
    assert email["outcomes"] == [
        {"key": "e4", "next": external_key(jornada["hash"], "n4"), "cond": None}
    ]
    assert interaction["goals"] == [
        {
            "key": external_key(jornada["hash"], "n5"),
            "arguments": {"metrica": "conversion", "deRef": "DE_conv"},
        }
    ]

    # determinístico pelo grafo sozinho: segunda chamada devolve bytes IDÊNTICOS
    assert (
        resposta.content
        == client.get(f"/api/v1/jornadas/{jornada['id']}/export?formato=json", headers=_h()).content
    )

    # formato fora de json|xml → 422 (contrato fechado)
    invalido = client.get(f"/api/v1/jornadas/{jornada['id']}/export?formato=yaml", headers=_h())
    assert invalido.status_code == 422


def test_M7_B5(client: TestClient, app: FastAPI) -> None:
    """B5: export XML válido contra journey_export.xsd e DETERMINÍSTICO byte a byte
    com mesmo grafo+clock (ClockPort fixado via app.state.relogio — §2.1)."""
    os_, corpo = _gerar_jornada(client, app)
    jornada = corpo["jornada"]
    instante = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
    app.state.relogio = _RelogioFixo(instante)

    url = f"/api/v1/jornadas/{jornada['id']}/export?formato=xml"
    resposta = client.get(url, headers=_h())
    assert resposta.status_code == 200, resposta.text
    assert resposta.headers["content-type"].startswith("application/xml")
    assert (
        resposta.headers["content-disposition"]
        == f'attachment; filename="jornada-{os_["codigo"]}-v1.xml"'
    )

    # mesmo grafo + mesmo clock ⇒ MESMOS bytes (determinismo é contrato, não sorte)
    assert resposta.content == client.get(url, headers=_h()).content

    # XML VÁLIDO contra o XSD canônico (domain/jornada/journey_export.xsd)
    esquema = etree.XMLSchema(etree.parse(str(XSD_PATH)))
    documento = etree.fromstring(resposta.content)
    esquema.assertValid(documento)

    # manifest embutido: hash JGC, versao, geradoEm (ClockPort) e plataforma
    manifesto = documento.find("Manifest")
    assert manifesto.get("hashJgc") == jornada["hash"]
    assert manifesto.get("versao") == "1"
    assert manifesto.get("geradoEm") == instante.isoformat()
    assert manifesto.get("plataforma") == "Jornada"

    # a MESMA spec do JSON: key e activities idênticas às do export JSON (B4)
    assert documento.get("key") == f"jrn-{jornada['hash'][:12]}"
    atividades = documento.find("Activities")
    assert [a.get("key") for a in atividades] == [
        external_key(jornada["hash"], no) for no in ("n2", "n3", "n4", "n5", "n6")
    ]
    assert [g.get("key") for g in documento.find("Goals")] == [external_key(jornada["hash"], "n5")]

    # clock diferente ⇒ SÓ o geradoEm muda (o conteúdo segue canônico)
    app.state.relogio = _RelogioFixo(datetime(2026, 8, 6, 9, 30, 0, tzinfo=UTC))
    outro = client.get(url, headers=_h())
    assert outro.content != resposta.content
    esquema.assertValid(etree.fromstring(outro.content))


def test_M7_gerar_degradado_503_e_put_sem_llm(client: TestClient, app: FastAPI) -> None:
    """Hub LLM fora (§10.6): gerar → 503 degraded; PUT do grafo (caminho crítico)
    segue funcionando SEM LLM."""
    os_, corpo = _gerar_jornada(client, app)
    app.state.llm = LLMFake(disponivel=False)

    degradado = client.post(f"/api/v1/os/{os_['id']}/jornada/gerar", headers=_h())
    assert degradado.status_code == 503
    assert degradado.json()["modo"] == "degraded"

    salvo = client.put(
        f"/api/v1/jornadas/{corpo['jornada']['id']}/grafo",
        json={"grafo": corpo["jornada"]["grafo"]},
        headers=_h(),
    )
    assert salvo.status_code == 200, salvo.text
