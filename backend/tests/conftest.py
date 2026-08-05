"""Fixtures compartilhadas — testes rodam via TestClient, SEM docker.

O ping de DB do /healthz é substituído por dublê (dependency_overrides) para simular a
pré-condição do aceite M0-A1 ("dado compose up" → db saudável). Ver CHANGELOG-SDD.md.

Guarda-corpos de LLM/observabilidade (§1.3.5, §10.8): todo app de teste nasce com
`state.llm = LLMFake()` (o hub real NUNCA é chamado em teste — testes que precisam de
resposta específica trocam o fake) e `state.tracer` = Langfuse DESABILITADO
(LANGFUSE_ENABLED=false → no-op absoluto, nenhuma rede).
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.llm.fake import LLMFake
from adapters.observabilidade.langfuse import TracerLangfuse
from app.config import Settings
from app.main import create_app, ping_db


@pytest.fixture()
def app() -> FastAPI:
    # demo=False: os aceites M0–M12 valem sobre repositório VAZIO (as seeds §11.4 são
    # cobertas por tests/acceptance/test_seeds_demo.py com create_app(demo=True)).
    application = create_app(demo=False)
    application.dependency_overrides[ping_db] = lambda: "ok"  # dublê: compose up / db saudável
    application.state.llm = LLMFake()  # §1.3.5: hub real jamais em teste
    application.state.tracer = TracerLangfuse(  # §10.8: LANGFUSE_ENABLED=false em teste
        Settings(_env_file=None, langfuse_enabled=False)
    )
    return application


@pytest.fixture()
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
