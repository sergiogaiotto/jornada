"""Rotas do M3 · Intake & Consultor / T2 (SDD §8-M3) — tag OpenAPI `intake`.

`POST /pedidos` (criação NA APP — o Portal do Solicitante foi aposentado; o token de
portal segue aceito como auth de link) · `POST /pedidos/{id}/mensagem` (conversa com o
consultor; devolve conteúdo atualizado + completude + faltantes) ·
`POST /pedidos/{id}/converter` (exige completude=100 → cria OS com briefing `inferido:true`)
· CRUD (emenda §8-M3): `GET /pedidos` (resumo do tenant; `?arquivados=true` inclui os
arquivados) · `GET /pedidos/{id}` · `PATCH /pedidos/{id}/campos` (edição manual direta →
`inferido:false`, completude por código) · `POST /pedidos/{id}/arquivar` (soft; convertido
→ 409) · `GET /os/{id}/briefing` · `PATCH /os/{id}/briefing/{campo}` (confirmar/editar).

Erros: domínio → RFC-7807 via `RotaComErrosDeDominio` (intake herda o mapa:
ConversaoIncompleta/PedidoJaConvertido/PedidoArquivado→409, CampoBriefingDesconhecido→404);
`LLMIndisponivel` → 503 `degraded` (§10.6) traduzido aqui. RBAC: pedidos/mensagem
aceitam token de portal (get_portador); GET lista/detalhe exigem login pleno; converter,
PATCH campos, arquivar e PATCH briefing exigem analista|lider.
LLM: SEMPRE via LLMPort — em teste o app injeta o fake em `app.state.llm` (§1.3.5).
"""

import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from adapters.embedding.hubgpu import EmbeddingHubGPU
from adapters.llm.hubgpu import LLMHubGPU
from adapters.observabilidade.langfuse import TracerLangfuse
from adapters.relogio import RelogioSistema
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    OsOut,
    RotaComErrosDeDominio,
    Tenant,
    get_repositorio_os,
    get_servico_os,
)
from app.auth import Usuario, get_portador
from app.config import get_settings
from app.errors import problem_response
from application.ports.embedding import EmbeddingPort
from application.ports.llm import LLMIndisponivel, LLMPort
from application.ports.observabilidade import TracerPort
from application.ports.repositorio_evidencia import RepositorioEvidencia
from application.ports.repositorio_intake import RepositorioIntake
from application.ports.repositorio_os import RepositorioOs
from application.services.consultor_service import ServicoConsultor
from application.services.os_service import ServicoOs
from application.services.retriever_service import RetrieverService


