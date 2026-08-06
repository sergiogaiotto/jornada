"""Rotas do M6 · Criativo / T6 (SDD §8-M6) — tag OpenAPI `criativo`.

`POST /os/{id}/criativos/gerar` (matriz canal×variante a partir do KV master —
pipeline visual/copy/content via LLMPort) · `PATCH /criativos/{id}/celula`
(aprovar/revisar por célula — A3: só usuário analista+) · `PUT /criativos/{id}/kv-master`
(edita o KV master; células derivadas → `adaptado_revisar` — A2) ·
`GET /os/{id}/criativos/kv-padrao` (KV de partida DERIVADO do briefing — determinístico,
ZERO LLM; A8 do UAT 2026-08-05). Validadores
DETERMINÍSTICOS: SMS≤160 (A1), template WhatsApp aprovado, termos proibidos de
linguagem; o LLM 20b só ACRESCENTA warnings ("regras + warn LLM").

Erros: domínio → RFC-7807 (mapa do M1; CelulaInexistente→404, AprovacaoRequerHumano→403
por herança) + traduções deste router: CriativoInvalido→422 com `problemas` (A1);
SaidaDoCriativoInvalida→422; LLMIndisponivel→503 degraded (§10.6). RBAC (§8-M0):
mutações exigem analista|lider — inclusive a aprovação de célula (A3).
"""

import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from adapters.relogio import RelogioSistema
from api.v1.intake import get_llm, get_tracer
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    Tenant,
    _problema_de_dominio,
    get_repositorio_os,
    get_servico_os,
)
from app.errors import problem_response
from application.ports.llm import LLMIndisponivel
from application.ports.repositorio_criativo import RepositorioCriativo
from application.services.criativo_service import ServicoCriativo
from application.services.os_service import ServicoOs
from domain.campanha.erros import ErroDominio
from domain.criativo.erros import CriativoInvalido, SaidaDoCriativoInvalida
from domain.criativo.modelos import CANAIS_CRIATIVO, VARIANTES_DEFAULT


