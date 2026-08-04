"""Fixtures compartilhadas — testes rodam via TestClient, SEM docker.

O ping de DB do /healthz é substituído por dublê (dependency_overrides) para simular a
pré-condição do aceite M0-A1 ("dado compose up" → db saudável). Ver CHANGELOG-SDD.md.
"""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app, ping_db


@pytest.fixture()
def app() -> FastAPI:
    application = create_app()
    application.dependency_overrides[ping_db] = lambda: "ok"  # dublê: compose up / db saudável
    return application


@pytest.fixture()
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
