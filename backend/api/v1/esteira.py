"""Rotas do M2 · Esteira de Produção ex-Hike / T4a (SDD §8-M2) — tag OpenAPI `esteira`.

`GET/PATCH /os/{id}/workflow` (7 etapas, checklist, dependências) ·
`POST /admin/hike/import` (export JSON do Hike → OS + etapas com `hike_ref`;
log em `hike_import_log`). Erros de domínio → RFC-7807 via `RotaComErrosDeDominio`
(esteira herda o mapa: DependenciaInsatisfeita/TransicaoEtapaIlegal→409,
ChecklistItemDesconhecido→404). RBAC (§8-M0): leitura autenticada; PATCH exige
analista|lider; import Hike é rota /admin → papel admin.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, cast, get_args

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from adapters.relogio import RelogioSistema
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    RotaComErrosDeDominio,
    Tenant,
    get_repositorio_os,
    get_servico_os,
)
from app.auth import Usuario, require_role
from application.ports.repositorio_workflow import RepositorioWorkflow
from application.services.os_service import ServicoOs
from application.services.workflow_service import ServicoWorkflow
from domain.esteira.modelos import ETAPAS

# ------------------------------------------------------------------ Dependências
_relogio = RelogioSistema()


def get_servico_workflow(
    request: Request, servico_os: Annotated[ServicoOs, Depends(get_servico_os)]
) -> ServicoWorkflow:
    """Mesma instância de repositório da OS (app.state) — RepositorioOsMemoria implementa
    ambas as portas (RepositorioOs e RepositorioWorkflow); o cast só informa o mypy."""
    repositorio = cast(RepositorioWorkflow, get_repositorio_os(request))
    return ServicoWorkflow(repositorio, _relogio, servico_os)


Servico = Annotated[ServicoWorkflow, Depends(get_servico_workflow)]
Admin = Annotated[Usuario, Depends(require_role("admin"))]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)
NomeEtapa = Literal[
    "briefing", "discovery", "audiencia", "criativos", "configuracao", "disparo", "acompanhamento"
]
EstadoEtapa = Literal["pendente", "em_andamento", "concluida", "bloqueada"]
assert set(get_args(NomeEtapa)) == set(ETAPAS)  # contrato da API = domínio (§4.1)


class ChecklistItemOut(BaseModel):
    item: str
    feito: bool
    por: str | None = None
    em: datetime | None = None


class EtapaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    os_id: uuid.UUID
    ordem: int
    nome: str
    responsavel: uuid.UUID | None
    sla_dias: int | None
    estado: str
    checklist: list[ChecklistItemOut]
    dependencias: list[str]
    hike_ref: dict[str, Any] | None


class WorkflowOut(BaseModel):
    os_id: uuid.UUID
    etapas: list[EtapaOut]


class ChecklistMarcacao(BaseModel):
    item: str = Field(min_length=1)
    feito: bool = True


class WorkflowPatch(BaseModel):
    etapa: NomeEtapa
    estado: EstadoEtapa | None = None
    responsavel: uuid.UUID | None = None
    sla_dias: int | None = Field(default=None, ge=0)
    checklist: list[ChecklistMarcacao] | None = None


class HikeChecklistItemIn(BaseModel):
    item: str = Field(min_length=1)
    feito: bool = False
    por: str | None = None
    em: str | None = None  # ISO-8601 do export; preservado como veio (jsonb §4.1)


class HikeEtapaIn(BaseModel):
    nome: NomeEtapa
    estado: EstadoEtapa = "pendente"
    sla_dias: int | None = Field(default=None, ge=0)
    checklist: list[HikeChecklistItemIn] | None = None


class HikeCardIn(BaseModel):
    card_id: str = Field(min_length=1)
    titulo: str = Field(min_length=1)
    tshirt: Literal["P", "M", "G", "GG"] = "M"
    url: str | None = None
    briefing: dict[str, Any] = Field(default_factory=dict)
    etapas: list[HikeEtapaIn] = Field(default_factory=list)
    historico: list[dict[str, Any]] = Field(default_factory=list)


class HikeImportIn(BaseModel):
    """Export JSON do Hike (fixture de referência: mocks/seeds/hike_export.json)."""

    origem: str | None = None
    exportado_em: datetime | None = None
    cards: list[HikeCardIn] = Field(min_length=1)


class HikeImportResultado(BaseModel):
    card_id: str
    status: Literal["ok", "duplicado"]
    os_id: uuid.UUID | None = None
    codigo: str | None = None


class HikeImportOut(BaseModel):
    importados: int
    duplicados: int
    resultados: list[HikeImportResultado]


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaComErrosDeDominio, tags=["esteira"])


def _workflow_out(os_id: uuid.UUID, etapas: list[Any]) -> WorkflowOut:
    return WorkflowOut(os_id=os_id, etapas=[EtapaOut.model_validate(e) for e in etapas])


@router.get("/os/{os_id}/workflow", response_model=WorkflowOut)
async def obter_workflow(
    os_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> WorkflowOut:
    """As 7 etapas da esteira (materializadas na primeira consulta — A1)."""
    return _workflow_out(os_id, servico.obter_workflow(tenant, os_id))


@router.patch("/os/{os_id}/workflow", response_model=WorkflowOut)
async def atualizar_workflow(
    os_id: uuid.UUID, payload: WorkflowPatch, tenant: Tenant, servico: Servico, user: Escritor
) -> WorkflowOut:
    """Atualiza UMA etapa (estado/responsável/SLA/checklist); dependência insatisfeita
    impede `em_andamento` (A2 → 409). Devolve o workflow completo."""
    etapas = servico.atualizar_etapa(
        tenant,
        os_id,
        payload.etapa,
        estado=payload.estado,
        responsavel=payload.responsavel,
        sla_dias=payload.sla_dias,
        checklist=[m.model_dump() for m in payload.checklist] if payload.checklist else None,
        actor=user.email,
    )
    return _workflow_out(os_id, etapas)


@router.post("/admin/hike/import", status_code=201, response_model=HikeImportOut)
async def importar_hike(
    payload: HikeImportIn, tenant: Tenant, servico: Servico, user: Admin
) -> HikeImportOut:
    """Import do export JSON do Hike: cria OS + 7 etapas com `hike_ref`, preserva o
    histórico (outbox `hike.card_imported`) e registra `hike_import_log` (A3)."""
    resultados = servico.importar_hike(
        tenant,
        [card.model_dump() for card in payload.cards],
        created_by=user.id,
        actor=user.email,
    )
    saida = [HikeImportResultado.model_validate(r) for r in resultados]
    return HikeImportOut(
        importados=sum(1 for r in saida if r.status == "ok"),
        duplicados=sum(1 for r in saida if r.status == "duplicado"),
        resultados=saida,
    )