class RotaIntake(RotaComErrosDeDominio):
    """Herda o mapa de erros de domínio e acrescenta LLMIndisponivel → 503 degraded (§10.6)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except LLMIndisponivel as exc:
                return problem_response(
                    503,
                    "Service Unavailable",
                    detail=str(exc),
                    instance=request.url.path,
                    extra={"modo": "degraded"},  # UI oferece modo manual (§10.6)
                )

        return handler


# ------------------------------------------------------------------ Dependências
_relogio = RelogioSistema()


def get_llm(request: Request) -> LLMPort:
    """LLM atrás de porta (§2.1). Testes SEMPRE injetam o fake em app.state.llm (§1.3.5);
    fora de teste, o adapter real fica atrás de LLM_DEGRADED_MODE (§10.6)."""
    llm = getattr(request.app.state, "llm", None)
    if llm is None:
        llm = LLMHubGPU(get_settings())
        request.app.state.llm = llm
    return llm


def get_tracer(request: Request) -> TracerPort:
    """Tracer Langfuse fire-and-forget (§10.8); LANGFUSE_ENABLED=false → no-op."""
    tracer = getattr(request.app.state, "tracer", None)
    if tracer is None:
        tracer = TracerLangfuse(get_settings())
        request.app.state.tracer = tracer
    return tracer


def get_embedding(request: Request) -> EmbeddingPort:
    """Embeddings atrás de porta (A11 — §2.1). Testes SEMPRE injetam o fake em
    app.state.embedding (§1.3.5); fora de teste, o adapter real fica atrás de
    LLM_DEGRADED_MODE (§10.6) — mesmo padrão de get_llm."""
    embedding = getattr(request.app.state, "embedding", None)
    if embedding is None:
        embedding = EmbeddingHubGPU(get_settings())
        request.app.state.embedding = embedding
    return embedding


def get_retriever(request: Request) -> RetrieverService:
    """Retriever §7.4: top-k=8 sobre `agente_evidence`, mesma instância de repositório
    do app (implementa RepositorioEvidencia — tipagem estrutural §2.1)."""
    repositorio = get_repositorio_os(request)
    return RetrieverService(cast(RepositorioEvidencia, repositorio), get_embedding(request))


def get_servico_consultor(
    request: Request, servico_os: Annotated[ServicoOs, Depends(get_servico_os)]
) -> ServicoConsultor:
    """Mesma instância de repositório da OS (app.state) — RepositorioOsMemoria implementa
    RepositorioIntake e RepositorioOs (tipagem estrutural §2.1)."""
    repositorio: RepositorioOs = get_repositorio_os(request)
    return ServicoConsultor(
        cast(RepositorioIntake, repositorio),  # mesma instância implementa ambas as portas
        repositorio,
        _relogio,
        servico_os,
        get_llm(request),
        get_tracer(request),
        retriever=get_retriever(request),  # A11: precedentes citáveis (§7.4)
    )


Servico = Annotated[ServicoConsultor, Depends(get_servico_consultor)]
Portador = Annotated[Usuario, Depends(get_portador)]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class PedidoCriar(BaseModel):
    solicitante: dict[str, Any]  # jsonb not null (§4.1) — ex.: {nome, area}
    conteudo: dict[str, Any] = Field(default_factory=dict)  # plano: {campo: valor}


EstadoPedido = Literal["rascunho", "completo", "convertido", "arquivado"]  # ESTADOS_PEDIDO §4.1


class PedidoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: str
    solicitante: dict[str, Any]
    conteudo: dict[str, Any]
    completude: float
    faltantes: list[str]
    estado: EstadoPedido
    os_id: uuid.UUID | None
    updated_at: datetime | None


class PedidoResumo(BaseModel):
    """Item de `GET /pedidos` (emenda §8-M3): resumo SEM `conteudo` (a lista da app
    mostra fila de trabalho; o detalhe vem em `GET /pedidos/{id}`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    solicitante: dict[str, Any]
    completude: float
    faltantes: list[str]
    estado: EstadoPedido
    os_id: uuid.UUID | None
    updated_at: datetime | None


class MensagemIn(BaseModel):
    mensagem: str = Field(min_length=1)


class MensagemOut(BaseModel):
    """Contrato §8-M3: conteúdo atualizado + completude + faltantes (+ resposta do agente)."""

    resposta: str
    conteudo: dict[str, Any]
    completude: float
    faltantes: list[str]
    estado: EstadoPedido


class ConverterIn(BaseModel):
    nome: str | None = None  # None → objetivo do briefing vira nome da OS
    tshirt: Literal["P", "M", "G", "GG"] = "M"


class BriefingOut(BaseModel):
    os_id: uuid.UUID
    briefing: dict[str, Any]


class BriefingPatch(BaseModel):
    """Sem `valor` → apenas confirma o campo (inferido:false); com `valor` → edita."""

    valor: Any = None


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaIntake, tags=["intake"])


@router.post("/pedidos", status_code=201, response_model=PedidoOut)
async def criar_pedido(
    payload: PedidoCriar, tenant: Tenant, servico: Servico, _user: Portador
) -> PedidoOut:
    """Portal do Solicitante (via link com token). Completude/faltantes são derivados
    por código determinístico já na criação (§8-M3)."""
    pedido = servico.criar_pedido(
        tenant, solicitante=payload.solicitante, conteudo=payload.conteudo
    )
    return PedidoOut.model_validate(pedido)


