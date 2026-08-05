"""Aceites do módulo M0 · Fundação (SDD §8-M0) — IDs iguais aos do SDD (§1.3.4).

Rodam via TestClient, sem docker (ping de DB dublado no conftest — CHANGELOG-SDD.md).
"""

import time

from fastapi.testclient import TestClient

from app.errors import PROBLEM_CONTENT_TYPE


def test_M0_A1(client: TestClient) -> None:
    """A1: dado compose up, quando GET /healthz, então {db:ok, llm:skip|ok} em <2s."""
    inicio = time.perf_counter()
    resposta = client.get("/healthz")
    duracao = time.perf_counter() - inicio

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["db"] == "ok"
    assert corpo["llm"] in ("skip", "ok")
    assert set(corpo) == {"db", "llm"}
    assert duracao < 2.0


def test_M0_A2(client: TestClient) -> None:
    """A2: requisição a /api/v1/* sem header X-Tenant → 400 (problem+json RFC-7807)."""
    resposta = client.get("/api/v1/os")  # qualquer rota sob /api/v1

    assert resposta.status_code == 400
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    corpo = resposta.json()
    assert corpo["status"] == 400
    assert "X-Tenant" in corpo["detail"]


def test_M0_A2_com_header_passa_do_middleware(client: TestClient) -> None:
    """Com X-Tenant presente o middleware libera — a rota M1 responde 401 (Bearer ausente),
    provando que o 400 de tenant não interceptou (era 404 antes do M1 — CHANGELOG-SDD.md)."""
    resposta = client.get("/api/v1/os", headers={"X-Tenant": "torre-movel"})

    assert resposta.status_code == 401
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)


def test_M0_healthz_dispensa_x_tenant(client: TestClient) -> None:
    """/healthz fica fora do prefixo /api/v1 — não exige X-Tenant (§8)."""
    assert client.get("/healthz").status_code == 200
