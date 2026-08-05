"""Factory FastAPI — SDD §2.2 (`backend/app/main.py`) e §8-M0.

Convenções de API (§8): prefixo /api/v1, header X-Tenant obrigatório (400 sem ele),
erros RFC-7807, auth Bearer dev. `GET /healthz` fora do prefixo (ops).
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from api.v1 import api_router
from app.config import get_settings
from app.errors import problem_response, register_error_handlers

TENANT_HEADER = "X-Tenant"
API_PREFIX = "/api/v1"


async def ping_db() -> str:
    """Ping do Postgres com timeout curto (contrato /healthz: 'ok' | 'fail', <2s)."""
    settings = get_settings()
    try:
        engine = create_async_engine(settings.database_url)
        try:
            async with asyncio.timeout(1.5):
                async with engine.connect() as conn:
                    await conn.execute(text("select 1"))
            return "ok"
        finally:
            await engine.dispose()
    except Exception:
        return "fail"


async def ping_llm() -> str:
    """Contrato /healthz: 'skip' | 'ok'. Em dev (ou forced_off §10.6) não sonda o hub."""
    settings = get_settings()
    if settings.app_env == "dev" or settings.llm_degraded_mode == "forced_off":
        return "skip"
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(
                f"{settings.llm_20b_base_url}/models",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            )
        return "ok" if resp.status_code < 500 else "skip"
    except Exception:
        return "skip"


def create_app(*, demo: bool | None = None) -> FastAPI:
    """`demo` (§11.4): None = automático (DEMO_MODE=true e APP_ENV=dev carregam as
    seeds da OS-2026-0457); os testes de aceite criam o app com `demo=False` — os
    aceites M0–M12 valem com e sem seeds (as seeds só ADICIONAM dados demo)."""
    settings = get_settings()  # valida config no startup (ex.: APP_SECRET em prod — §10.3)
    app = FastAPI(
        title="Jornada",
        version="1.0.0",
        description=(
            "Digital Twin do Journey Builder (SFMC) — API v1. "
            "Contrato: SDD-Jornada.md (Spec-Driven Development)."
        ),
    )

    @app.middleware("http")
    async def exigir_x_tenant(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Header X-Tenant obrigatório em /api/v1/* (§8) — 400 problem+json sem ele."""
        if request.url.path.startswith(API_PREFIX):
            tenant = request.headers.get(TENANT_HEADER)
            if not tenant:
                return problem_response(
                    400,
                    "Bad Request",
                    detail=f"Header {TENANT_HEADER} é obrigatório (SDD §8).",
                    instance=request.url.path,
                )
            request.state.tenant_id = tenant
        return await call_next(request)

    register_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)

    @app.get("/healthz", tags=["ops"])
    async def healthz(
        db: Annotated[str, Depends(ping_db)],
        llm: Annotated[str, Depends(ping_llm)],
    ) -> dict[str, str]:
        """M0-A1: `{db: ok, llm: skip|ok}` em <2s com o compose de pé."""
        return {"db": db, "llm": llm}

    if demo if demo is not None else (settings.demo_mode and settings.app_env == "dev"):
        # Seeds DEMO_MODE (§11.4): repo em memória já semeado com a OS-2026-0457
        # ponta a ponta — imports tardios evitam custo quando demo está desligado.
        from adapters.demo_seeds import semear_demo
        from adapters.persistence.memoria import RepositorioOsMemoria

        repositorio = RepositorioOsMemoria()
        semear_demo(repositorio, tenant_id=settings.default_tenant, agora=datetime.now(UTC))
        app.state.repositorio_os = repositorio

    return app


app = create_app()
