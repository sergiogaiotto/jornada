"""Rotas do M12 (parte 1) · Ateliê T16 (SDD §8-M12, §7.1) — tag OpenAPI `atelie`.

CRUD agentes/skills (ciclo draft→em_revisao→publicada; skill nasce de um SKILL.md
canônico validado pelo parser §7.1) · `POST /skills/{id}/harness` (golden dataset +
judge 120b com rubrica fixa; LLMFake determinístico em teste §1.3.5; grava
`harness_run` com score POR DIMENSÃO) · `POST /skills/{id}/publicar` (A1: exige
harness VERDE — score ≥ 90 por dimensão §7.1 — senão 409; publicar NUNCA toca
`os.frozen` — A2: OS em voo permanece congelada) · `POST /skills/{id}/dry-run`
(lado a lado: MESMA entrada, versão atual vs candidata; nada persiste §1.1.3).

Erros: mapa RFC-7807 do M1 + traduções próprias: SkillMdInvalido→422 (com a lista
`erros` do parser) · LLMIndisponivel→503 degraded (§10.6 — harness/dry-run não são
caminho crítico). RBAC (§8-M0): CRUD/harness/dry-run exigem analista|lider;
PUBLICAR exige lider (portão de plataforma; admin sempre passa).
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from adapters.atelie_seeds import semear_atelie
from adapters.relogio import RelogioSistema
from api.v1.intake import get_llm, get_tracer
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    Tenant,
    _problema_de_dominio,
    get_repositorio_os,
)
from app.auth import Usuario, require_role
from app.config import get_settings
from app.errors import problem_response
from application.ports.llm import LLMIndisponivel
from application.ports.repositorio_atelie import RepositorioAtelie
from application.services.atelie_service import ServicoAtelie
from domain.atelie.erros import SkillMdInvalido
from domain.campanha.erros import ErroDominio


class RotaAtelie(APIRoute):
    """Traduções do M12 ANTES do mapa genérico do M1 (padrão M4/M5/M8/M10/M11)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except SkillMdInvalido as exc:  # parser §7.1: 422 com a lista de erros
                return problem_response(
                    422,
                    "Unprocessable Entity",
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra={"erros": exc.erros},
                )
            except LLMIndisponivel as exc:  # §10.6: harness/dry-run degradam
                return problem_response(
                    503,
                    "Service Unavailable",
                    detail=str(exc),
                    instance=request.url.path,
                    extra={"modo": "degraded"},
                )
            except ErroDominio as exc:
                return _problema_de_dominio(exc, request.url.path)

        return handler


# ------------------------------------------------------------------ Dependências
_relogio = RelogioSistema()


def get_repositorio_atelie(request: Request) -> RepositorioAtelie:
    """Mesma instância do repositório da OS (app.state — tipagem estrutural §2.1),
    SEMEADA na primeira passagem pelo Ateliê (§11.4: agentes+skills v1 publicadas +
    3 casos golden por agente-chave); idempotente."""
    repositorio = cast(RepositorioAtelie, get_repositorio_os(request))
    semear_atelie(
        repositorio,
        tenant_id=get_settings().default_tenant,
        agora=_relogio.agora(),
    )
    return repositorio


def get_servico_atelie(request: Request) -> ServicoAtelie:
    return ServicoAtelie(
        get_repositorio_atelie(request),
        _relogio,
        get_llm(request),
        get_tracer(request),
    )


Servico = Annotated[ServicoAtelie, Depends(get_servico_atelie)]
Publicador = Annotated[Usuario, Depends(require_role("lider"))]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class AgenteCriar(BaseModel):
    nome: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    camada: Literal["maestro", "triagem", "especialista"]  # §4.1
    etapa_workflow: str | None = Field(default=None, max_length=100)
    modelo_perfil: Literal["120b", "20b"] | None = None  # §3
    deterministico: bool = False  # guard=True (§7.2)


class SkillCriar(BaseModel):
    skill_md: str = Field(min_length=1)  # SKILL.md canônico §7.1 (validado no parser)


