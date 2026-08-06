"""Factory FastAPI — SDD §2.2 (`backend/app/main.py`) e §8-M0.

Convenções de API (§8): prefixo /api/v1, header X-Tenant obrigatório (400 sem ele) e
CONFERIDO contra o portador autenticado (403 se divergir — achado 5/UAT5), erros
RFC-7807, auth Bearer dev. `GET /healthz` fora do prefixo (ops).
"""

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from adapters.persistence.sql import RepositorioSql, criar_repositorio
from api.v1 import api_router
from app.auth import usuario_do_authorization
from app.config import get_settings
from app.errors import problem_response, register_error_handlers
from application.ports.embedding import EmbeddingPort

TENANT_HEADER = "X-Tenant"
API_PREFIX = "/api/v1"

# Rotas de /api/v1 isentas do header X-Tenant OBRIGATÓRIO (emenda C03, §8-M8/§8-M0-A2),
# como /healthz já é isento por viver fora do prefixo.
#
# ATENÇÃO ao nome (E03 — frente 3, §10.5): "PÚBLICAS" virou herança histórica e a emenda
# propõe renomear para ROTAS_SEM_TENANT_HEADER. `/aprovacao/*` NÃO é mais anônima —
# ambas as rotas exigem sessão autenticada na própria rota (api/v1/portoes.py), porque o
# token do link mágico deixou de ser credencial e virou ponteiro para o pacote. Isento
# aqui = "não precisa ANUNCIAR tenant", nunca "não precisa de credencial".
#
# Por que a isenção do header sobrevive ao login: esta é a URL que se abre ANTES de ter
# app aberto (link colado no chat, deep link), quando o cliente ainda não sabe qual
# tenant anunciar — o mesmo motivo pelo qual a futura rota de login não pode exigir o
# header. O escopo vem da SESSÃO (`get_tenant_do_aprovador`) e o pacote é conferido
# contra ele; o header, quando anunciado, continua sendo conferido — divergiu, 403.
#
# Prefixo fechado: só `/aprovacao/...` entra (test_E05_A7 guarda isso). Frente 1: as
# rotas de login/troca de senha entram AQUI quando existirem — antes do login não há
# tenant a anunciar. Nada mais do M8 é isento.
ROTAS_PUBLICAS: tuple[str, ...] = (f"{API_PREFIX}/aprovacao/",)


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