@router.get("/pedidos", response_model=list[PedidoResumo])
async def listar_pedidos(
    tenant: Tenant, servico: Servico, _user: Autenticado, arquivados: bool = False
) -> list[PedidoResumo]:
    """CRUD (emenda §8-M3): fila de trabalho da app, mais recente primeiro; arquivados
    (soft) ficam fora por padrão — `?arquivados=true` os inclui. Login pleno."""
    pedidos = servico.listar_pedidos(tenant, incluir_arquivados=arquivados)
    return [PedidoResumo.model_validate(pedido) for pedido in pedidos]


@router.get("/pedidos/{pedido_id}", response_model=PedidoOut)
async def obter_pedido(
    pedido_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> PedidoOut:
    """Detalhe completo (com `conteudo`); arquivado continua legível (soft)."""
    return PedidoOut.model_validate(servico.obter_pedido(tenant, pedido_id))


@router.patch("/pedidos/{pedido_id}/campos", response_model=PedidoOut)
async def editar_campos_do_pedido(
    pedido_id: uuid.UUID,
    payload: dict[str, Any],
    tenant: Tenant,
    servico: Servico,
    user: Escritor,
) -> PedidoOut:
    """Edição manual direta `{campo: valor}` — cada campo vira `inferido:false`;
    completude/faltantes recalculados por CÓDIGO (§8-M3). Convertido/arquivado → 409."""
    pedido = servico.editar_campos(tenant, pedido_id, payload, actor=user.email)
    return PedidoOut.model_validate(pedido)


@router.post("/pedidos/{pedido_id}/arquivar", response_model=PedidoOut)
async def arquivar_pedido(
    pedido_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Escritor
) -> PedidoOut:
    """Arquivamento SOFT e idempotente; convertido → 409 (o rastro pedido→OS é
    história de governança, não se arquiva)."""
    return PedidoOut.model_validate(servico.arquivar(tenant, pedido_id, actor=user.email))


@router.post("/pedidos/{pedido_id}/mensagem", response_model=MensagemOut)
async def mensagem_ao_consultor(
    pedido_id: uuid.UUID, payload: MensagemIn, tenant: Tenant, servico: Servico, user: Portador
) -> MensagemOut:
    """Conversa com o consultor (LLM 120b — roster §7.2). Inferências entram com
    `inferido:true` + evidências; ledger `invocacao` + trace Langfuse (A3, §10.8)."""
    pedido, resposta = servico.conversar(
        tenant, pedido_id, mensagem=payload.mensagem, portador_id=user.id
    )
    return MensagemOut(
        resposta=resposta,
        conteudo=pedido.conteudo,
        completude=pedido.completude,
        faltantes=pedido.faltantes,
        estado=pedido.estado,  # type: ignore[arg-type]  # ESTADOS_PEDIDO (§4.1)
    )


@router.post("/pedidos/{pedido_id}/converter", status_code=201, response_model=OsOut)
async def converter_pedido(
    pedido_id: uuid.UUID, payload: ConverterIn, tenant: Tenant, servico: Servico, user: Escritor
) -> OsOut:
    """A2: exige completude=100 (409 com faltantes no motivo). Cria a OS com briefing
    pré-preenchido; campos inferidos permanecem `inferido:true` até confirmação."""
    os_ = servico.converter(
        tenant,
        pedido_id,
        created_by=user.id,
        actor=user.email,
        nome=payload.nome,
        tshirt=payload.tshirt,
    )
    return OsOut.model_validate(os_)


@router.get("/os/{os_id}/briefing", response_model=BriefingOut)
async def obter_briefing(
    os_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> BriefingOut:
    return BriefingOut(os_id=os_id, briefing=servico.obter_briefing(tenant, os_id))


@router.patch("/os/{os_id}/briefing/{campo}", response_model=BriefingOut)
async def editar_briefing(
    os_id: uuid.UUID,
    campo: str,
    payload: BriefingPatch,
    tenant: Tenant,
    servico: Servico,
    user: Escritor,
) -> BriefingOut:
    """Confirmar (sem valor) ou editar (com valor) um campo — vira `inferido:false`."""
    extras: dict[str, Any] = {}
    if "valor" in payload.model_fields_set:
        extras["valor"] = payload.valor
    briefing = servico.editar_briefing(tenant, os_id, campo, actor=user.email, **extras)
    return BriefingOut(os_id=os_id, briefing=briefing)
