"""Aceites do módulo M1 · Núcleo OS/governança (SDD §8-M1) — IDs iguais aos do SDD (§1.3.4).

Rodam via TestClient, sem docker (repositório em memória — CHANGELOG-SDD.md M1).
Tokens dev (§8-M0): dev-analista/dev-lider; ids de usuário determinísticos (app.auth).
"""

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import DEV_TOKENS
from app.errors import PROBLEM_CONTENT_TYPE

TENANT = "torre-movel"


def _h(token: str) -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _criar_os(client: TestClient) -> dict[str, Any]:
    resposta = client.post(
        "/api/v1/os",
        json={"nome": "Upgrade Pós-Pago 5G", "tshirt": "M", "briefing": {"objetivo": "upsell"}},
        headers=_h("dev-analista"),
    )
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["fase"] == "pensada"
    return corpo


def _abrir_pendencia(client: TestClient, os_id: str, **campos: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"titulo": "Opt-in do canal SMS não confirmado", **campos}
    resposta = client.post(
        f"/api/v1/os/{os_id}/pendencias", json=payload, headers=_h("dev-analista")
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_M1_A1(client: TestClient) -> None:
    """A1: pendência bloqueante aberta → POST /os/{id}/fase NÃO avança: 409 com motivo
    no corpo problem+json (RFC-7807)."""
    os_ = _criar_os(client)
    pendencia = _abrir_pendencia(client, os_["id"], bloqueante=True, severidade="alta")
    assert pendencia["status"] == "aberta" and pendencia["bloqueante"] is True

    resposta = client.post(
        f"/api/v1/os/{os_['id']}/fase", json={"fase": "discutida"}, headers=_h("dev-analista")
    )

    assert resposta.status_code == 409
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    corpo = resposta.json()
    assert corpo["status"] == 409
    # motivo legível no corpo, apontando a(s) pendência(s) que bloqueia(m)
    assert f"#{pendencia['numero']} {pendencia['titulo']}" in corpo["detail"]
    assert corpo["pendencias"][0]["numero"] == pendencia["numero"]

    # e a OS de fato não avançou
    consulta = client.get(f"/api/v1/os/{os_['id']}", headers=_h("dev-analista"))
    assert consulta.status_code == 200
    assert consulta.json()["fase"] == "pensada"


def test_M1_A2(client: TestClient, app: FastAPI) -> None:
    """A2: aceite de pendência exige papel accountable + justificativa; gera
    `domain_event` pendencia.accepted (§2.3)."""
    accountable = DEV_TOKENS["dev-lider"]
    os_ = _criar_os(client)
    pendencia = _abrir_pendencia(
        client, os_["id"], bloqueante=True, tipo="risk", accountable=str(accountable.id)
    )

    # quem não é o accountable não aceita (403 — AcaoNaoPermitida, segregação §10.5)
    negado = client.post(
        f"/api/v1/pendencias/{pendencia['id']}/aceitar",
        json={"justificativa": "Tentativa indevida"},
        headers=_h("dev-analista"),
    )
    assert negado.status_code == 403
    assert negado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    # accountable sem justificativa → 422 (ausente: contrato; em branco: JustificativaObrigatoria)
    sem_justificativa = client.post(
        f"/api/v1/pendencias/{pendencia['id']}/aceitar", json={}, headers=_h("dev-lider")
    )
    assert sem_justificativa.status_code == 422
    em_branco = client.post(
        f"/api/v1/pendencias/{pendencia['id']}/aceitar",
        json={"justificativa": "   "},
        headers=_h("dev-lider"),
    )
    assert em_branco.status_code == 422

    # accountable + justificativa → aceita, com registro {por, em, justificativa}
    aceite = client.post(
        f"/api/v1/pendencias/{pendencia['id']}/aceitar",
        json={"justificativa": "Risco assumido: campanha piloto com volume reduzido."},
        headers=_h("dev-lider"),
    )
    assert aceite.status_code == 200, aceite.text
    corpo = aceite.json()
    assert corpo["status"] == "aceita"
    assert corpo["aceite"]["por"] == str(accountable.id)
    assert corpo["aceite"]["justificativa"].startswith("Risco assumido")

    # domain_event pendencia.accepted no outbox (§2.3)
    eventos = app.state.repositorio_os.listar_eventos(tipo="pendencia.accepted")
    assert len(eventos) == 1
    evento = eventos[0]
    assert evento.payload["pendencia_id"] == pendencia["id"]
    assert evento.payload["por"] == str(accountable.id)
    assert evento.actor == accountable.email


def test_M1_A3(client: TestClient, app: FastAPI) -> None:
    """A3: saúde é view derivada (§4.1) — não existe endpoint de escrita de saúde
    (PUT/POST/PATCH/DELETE → 404/405)."""
    os_ = _criar_os(client)
    url = f"/api/v1/os/{os_['id']}/saude"

    leitura = client.get(url, headers=_h("dev-analista"))
    assert leitura.status_code == 200
    assert leitura.json() == {"os_id": os_["id"], "saude": "normal"}

    # a derivação reage ao estado (pendência bloqueante aberta → em_risco), sem escrita
    _abrir_pendencia(client, os_["id"], bloqueante=True)
    assert client.get(url, headers=_h("dev-analista")).json()["saude"] == "em_risco"

    for metodo in ("PUT", "POST", "PATCH", "DELETE"):
        resposta = client.request(metodo, url, json={"saude": "normal"}, headers=_h("dev-admin"))
        assert resposta.status_code in (404, 405), (metodo, resposta.status_code)
        assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    # e no contrato OpenAPI não há NENHUMA operação de /saude além do GET
    caminhos_saude = {
        caminho: operacoes
        for caminho, operacoes in app.openapi()["paths"].items()
        if caminho.endswith("/saude")
    }
    assert caminhos_saude, "rota GET /os/{id}/saude deve existir (§8-M1)"
    for caminho, operacoes in caminhos_saude.items():
        assert set(operacoes) == {"get"}, (caminho, sorted(operacoes))


def test_M1_A4(client: TestClient) -> None:
    """A4 (emenda B01, UAT #2): `GET /os/{id}/pendencias` — a rota só aceitava POST (405),
    então o que estava aberto sumia da tela a cada reload. A leitura devolve TODAS as
    pendências da OS em ordem de `numero`, com o que a governança precisa decidir:
    severidade, status, bloqueante, accountable e a origem que ancora no campo."""
    os_ = _criar_os(client)
    assert client.get(f"/api/v1/os/{os_['id']}/pendencias", headers=_h("dev-analista")).json() == []

    accountable = DEV_TOKENS["dev-lider"]
    primeira = _abrir_pendencia(
        client,
        os_["id"],
        titulo="Opt-in do canal SMS não confirmado",
        severidade="alta",
        bloqueante=True,
        accountable=str(accountable.id),
        origem="validacao:canais",
    )
    segunda = _abrir_pendencia(
        client, os_["id"], titulo="Tarifário de push desatualizado", bloqueante=False
    )

    listadas = client.get(f"/api/v1/os/{os_['id']}/pendencias", headers=_h("dev-analista"))
    assert listadas.status_code == 200, listadas.text
    corpo = listadas.json()
    assert [p["numero"] for p in corpo] == [primeira["numero"], segunda["numero"]]  # ordem estável
    assert corpo[0] == primeira  # o corpo da leitura é o MESMO contrato do POST
    assert corpo[0]["severidade"] == "alta" and corpo[0]["bloqueante"] is True
    assert corpo[0]["accountable"] == str(accountable.id)
    assert corpo[0]["origem"] == "validacao:canais"
    assert corpo[1]["bloqueante"] is False

    # tratada muda de status na leitura (a UI distingue o que ainda trava o avanço)
    aceite = client.post(
        f"/api/v1/pendencias/{primeira['id']}/aceitar",
        json={"justificativa": "Risco aceito pela liderança para a janela desta campanha."},
        headers=_h("dev-lider"),
    )
    assert aceite.status_code == 200, aceite.text
    depois = client.get(f"/api/v1/os/{os_['id']}/pendencias", headers=_h("dev-analista")).json()
    assert [p["status"] for p in depois] == ["aceita", "aberta"]
    assert depois[0]["aceite"]["justificativa"].startswith("Risco aceito")

    # leitura é de qualquer autenticado (§8-M0) e escopada por tenant
    de_leitor = client.get(f"/api/v1/os/{os_['id']}/pendencias", headers=_h("dev-solicitante"))
    assert de_leitor.status_code == 200
    outro = {"X-Tenant": "outro", "Authorization": "Bearer dev-analista"}
    assert client.get(f"/api/v1/os/{os_['id']}/pendencias", headers=outro).status_code == 404
