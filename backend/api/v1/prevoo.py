"""Rotas do M9 (fatia 2) · Pré-voo & Drift T11 (SDD §5.4.5, §8-M9) — tag OpenAPI
`compilador` (mesmo módulo M9 da fatia 1).

`POST /preflight/{snapshot}?ambiente=` (bateria pass/warn/fail com evidência — fail
bloqueia apply) · `GET /drift` (job on-demand §5.4.5: retrieve → decompila → compara
hash/campos → grava `drift_check`; drift em PROD abre pendência automática bloqueante
— A4) · `POST /drift/{id}/resolver` (adopt/enforce/excecao; excecao EXIGE prazo).

**LLM PROIBIDO em todo este caminho (§5.4)** — pré-voo e drift são 100% determinísticos.
Erros: mapa RFC-7807 do M1 (RotaComErrosDeDominio); PrevooReprovado/DriftJaResolvido
(EstadoInvalido)→409 · ExcecaoSemPrazo (JustificativaObrigatoria)→422.
RBAC (§8-M0): pré-voo e resolução exigem analista|lider; `GET /drift` é monitor —
qualquer autenticado (a pendência automática é ação do SISTEMA, actor registrado).
SFMC atrás de porta (§2.1): mesma injeção `app.state.sfmc_port` da fatia 1.
"""

import uuid
from datetime import datetime
from typing import Any, Literal, cast

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

from api.v1.audiencia import get_read_model  # mesma instância/state key do M5
from api.v1.compilador import Ambiente, _relogio, get_sfmc
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    RotaComErrosDeDominio,
    Tenant,
    get_repositorio_os,
    get_servico_os,
)
from application.ports.repositorio_sync import RepositorioSync
from application.services.drift_service import ServicoDrift
from application.services.prevoo_service import ServicoPrevoo

# ------------------------------------------------------------------ Dependências


def get_servico_drift(request: Request) -> ServicoDrift:
    repositorio = cast(RepositorioSync, get_repositorio_os(request))
    servico_os = get_servico_os(get_repositorio_os(request))
    return ServicoDrift(repositorio, get_sfmc(request), _relogio, servico_os)


def get_servico_prevoo(request: Request) -> ServicoPrevoo:
    repositorio = cast(RepositorioSync, get_repositorio_os(request))
    return ServicoPrevoo(
        repositorio,
        get_sfmc(request),
        _relogio,
        get_read_model(request),
        get_servico_drift(request),
    )


# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class PreflightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID
    ambiente: str
    resultado: Literal["verde", "amarelo", "vermelho"]
    itens: list[dict[str, Any]]
    created_at: datetime | None


class DriftCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID
    recurso: str
    estado: Literal["em_sincronia", "drift_sfmc", "twin_a_frente"]
    diff: dict[str, Any]
    resolucao: Literal["adopt", "enforce", "excecao"] | None
    checked_at: datetime | None


class ResolverDriftIn(BaseModel):
    resolucao: Literal["adopt", "enforce", "excecao"]  # §4.1 drift_check.resolucao
    justificativa: str | None = None
    prazo_ate: datetime | None = None  # OBRIGATÓRIO quando excecao (§8-M9)


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaComErrosDeDominio, tags=["compilador"])


@router.post("/preflight/{snapshot_id}", status_code=201, response_model=PreflightOut)
async def executar_preflight(
    snapshot_id: uuid.UUID,
    tenant: Tenant,
    request: Request,
    user: Escritor,
    ambiente: Ambiente = Query(...),
) -> PreflightOut:
    """§8-M9: bateria pass/warn/fail com evidência (DEs/schema, freshness Hybris,
    opt-in, re-varredura last-mile das 7 listas via Guard, lint AMPscript, limites
    SFMC, drift=0, seed dry-run). FAIL ⇒ vermelho BLOQUEIA o apply; prod exige pré-voo
    executado e não-vermelho (§5.4.4)."""
    servico = get_servico_prevoo(request)
    run = await servico.executar(tenant, snapshot_id, ambiente, actor=user.email)
    return PreflightOut.model_validate(run)


@router.get("/drift", response_model=list[DriftCheckOut])
async def verificar_drift(
    tenant: Tenant,
    request: Request,
    user: Autenticado,
    ambiente: Ambiente | None = Query(default=None),
    os_id: uuid.UUID | None = Query(default=None),
) -> list[DriftCheckOut]:
    """§5.4.5 (job on-demand; o job de 30min reusa este caso de uso): retrieve do
    estado real → decompila → compara por hash/campos → grava `drift_check`. Drift em
    PROD abre pendência automática BLOQUEANTE na OS (A4)."""
    servico = get_servico_drift(request)
    checks = await servico.verificar(tenant, ambiente=ambiente, os_id=os_id, actor=user.email)
    return [DriftCheckOut.model_validate(c) for c in checks]


@router.post("/drift/{drift_id}/resolver", response_model=DriftCheckOut)
async def resolver_drift(
    drift_id: uuid.UUID,
    payload: ResolverDriftIn,
    tenant: Tenant,
    request: Request,
    user: Escritor,
) -> DriftCheckOut:
    """§8-M9: adopt (twin adota o estado real) | enforce (reconvergência via re-plan/
    apply idempotente §5.4.1-2) | excecao COM PRAZO. Sem drift pendente no ambiente ⇒
    a pendência automática (A4) é resolvida."""
    servico = get_servico_drift(request)
    check = servico.resolver(
        tenant,
        drift_id,
        resolucao=payload.resolucao,
        justificativa=payload.justificativa,
        prazo_ate=payload.prazo_ate,
        actor=user.email,
    )
    return DriftCheckOut.model_validate(check)
