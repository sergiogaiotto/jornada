"""Fixtures compartilhadas — testes rodam via TestClient, SEM docker.

O ping de DB do /healthz é substituído por dublê (dependency_overrides) para simular a
pré-condição do aceite M0-A1 ("dado compose up" → db saudável). Ver CHANGELOG-SDD.md.

Guarda-corpos de LLM/observabilidade (§1.3.5, §10.8): todo app de teste nasce com
`state.llm = LLMFake()` e `state.embedding = EmbeddingFake()` (o hub real NUNCA é
chamado em teste — testes que precisam de resposta específica trocam o fake) e
`state.tracer` = Langfuse DESABILITADO (LANGFUSE_ENABLED=false → no-op absoluto,
nenhuma rede).
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.embedding.fake import EmbeddingFake
from adapters.llm.fake import LLMFake
from adapters.observabilidade.langfuse import TracerLangfuse
from app.auth import DEV_TOKENS, PORTAL_TOKENS, Usuario
from app.config import Settings
from app.main import create_app, ping_db


@pytest.fixture(autouse=True)
def _persistencia_em_memoria(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda-corpo A7: fora dos testes @integration, `create_app` NUNCA seleciona os
    repos SQL — mesmo se o dev estiver com docker de pé e DATABASE_URL exportado, os
    aceites M0–M12 valem sobre repositório em memória isolado (sem estado entre runs)."""
    if "integration" in request.keywords:
        return
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture()
def app() -> FastAPI:
    # demo=False: os aceites M0–M12 valem sobre repositório VAZIO (as seeds §11.4 são
    # cobertas por tests/acceptance/test_seeds_demo.py com create_app(demo=True)).
    application = create_app(demo=False)
    application.dependency_overrides[ping_db] = lambda: "ok"  # dublê: compose up / db saudável
    application.state.llm = LLMFake()  # §1.3.5: hub real jamais em teste
    application.state.embedding = EmbeddingFake()  # §1.3.5 idem para embeddings (A11)
    application.state.tracer = TracerLangfuse(  # §10.8: LANGFUSE_ENABLED=false em teste
        Settings(_env_file=None, langfuse_enabled=False)
    )
    return application


@pytest.fixture()
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


TENANT_ALHEIO = "outra-torre"


@pytest.fixture()
def tokens_outro_tenant(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Segunda identidade REAL (achado 5/UAT5): tokens de dev e de portal de `outra-torre`.

    Os tokens seed (§8) são todos de `torre-movel`. Desde que o `X-Tenant` é conferido
    contra o portador (o header é asserção, não fonte da verdade), provar isolamento
    exige um USUÁRIO do outro tenant — forjar o header é exatamente o que o fix proíbe.
    Devolve `{"pleno": ..., "portal": ...}`."""
    pleno, portal = "dev-analista-outra-torre", "portal-outra-torre"
    monkeypatch.setitem(
        DEV_TOKENS,
        pleno,
        Usuario(
            id=uuid.uuid5(uuid.NAMESPACE_URL, "jornada/dev/analista/outra-torre"),
            tenant_id=TENANT_ALHEIO,
            nome="Dev Analista (outra torre)",
            email="analista@outra-torre.local",
            papeis=("analista",),
        ),
    )
    monkeypatch.setitem(
        PORTAL_TOKENS,
        portal,
        Usuario(
            id=uuid.uuid5(uuid.NAMESPACE_URL, "jornada/portal/outra-torre"),
            tenant_id=TENANT_ALHEIO,
            nome="Solicitante (Portal, outra torre)",
            email="portal@outra-torre.local",
            papeis=("solicitante",),
        ),
    )
    return {"pleno": pleno, "portal": portal}
