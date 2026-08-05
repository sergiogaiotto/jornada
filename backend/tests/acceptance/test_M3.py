"""Aceites do módulo M3 · Intake & Consultor (SDD §8-M3) — IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker (repositório em memória). LLM: SEMPRE o adapter fake
(`app.state.llm` — conftest injeta um default; aqui trocamos por respostas enlatadas);
o hub real jamais é chamado (§1.3.5). Langfuse desabilitado (no-op — §10.8).
Portal: token `portal-dev` (link com token, sem login pleno — §8-M3).
"""

import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.llm.fake import LLMFake
from app.auth import PORTAL_TOKENS
from app.errors import PROBLEM_CONTENT_TYPE

TENANT = "torre-movel"

CONTEUDO_PARCIAL = {  # sem verba/janela (A1)
    "objetivo": "Upgrade de clientes pós-pago para planos 5G",
    "publico": "Pós-pago ativos há 12+ meses sem 5G",
    "oferta": "20GB de bônus por 6 meses",
}
CONTEUDO_COMPLETO = {**CONTEUDO_PARCIAL, "verba": "R$ 500.000", "janela": "01/10 a 15/10"}


def _h(token: str) -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _criar_pedido(client: TestClient, conteudo: dict[str, Any]) -> dict[str, Any]:
    resposta = client.post(
        "/api/v1/pedidos",
        json={"solicitante": {"nome": "Ana Lima", "area": "Marketing"}, "conteudo": conteudo},
        headers=_h("portal-dev"),  # portal via link com token, sem login pleno
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _resposta_consultor(**inferencias: dict[str, Any]) -> str:
    """Saída enlatada do LLM no contrato JSON do SKILL.md do consultor."""
    return json.dumps(
        {
            "resposta": "Com base em campanhas anteriores, sugiro verba e janela. Confere?",
            "inferencias": [
                {"campo": campo, "valor": dados["valor"], "evidencias": dados["evidencias"]}
                for campo, dados in inferencias.items()
            ],
        },
        ensure_ascii=False,
    )


def test_M3_A1(client: TestClient) -> None:
    """A1: pedido sem verba/janela → completude<100 e faltantes lista EXATAMENTE esses
    campos; cálculo é determinístico (nenhuma chamada de LLM na criação)."""
    pedido = _criar_pedido(client, CONTEUDO_PARCIAL)

    assert pedido["completude"] < 100
    assert pedido["completude"] == 60.0  # 3 de 5 obrigatórios (código, não LLM)
    assert pedido["faltantes"] == ["verba", "janela"]
    assert pedido["estado"] == "rascunho"
    assert pedido["os_id"] is None
    # conteúdo direto do solicitante NÃO é inferência (inferido:false, sem evidências)
    esperado = {"valor": CONTEUDO_PARCIAL["objetivo"], "inferido": False}
    assert pedido["conteudo"]["objetivo"] == esperado

    # sem token algum → 401 (portal exige o link com token)
    negado = client.post(
        "/api/v1/pedidos",
        json={"solicitante": {"nome": "X"}, "conteudo": {}},
        headers={"X-Tenant": TENANT},
    )
    assert negado.status_code == 401

    # pedido completo já nasce `completo`, com faltantes vazio
    completo = _criar_pedido(client, CONTEUDO_COMPLETO)
    assert completo["completude"] == 100.0
    assert completo["faltantes"] == []
    assert completo["estado"] == "completo"


def test_M3_A2(client: TestClient) -> None:
    """A2: converter exige completude=100 → 409 problem+json com os faltantes no motivo;
    com 100, cria a OS com briefing pré-preenchido (uma única vez)."""
    incompleto = _criar_pedido(client, CONTEUDO_PARCIAL)

    negado = client.post(
        f"/api/v1/pedidos/{incompleto['id']}/converter", json={}, headers=_h("dev-analista")
    )
    assert negado.status_code == 409, negado.text
    assert negado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    corpo = negado.json()
    assert corpo["status"] == 409
    assert "verba" in corpo["detail"] and "janela" in corpo["detail"]
    # e nenhuma OS foi criada
    assert client.get("/api/v1/os", headers=_h("dev-analista")).json() == []

    # completo → converte (201) com briefing pré-preenchido
    completo = _criar_pedido(client, CONTEUDO_COMPLETO)
    ok = client.post(
        f"/api/v1/pedidos/{completo['id']}/converter",
        json={"nome": "Upgrade Pós-Pago 5G", "tshirt": "G"},
        headers=_h("dev-analista"),
    )
    assert ok.status_code == 201, ok.text
    os_ = ok.json()
    assert os_["fase"] == "pensada" and os_["tshirt"] == "G"
    for campo, valor in CONTEUDO_COMPLETO.items():
        assert os_["briefing"][campo]["valor"] == valor

    # GET /os/{id}/briefing espelha o briefing convertido (§8-M3)
    briefing = client.get(f"/api/v1/os/{os_['id']}/briefing", headers=_h("dev-analista"))
    assert briefing.status_code == 200
    assert briefing.json() == {"os_id": os_["id"], "briefing": os_["briefing"]}

    # pedido convertido é terminal: nova conversão → 409
    de_novo = client.post(
        f"/api/v1/pedidos/{completo['id']}/converter", json={}, headers=_h("dev-analista")
    )
    assert de_novo.status_code == 409

    # RBAC: token de portal NÃO converte (converter exige login pleno analista|lider)
    outro = _criar_pedido(client, CONTEUDO_COMPLETO)
    portal = client.post(
        f"/api/v1/pedidos/{outro['id']}/converter", json={}, headers=_h("portal-dev")
    )
    assert portal.status_code == 401


def test_M3_A3(client: TestClient, app: FastAPI) -> None:
    """A3: toda inferência do consultor carrega `via_ai` + evidências (precedentes) —
    no conteúdo (`inferido:true` + evidencias), no ledger `invocacao` e no outbox
    `agent.invoked`; o briefing herda `inferido:true` até confirmação humana."""
    fake = LLMFake(
        resposta=_resposta_consultor(
            verba={
                "valor": "R$ 500.000",
                "evidencias": ["OS-2025-0311: upgrade 5G similar aprovou verba de R$ 500k"],
            },
            janela={
                "valor": "01/10 a 15/10",
                "evidencias": ["Histórico: janelas de 15 dias performam melhor no pós-pago"],
            },
        )
    )
    app.state.llm = fake  # §1.3.5: fake com resposta enlatada — nenhuma rede

    pedido = _criar_pedido(client, CONTEUDO_PARCIAL)
    resposta = client.post(
        f"/api/v1/pedidos/{pedido['id']}/mensagem",
        json={"mensagem": "Pode usar como referência a campanha de upgrade do ano passado."},
        headers=_h("portal-dev"),
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()

    # contrato §8-M3: conteúdo atualizado + completude + faltantes (recalculados por código)
    assert corpo["resposta"].startswith("Com base em campanhas anteriores")
    assert corpo["completude"] == 100.0 and corpo["faltantes"] == []
    assert corpo["estado"] == "completo"
    for campo in ("verba", "janela"):
        assert corpo["conteudo"][campo]["inferido"] is True  # até confirmação humana
        assert corpo["conteudo"][campo]["evidencias"]  # toda inferência tem evidências
    assert corpo["conteudo"]["objetivo"]["inferido"] is False  # veio do solicitante

    # roteamento §7.2: consultor é perfil 120b; prompt NÃO carrega PII do solicitante
    assert [c["perfil"] for c in fake.chamadas] == ["120b"]
    prompt = json.dumps(fake.chamadas[0]["mensagens"], ensure_ascii=False)
    assert "Ana Lima" not in prompt and "solicitante@" not in prompt

    # ledger `invocacao` (§4.1): via_ai reconstruível — portador, skill, evidências, latência
    repo = app.state.repositorio_os
    invocacoes = repo.listar_invocacoes(TENANT)
    assert len(invocacoes) == 1
    invocacao = invocacoes[0]
    assert invocacao.usuario_portador == PORTAL_TOKENS["portal-dev"].id
    assert invocacao.skill_versao == "1.0"
    assert invocacao.latencia_ms is not None and invocacao.latencia_ms >= 0
    assert any("OS-2025-0311" in evidencia for evidencia in invocacao.evidencias)
    assert {i["campo"] for i in invocacao.output["inferencias"]} == {"verba", "janela"}

    # outbox: `agent.invoked` com via_ai=true (§2.3)
    eventos = repo.listar_eventos(tipo="agent.invoked")
    assert len(eventos) == 1
    assert eventos[0].via_ai is True
    assert eventos[0].payload["invocacao_id"] == str(invocacao.id)
    assert sorted(eventos[0].payload["campos_inferidos"]) == ["janela", "verba"]

    # conversão: briefing herda inferido:true + evidências até confirmação (A3/§8-M3)
    convertido = client.post(
        f"/api/v1/pedidos/{pedido['id']}/converter", json={}, headers=_h("dev-analista")
    )
    assert convertido.status_code == 201, convertido.text
    os_ = convertido.json()
    assert os_["briefing"]["verba"]["inferido"] is True
    assert os_["briefing"]["verba"]["evidencias"]

    # PATCH /os/{id}/briefing/{campo}: confirmar (sem valor) → inferido:false
    confirmado = client.patch(
        f"/api/v1/os/{os_['id']}/briefing/verba", json={}, headers=_h("dev-analista")
    )
    assert confirmado.status_code == 200
    assert confirmado.json()["briefing"]["verba"] == {
        "valor": "R$ 500.000",
        "inferido": False,
        "evidencias": ["OS-2025-0311: upgrade 5G similar aprovou verba de R$ 500k"],
    }

    # editar (com valor) também confirma; campo desconhecido sem valor → 404
    editado = client.patch(
        f"/api/v1/os/{os_['id']}/briefing/janela",
        json={"valor": "05/10 a 20/10"},
        headers=_h("dev-analista"),
    )
    assert editado.status_code == 200
    assert editado.json()["briefing"]["janela"]["valor"] == "05/10 a 20/10"
    assert editado.json()["briefing"]["janela"]["inferido"] is False
    inexistente = client.patch(
        f"/api/v1/os/{os_['id']}/briefing/nao-existe", json={}, headers=_h("dev-analista")
    )
    assert inexistente.status_code == 404


def test_M3_llm_indisponivel_responde_503_degraded(client: TestClient, app: FastAPI) -> None:
    """§10.6: hub indisponível → agente responde 503 `degraded` (problem+json); o caminho
    determinístico (criação/conversão) segue funcionando sem LLM."""
    app.state.llm = LLMFake(disponivel=False)
    pedido = _criar_pedido(client, CONTEUDO_COMPLETO)  # determinístico: funciona sem LLM

    resposta = client.post(
        f"/api/v1/pedidos/{pedido['id']}/mensagem",
        json={"mensagem": "olá"},
        headers=_h("portal-dev"),
    )
    assert resposta.status_code == 503
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert resposta.json()["modo"] == "degraded"

    # conversão (código determinístico) não depende de LLM (§10.6)
    ok = client.post(
        f"/api/v1/pedidos/{pedido['id']}/converter", json={}, headers=_h("dev-analista")
    )
    assert ok.status_code == 201
