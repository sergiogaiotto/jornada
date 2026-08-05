"""Aceites do módulo M7 · Twin Canvas T7 (SDD §5, §8-M7) — IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker e SEM REDE: o flow usa o LLMFake (§1.3.5 — único
adapter de LLM permitido em teste); validação §5.3, taxímetro (A2) e sfmc-preview são
código determinístico. O segmento recontado (volume do taxímetro) é semeado direto no
repositório em memória (`app.state.repositorio_os` — padrão dos aceites M8); o
experimento do A3 nasce pelo próprio `POST /experimentos` (M8 parte 2 — já travado).
"""

import json
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.llm.fake import LLMFake
from app.errors import PROBLEM_CONTENT_TYPE
from domain.audiencia.modelos import Segmento

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
