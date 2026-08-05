"""Rotas do M9 (fatia 1) · Compilador plan/apply T11 (SDD §5.4, §8-M9) — tag OpenAPI
`compilador`.

`POST /snapshots/{id}/plan?ambiente=` · `POST /snapshots/{id}/apply?ambiente=`
(exige plan prévio A1 + aprovação §5.4.4 + certificado válido M5-A3 + pré-voo sem FAIL
— obrigatório em prod §5.4.4) · `GET /sync-runs/{id}`. Pré-voo (`POST /preflight/...`)
e drift (`GET /drift`, `POST /drift/{id}/resolver`) estão na fatia 2 (api/v1/prevoo.py).

**LLM PROIBIDO em todo este caminho (§5.4)** — compilador é 100% determinístico.
Erros: mapa RFC-7807 do M1 + GrafoNaoCompilavel→422 (nó de exceção §5.2);
SemPlanPrevio/AprovacaoNecessaria/CertificadoNecessario herdam EstadoInvalido→409.
RBAC (§8-M0): mutações exigem analista|lider; leitura, qualquer autenticado.
SFMC atrás de porta (§2.1): dev/prod usam o adapter `SfmcHttp` (URLs `SFMC_*` §3.1);
teste injeta `app.state.sfmc` com transport ASGI (mock in-process — §1.3.5).
"""

import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict

from adapters.relogio import RelogioSistema
from adapters.sfmc.cliente import SfmcHttp
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    Tenant,
    _problema_de_dominio,
    get_repositorio_os,
)
from app.config import get_settings
from app.errors import problem_response
from application.ports.repositorio_sync import RepositorioSync
from application.ports.sfmc import SFMCPort
from application.services.compilador_service import ServicoCompilador
from domain.campanha.erros import ErroDominio
from domain.jornada.erros import GrafoNaoCompilavel


class RotaCompilador(APIRoute):
    """GrafoNaoCompilavel→422 com nós apontados ANTES do mapa genérico (padrão M7)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except GrafoNaoCompilavel as exc:
                return problem_response(
                    422,
                    "Unprocessable Entity",
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra={"nos": exc.nos},
                )
            except ErroDominio as exc:
                return _problema_de_dominio(exc, request.url.path)

        return handler


# ------------------------------------------------------------------ Dependências
_relogio = RelogioSistema()


def get_sfmc(request: Request) -> SFMCPort:
    """Porta SFMC por app (`app.state.sfmc_port`): teste injeta o adapter com
    transport ASGI (mock-sfmc IN-PROCESS §1.3.5); dev/prod criam das URLs §3.1."""
    sfmc = getattr(request.app.state, "sfmc_port", None)
    if sfmc is None:
        sfmc = SfmcHttp(get_settings())
        request.app.state.sfmc_port = sfmc
    return cast(SFMCPort, sfmc)


def get_servico_compilador(request: Request) -> ServicoCompilador:
    """Mesma instância de repositório (app.state) — RepositorioOsMemoria implementa
    todas as portas (tipagem estrutural §2.1); o cast só informa o mypy. Orçamento:
    `SFMC_API_BUDGET_PER_APPLY` (§3.1), sobreponível por `app.state.sfmc_api_budget`
    (teste do rollback §5.4.2)."""
    repositorio = cast(RepositorioSync, get_repositorio_os(request))
    orcamento = getattr(
        request.app.state, "sfmc_api_budget", get_settings().sfmc_api_budget_per_apply
    )
    return ServicoCompilador(repositorio, get_sfmc(request), _relogio, int(orcamento))


# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)
Ambiente = Literal["homolog", "prod"]


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID
    ambiente: str
    fase: Literal["plan", "apply"]
    plano: list[dict[str, Any]] | None
    resultado: dict[str, Any] | None
    estado: Literal["pendente", "ok", "parcial", "revertido", "falhou"]
    api_calls: int
    created_at: datetime | None


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaCompilador, tags=["compilador"])


@router.post("/snapshots/{snapshot_id}/plan", status_code=201, response_model=SyncRunOut)
async def plan_snapshot(
    snapshot_id: uuid.UUID,
    tenant: Tenant,
    request: Request,
    user: Escritor,
    ambiente: Ambiente = Query(...),
) -> SyncRunOut:
    """§5.4.1: resolve dependências (DEs → EventDefs → Assets → Journey → Automations)
    e gera `{recurso, acao criar|alterar|manter|destruir, aviso}` com externalKey
    idempotente `jrn-{hash[0:12]}-{noId}`; avisos destrutivos obrigatórios (§5.4.3).
    Persistido em `sync_run` (fase=plan)."""
    servico = get_servico_compilador(request)
    run = await servico.plan(tenant, snapshot_id, ambiente, actor=user.email)
    return SyncRunOut.model_validate(run)


@router.post("/snapshots/{snapshot_id}/apply", status_code=201, response_model=SyncRunOut)
async def apply_snapshot(
    snapshot_id: uuid.UUID,
    tenant: Tenant,
    request: Request,
    user: Escritor,
    ambiente: Ambiente = Query(...),
) -> SyncRunOut:
    """§5.4.2/§5.4.4: exige plan prévio (A1: 409), aprovação válida e certificado
    não expirado (M5-A3). Idempotente por externalKey (A3: re-apply do mesmo hash →
    0 mutações); retry/backoff + orçamento; falha → rollback compensatório. Tudo em
    `sync_run` + `resource_registry`; sucesso emite `sync.applied` (§2.3)."""
    servico = get_servico_compilador(request)
    run = await servico.apply(tenant, snapshot_id, ambiente, actor=user.email)
    return SyncRunOut.model_validate(run)


@router.get("/sync-runs/{sync_run_id}", response_model=SyncRunOut)
async def obter_sync_run(
    sync_run_id: uuid.UUID, tenant: Tenant, request: Request, _user: Autenticado
) -> SyncRunOut:
    """Log do plan/apply (§5.4.2: "tudo logado em sync_run") — escopo do tenant."""
    servico = get_servico_compilador(request)
    return SyncRunOut.model_validate(servico.obter_sync_run(tenant, sync_run_id))
