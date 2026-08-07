"""Unit — config (§3/§10.3) e handler de erros RFC-7807 (§8)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.errors import PROBLEM_CONTENT_TYPE


def test_defaults_espelham_env_example(ambiente_sem_config: None) -> None:
    # `ambiente_sem_config`: `_env_file=None` desliga o ARQUIVO, não o `os.environ` — sem
    # a limpeza, com a suíte rodando em `APP_ENV=prod` (frente 3) este teste mediria o
    # ambiente do processo e não o default do código. Ver tests/conftest.py.
    s = Settings(_env_file=None)
    assert s.app_env == "dev"
    assert s.default_tenant == "torre-movel"
    assert s.llm_api_key == "not-needed"  # §3: string literal válida (proxy autentica)
    assert s.llm_timeout_s == 300
    assert s.embed_dim == 1024
    assert s.rag_collection == "agente_evidence"
    assert s.sfmc_api_budget_per_apply == 200
    assert s.langfuse_enabled is True  # §10.8


def test_prod_com_secret_default_falha(ambiente_sem_config: None) -> None:
    """§10.3: APP_SECRET obrigatório ≠ default em APP_ENV=prod (startup falha).

    Sem `ambiente_sem_config` o `APP_SECRET` do processo entrava por baixo e o
    fail-fast "passava" sem nunca ter sido exercitado — o teste do guarda-corpo
    dependendo do ambiente que o guarda-corpo existe para não confiar."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="prod")


def test_prod_com_secret_proprio_passa() -> None:
    s = Settings(_env_file=None, app_env="prod", app_secret="segredo-de-vault")
    assert s.app_env == "prod"


def test_404_em_problem_json(app: FastAPI) -> None:
    client = TestClient(app)
    resposta = client.get("/rota-inexistente")
    assert resposta.status_code == 404
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    corpo = resposta.json()
    assert corpo["title"] == "Not Found"
    assert corpo["status"] == 404
    assert corpo["type"] == "about:blank"
    assert corpo["instance"] == "/rota-inexistente"


def test_erro_de_validacao_422_problem_json(app: FastAPI) -> None:
    from fastapi import Query

    @app.get("/api/v1/_validation-probe")  # rota exclusiva de teste
    async def _probe(limit: int = Query(...)) -> dict[str, int]:
        return {"limit": limit}

    client = TestClient(app)
    resposta = client.get(
        "/api/v1/_validation-probe",
        params={"limit": "nao-numero"},
        headers={"X-Tenant": "torre-movel"},
    )
    assert resposta.status_code == 422
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert resposta.json()["errors"]


def test_excecao_nao_tratada_500_problem_json(app: FastAPI) -> None:
    @app.get("/api/v1/_boom-probe")  # rota exclusiva de teste
    async def _boom() -> None:
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    resposta = client.get("/api/v1/_boom-probe", headers={"X-Tenant": "torre-movel"})
    assert resposta.status_code == 500
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert resposta.json()["title"] == "Internal Server Error"