def create_app(*, demo: bool | None = None, embedding: EmbeddingPort | None = None) -> FastAPI:
    """`demo` (§11.4): None = automático (DEMO_MODE=true e APP_ENV=dev carregam as
    seeds da OS-2026-0457); os testes de aceite criam o app com `demo=False` — os
    aceites M0–M12 valem com e sem seeds (as seeds só ADICIONAM dados demo).

    `embedding` (A11 — §1.3.5): port de embeddings usado pela seed RAG do demo e
    stashado em `app.state.embedding` (rotas). None = adapter real HubGPU; testes
    com demo=True DEVEM injetar o fake (o hub real jamais é tocado em teste)."""
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
    async def resolver_tenant(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Tenant efetivo do request em /api/v1/* (§8 + achado 5/UAT5).

        O header X-Tenant é uma ASSERÇÃO do cliente, NUNCA a fonte da verdade — o
        portador autenticado já carrega o escopo (`Usuario.tenant_id`, §8-M0) e é ele
        que vale. Mesma regra que o C03 adotou para o link mágico, agora no resto da API:

        · header ausente → 400 problem+json (contrato §8 preservado, inclusive M0-A2);
        · portador reconhecido e header DIVERGENTE → 403 (nada chega à rota; antes o
          cliente escolhia o próprio escopo e lia/escrevia em tenant inventado);
        · portador reconhecido e header igual → segue com o tenant do USUÁRIO;
        · sem portador reconhecido → o header segue como estava e a rota responde 401
          (o middleware não pode virar oráculo de "este token existe?").

        Exceção: ROTAS_PUBLICAS (link mágico — C03) seguem sem header obrigatório. Desde o
        E03 (§10.5) elas exigem SESSÃO na rota, e o tenant efetivo delas vem do portador,
        não mais do token: quem confere é `get_tenant_do_aprovador` (api/v1/portoes.py),
        inclusive o 403 do header divergente. O middleware só se abstém do 400."""
        if request.url.path.startswith(API_PREFIX):
            anunciado = request.headers.get(TENANT_HEADER)
            if request.url.path.startswith(ROTAS_PUBLICAS):
                request.state.tenant_id = anunciado or None
                return await call_next(request)
            if not anunciado:
                return problem_response(
                    400,
                    "Bad Request",
                    detail=f"Header {TENANT_HEADER} é obrigatório (SDD §8).",
                    instance=request.url.path,
                )
            portador = usuario_do_authorization(request.headers.get("Authorization"))
            if portador is not None and portador.tenant_id != anunciado:
                return problem_response(
                    403,
                    "Forbidden",
                    detail=(
                        f"Header {TENANT_HEADER} diverge do escopo da credencial "
                        "(o tenant vem do portador autenticado — SDD §8)."
                    ),
                    instance=request.url.path,
                )
            request.state.tenant_id = portador.tenant_id if portador else anunciado
        return await call_next(request)

    register_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)

    @app.get("/healthz", tags=["ops"])
    async def healthz(
        db: Annotated[str, Depends(ping_db)],
        llm: Annotated[str, Depends(ping_llm)],
    ) -> dict[str, str]:
        """M0-A1: `{db: ok, llm: skip|ok}` em <2s com o compose de pé.

        `sha` (A22 — version-stamp): commit embutido na imagem via ARG/ENV GIT_SHA.
        O smoke pós-deploy do CI compara este valor com o SHA do run: divergiu, o
        deploy não chegou (o "deploy-fantasma" que enganou a validação em 2026-08-05).
        """
        return {"db": db, "llm": llm, "sha": os.environ.get("GIT_SHA", "dev")}

    # Persistência (A7 — §4/§10.9): DATABASE_URL setado no ambiente E alcançável
    # → repos SQL (TODOS os agregados §4.1 em Postgres); senão memória (dev sem
    # docker). Uma instância por app implementa todas as portas (§2.1).
    repositorio = criar_repositorio(os.environ.get("DATABASE_URL"))
    app.state.repositorio_os = repositorio
    if embedding is not None:  # A11: rotas e seed RAG usam o port injetado (§1.3.5)
        app.state.embedding = embedding

    if isinstance(repositorio, RepositorioSql):
        # A7 parte 2: com SQL o ledger `invocacao` tem FK para `agente` (§4.1) — o
        # roster/política v1 (idempotentes, ids uuid5 §11.4) entram já no boot para
        # nenhuma invocação chegar antes das linhas referenciadas. Em memória segue
        # a semeadura tardia das rotas do Ateliê (comportamento dos testes intacto).
        from adapters.atelie_seeds import semear_atelie, semear_politicas

        agora_boot = datetime.now(UTC)
        semear_atelie(repositorio, tenant_id=settings.default_tenant, agora=agora_boot)
        semear_politicas(repositorio, tenant_id=settings.default_tenant, agora=agora_boot)

    if demo if demo is not None else (settings.demo_mode and settings.app_env == "dev"):
        # Seeds DEMO_MODE (§11.4): OS-2026-0457 ponta a ponta. Idempotentes com
        # persistência SQL: ids uuid5 determinísticos + upsert por id (restart não
        # duplica) — import tardio evita custo quando demo está desligado.
        from adapters.demo_seeds import semear_demo

        semear_demo(repositorio, tenant_id=settings.default_tenant, agora=datetime.now(UTC))

        # A11 (§7.4/§11.4): base RAG `dicionario_dados` no boot demo. Embeddings via
        # EmbeddingPort (real por default; teste injeta fake); sem hub → a própria
        # seed PULA com log, sem quebrar o boot.
        from adapters.embedding.hubgpu import EmbeddingHubGPU
        from app.rag import semear_rag_demo

        semear_rag_demo(
            repositorio,
            embedding if embedding is not None else EmbeddingHubGPU(settings),
            tenant_id=settings.default_tenant,
        )

    return app


# Sem app de nível de módulo: importar `app.main` NÃO pode ter efeito colateral
# (com DATABASE_URL setado, o boot semeia roster/políticas — e no CI de integração as
# migrações ainda nem rodaram, quebrando a COLETA dos testes). Os processos usam a
# factory: `uvicorn app.main:create_app --factory` (Dockerfile e composes).
