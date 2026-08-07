"""Unit — auth dev Bearer estático + require_role (SDD §8-M0, papéis RBAC)."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import DEV_TOKENS, PAPEIS, Usuario, require_role
from app.config import Settings

TENANT = {"X-Tenant": "torre-movel"}
_exige_analista_ou_lider = require_role("analista", "lider")


@pytest.fixture()
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # TestClient CRU e ambiente FIXADO em dev: este arquivo é o unit do portador Bearer
    # estático, e ele só existe em dev (§10.3). Como a suíte roda também com
    # `APP_ENV=prod` (frente 3), o teste declara o ambiente de que precisa em vez de
    # herdá-lo do processo — herdar era o que fazia estes três casos caírem em prod.
    import app.auth as modulo_auth

    monkeypatch.setattr(
        modulo_auth, "get_settings", lambda: Settings(_env_file=None, app_env="dev")
    )

    # Rota exclusiva de teste (não faz parte do contrato §8) para exercitar o RBAC.
    @app.get("/api/v1/_rbac-probe")
    async def _probe(user: Usuario = Depends(_exige_analista_ou_lider)) -> dict[str, str]:
        return {"user": user.nome}

    return TestClient(app)


def test_tokens_dev_cobrem_todos_os_papeis() -> None:
    assert set(PAPEIS) == {"solicitante", "analista", "lider", "aprovador", "dpo", "admin"}
    assert {u.papeis[0] for u in DEV_TOKENS.values()} == set(PAPEIS)


def test_sem_bearer_401(client: TestClient) -> None:
    resposta = client.get("/api/v1/_rbac-probe", headers=TENANT)
    assert resposta.status_code == 401
    assert resposta.headers["www-authenticate"] == "Bearer"


def test_token_invalido_401(client: TestClient) -> None:
    headers = TENANT | {"Authorization": "Bearer nao-existe"}
    assert client.get("/api/v1/_rbac-probe", headers=headers).status_code == 401


def test_papel_errado_403(client: TestClient) -> None:
    headers = TENANT | {"Authorization": "Bearer dev-solicitante"}
    resposta = client.get("/api/v1/_rbac-probe", headers=headers)
    assert resposta.status_code == 403


def test_papel_correto_200(client: TestClient) -> None:
    headers = TENANT | {"Authorization": "Bearer dev-analista"}
    assert client.get("/api/v1/_rbac-probe", headers=headers).status_code == 200


def test_admin_sempre_passa(client: TestClient) -> None:
    headers = TENANT | {"Authorization": "Bearer dev-admin"}
    assert client.get("/api/v1/_rbac-probe", headers=headers).status_code == 200


def test_require_role_papel_desconhecido_falha_rapido() -> None:
    with pytest.raises(ValueError):
        require_role("papel-inexistente")