class DryRunIn(BaseModel):
    entrada: dict[str, Any]  # mesma entrada nos dois lados (§8-M12)


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaAtelie, tags=["atelie"])


@router.get("/agentes")
async def listar_agentes(tenant: Tenant, servico: Servico, _user: Autenticado) -> dict[str, Any]:
    """Roster do Ateliê (§7.2) com a versão publicada ATUAL e o resumo das skills."""
    return {"agentes": servico.listar_agentes(tenant)}


@router.post("/agentes", status_code=201)
async def criar_agente(
    payload: AgenteCriar, tenant: Tenant, servico: Servico, user: Escritor
) -> dict[str, Any]:
    return servico.criar_agente(
        tenant,
        nome=payload.nome,
        camada=payload.camada,
        etapa_workflow=payload.etapa_workflow,
        modelo_perfil=payload.modelo_perfil,
        deterministico=payload.deterministico,
        actor=user.email,
    )


@router.get("/agentes/{agente_id}/skills")
async def listar_skills(
    agente_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> dict[str, Any]:
    return {"skills": servico.listar_skills(tenant, agente_id)}


@router.post("/agentes/{agente_id}/skills", status_code=201)
async def criar_skill(
    agente_id: uuid.UUID,
    payload: SkillCriar,
    tenant: Tenant,
    servico: Servico,
    user: Escritor,
) -> dict[str, Any]:
    """Nova versão em `draft` a partir do SKILL.md canônico (parser valida campos
    §7.1; `name` deve ser o do agente; unique(agente_id, versao) §4.1)."""
    return servico.criar_skill(tenant, agente_id, skill_md=payload.skill_md, actor=user.email)


@router.get("/skills/{skill_id}")
async def obter_skill(
    skill_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> dict[str, Any]:
    return servico.obter_skill(tenant, skill_id)


@router.put("/skills/{skill_id}")
async def atualizar_skill(
    skill_id: uuid.UUID,
    payload: SkillCriar,
    tenant: Tenant,
    servico: Servico,
    user: Escritor,
) -> dict[str, Any]:
    """Edita o SKILL.md — SÓ em `draft` (em revisão o harness julga texto estável)."""
    return servico.atualizar_skill(tenant, skill_id, skill_md=payload.skill_md, actor=user.email)


@router.post("/skills/{skill_id}/revisao")
async def enviar_para_revisao(
    skill_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Escritor
) -> dict[str, Any]:
    """draft → em_revisao (ciclo §8-M12); conteúdo congela para o julgamento."""
    return servico.enviar_para_revisao(tenant, skill_id, actor=user.email)


@router.post("/skills/{skill_id}/harness", status_code=201)
async def rodar_harness(
    skill_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Escritor
) -> dict[str, Any]:
    """Roda o golden dataset (§4.1 harness_case) com judge 120b (rubrica fixa §7.1)
    e grava `harness_run` com score POR DIMENSÃO — o portão da publicação (A1)."""
    return servico.rodar_harness(tenant, skill_id, actor=user.email)


@router.post("/skills/{skill_id}/publicar")
async def publicar_skill(
    skill_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Publicador
) -> dict[str, Any]:
    """A1: exige `em_revisao` + último harness_run VERDE (passou, score ≥ 90 por
    dimensão §7.1) sobre o skill_md ATUAL — senão 409. A2: NÃO toca `os.frozen`
    (OS em voo segue com as versões congeladas no GO §8-M4)."""
    return servico.publicar(tenant, skill_id, actor=user.email)


@router.post("/skills/{skill_id}/dry-run")
async def dry_run(
    skill_id: uuid.UUID,
    payload: DryRunIn,
    tenant: Tenant,
    servico: Servico,
    _user: Escritor,
) -> dict[str, Any]:
    """Lado a lado (§8-M12): MESMA entrada na versão publicada atual e na candidata;
    nada persiste; a decisão de publicar continua humana (§1.1.3)."""
    return servico.dry_run(tenant, skill_id, entrada=payload.entrada)