class RotaCriativo(APIRoute):
    """Traduções do M6 ANTES do mapa genérico do M1 (padrão da RotaAudiencia/M5)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except CriativoInvalido as exc:  # A1: validadores determinísticos → 422
                return problem_response(
                    422,
                    "Unprocessable Entity",
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra={"problemas": exc.problemas},
                )
            except SaidaDoCriativoInvalida as exc:
                return problem_response(
                    422, "Unprocessable Entity", detail=exc.motivo, instance=request.url.path
                )
            except LLMIndisponivel as exc:  # §10.6
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


def get_servico_criativo(
    request: Request, servico_os: Annotated[ServicoOs, Depends(get_servico_os)]
) -> ServicoCriativo:
    """Mesma instância de repositório da OS (app.state) — RepositorioOsMemoria implementa
    todas as portas (tipagem estrutural §2.1); o cast só informa o mypy."""
    repositorio = get_repositorio_os(request)
    return ServicoCriativo(
        cast(RepositorioCriativo, repositorio),
        _relogio,
        servico_os,
        get_llm(request),
        get_tracer(request),
    )


Servico = Annotated[ServicoCriativo, Depends(get_servico_criativo)]

Canal = Literal["email", "sms", "push", "whatsapp"]  # CANAIS_CRIATIVO (§8-M6)

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class CelulaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    canal: Canal
    variante: str
    conteudo: dict[str, Any]
    estado: Literal["gerado", "aprovado", "revisar", "adaptado_revisar"]
    aprovada_por: uuid.UUID | None
    aprovada_em: datetime | None
    observacao: str | None


class CriativoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    os_id: uuid.UUID
    kv_master: dict[str, Any]
    kv_master_ref: str | None
    celulas: list[CelulaOut]
    created_at: datetime | None
    updated_at: datetime | None


class GerarCriativosIn(BaseModel):
    kv_master: dict[str, Any] = Field(min_length=1)  # matriz nasce DO KV master (§8-M6)
    canais: list[Canal] = Field(default_factory=lambda: cast("list[Canal]", list(CANAIS_CRIATIVO)))
    variantes: list[str] = Field(default_factory=lambda: list(VARIANTES_DEFAULT), min_length=1)
    instrucoes: str | None = None


class GerarCriativosOut(BaseModel):
    """Prévia dos agentes do T6 (§1.1.3): toda célula nasce `gerado` — aprovação é
    humana (A3). `avisos` = warn LLM não bloqueante ("regras + warn LLM")."""

    criativo: CriativoOut
    avisos: list[str]
    via_ai: bool = True
    invocacao_ids: list[uuid.UUID]


class CelulaPatch(BaseModel):
    canal: Canal
    variante: str = Field(min_length=1)
    acao: Literal["aprovar", "revisar"]
    observacao: str | None = None


class KvMasterIn(BaseModel):
    kv_master: dict[str, Any] = Field(min_length=1)


class KvMasterOut(BaseModel):
    criativo: CriativoOut
    avisos: list[str]  # warn LLM (best-effort — vazio com hub fora, §10.6)


class KvPadraoOut(BaseModel):
    """KV de PARTIDA do Estúdio (A8) — derivado do briefing por CÓDIGO (`via_ai:false`).

    `derivado_de` = campos do briefing que alimentaram o default (rastro honesto);
    `suficiente:false` → o KV veio com placeholders "(defina …)" para o humano preencher.
    """

    os_id: uuid.UUID
    kv_master: dict[str, str]
    derivado_de: list[str]
    suficiente: bool
    via_ai: bool = False  # determinístico: nada de LLM aqui (§1.1.3)


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaCriativo, tags=["criativo"])


@router.get("/os/{os_id}/criativos/kv-padrao", response_model=KvPadraoOut)
async def kv_padrao(
    os_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> KvPadraoOut:
    """KV master de partida DERIVADO do briefing da OS — determinístico, ZERO LLM e sem
    persistir nada (A8 do UAT 2026-08-05: o Estúdio abria com copy fixa da campanha de
    franquia, que vazava para OS de outro tema). Briefing insuficiente → placeholders
    "(defina o Key Visual)" — nunca copy de outra campanha (§1.3.5)."""
    kv_master, derivado_de, tem_briefing = servico.kv_master_padrao(tenant, os_id)
    return KvPadraoOut(
        os_id=os_id, kv_master=kv_master, derivado_de=derivado_de, suficiente=tem_briefing
    )


@router.post("/os/{os_id}/criativos/gerar", status_code=201, response_model=GerarCriativosOut)
async def gerar_criativos(
    os_id: uuid.UUID, payload: GerarCriativosIn, tenant: Tenant, servico: Servico, user: Escritor
) -> GerarCriativosOut:
    """Pipeline visual→copy→content (LLM 120b — roster §7.2) gera a matriz como
    PRÉVIA (§1.1.3); validadores determinísticos reprovam antes de persistir (A1);
    ledger `invocacao` via_ai por chamada + traces Langfuse (§10.8)."""
    criativo, avisos, invocacoes = servico.gerar(
        tenant,
        os_id,
        kv_master=payload.kv_master,
        canais=list(payload.canais),
        variantes=list(payload.variantes),
        instrucoes=payload.instrucoes,
        portador_id=user.id,
    )
    return GerarCriativosOut(
        criativo=CriativoOut.model_validate(criativo),
        avisos=avisos,
        invocacao_ids=[i.id for i in invocacoes],
    )


@router.patch("/criativos/{criativo_id}/celula", response_model=CriativoOut)
async def decidir_celula(
    criativo_id: uuid.UUID, payload: CelulaPatch, tenant: Tenant, servico: Servico, user: Escritor
) -> CriativoOut:
    """Aprovar/revisar POR CÉLULA — A3: `aprovado` é ato de usuário analista+ (RBAC
    nesta rota + regra pura no domínio); agente jamais aprova."""
    criativo = servico.decidir_celula(
        tenant,
        criativo_id,
        canal=payload.canal,
        variante=payload.variante,
        acao=payload.acao,
        observacao=payload.observacao,
        por=user.id,
        actor=user.email,
    )
    return CriativoOut.model_validate(criativo)


@router.put("/criativos/{criativo_id}/kv-master", response_model=KvMasterOut)
async def editar_kv_master(
    criativo_id: uuid.UUID, payload: KvMasterIn, tenant: Tenant, servico: Servico, user: Escritor
) -> KvMasterOut:
    """A2: edição do KV master marca TODAS as células derivadas `adaptado_revisar`
    (aprovações caem — novo olhar humano); compliance determinístico valida o KV."""
    criativo, avisos = servico.editar_kv_master(
        tenant, criativo_id, kv_master=payload.kv_master, portador_id=user.id, actor=user.email
    )
    return KvMasterOut(criativo=CriativoOut.model_validate(criativo), avisos=avisos)
