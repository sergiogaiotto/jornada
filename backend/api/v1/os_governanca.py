"""Rotas do M1 · Núcleo OS/governança (SDD §8-M1) — tag OpenAPI `os`.

`POST/GET /os` · `GET /os/{id}` · `POST /os/{id}/fase` (só transições legais; portões
checados) · `POST /os/{id}/pendencias` · `GET /os/{id}/pendencias` (emenda B01 — a UI
recupera o que está aberto após reload) · `POST /pendencias/{id}/resolver|aceitar` ·
`GET /os/{id}/saude` — saúde é DERIVADA (view §4.1): nenhuma rota de escrita (A3).

Erros de domínio → RFC-7807 problem+json, mapa documentado em domain/campanha/erros.py:
NaoEncontrado→404 · AcaoNaoPermitida→403 · JustificativaObrigatoria→422 ·
TransicaoIlegal/AvancoBloqueadoPorPendencia/CodigoDuplicado/EstadoInvalido→409.
RBAC (§8-M0): escrita exige analista|lider (admin sempre passa); aceite de pendência é
de qualquer autenticado — o domínio exige o `accountable` (sem override, §10.5).
"""

import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from adapters.persistence.memoria import RepositorioOsMemoria
from adapters.relogio import RelogioSistema
from app.auth import Usuario, get_current_user, require_role
from app.errors import problem_response
from application.ports.repositorio_os import RepositorioOs
from application.services.os_service import ServicoOs
from domain.campanha.erros import (
    AcaoNaoPermitida,
    AvancoBloqueadoPorPendencia,
    CodigoDuplicado,
    ErroDominio,
    EstadoInvalido,
    JustificativaObrigatoria,
    NaoEncontrado,
    TransicaoIlegal,
)
from domain.ia_responsavel import (
    DadoBloqueadoParaLlm,
    DecisaoAutomatizadaNegada,
    ModeloNaoPermitido,
)

# ----------------------------------------------------------- Erros → problem+json
_STATUS_POR_ERRO: tuple[tuple[type[ErroDominio], int], ...] = (
    (NaoEncontrado, 404),
    (AcaoNaoPermitida, 403),
    (JustificativaObrigatoria, 422),
    (AvancoBloqueadoPorPendencia, 409),
    (TransicaoIlegal, 409),
    (CodigoDuplicado, 409),
    (EstadoInvalido, 409),
    # IA Responsável (§10.2) — sem estas linhas o portão INTERROMPE a chamada e depois
    # mente sobre o motivo: `_problema_de_dominio` cai no `500` de fallback e a resposta
    # vira "Erro interno inesperado". Medido: publicar `cpf: bloquear` devolvia 500 em
    # `POST /ajuda/perguntar`. Enforcement que se apresenta como bug é pior que
    # enforcement ausente — o usuário reporta incidente, o suporte procura stack trace,
    # e a decisão de privacidade que o DPO publicou fica invisível para todo mundo.
    (DadoBloqueadoParaLlm, 422),  # o solicitante corrige removendo o dado do texto
    (DecisaoAutomatizadaNegada, 403),  # Art. 20: a IA propõe, a pessoa aplica
    # 409 e não 403: quem chamou TEM o papel: é a política do tenant que conflita com o
    # perfil que a skill pede. 403 mandaria o usuário pedir permissão a si mesmo.
    (ModeloNaoPermitido, 409),
)


def _problema_de_dominio(exc: ErroDominio, instance: str) -> Response:
    status = next((s for tipo, s in _STATUS_POR_ERRO if isinstance(exc, tipo)), 500)
    extra: dict[str, Any] | None = None
    if isinstance(exc, AvancoBloqueadoPorPendencia):  # A1: motivo + pendências no corpo
        extra = {
            "pendencias": [
                {"numero": p.numero, "titulo": p.titulo, "severidade": p.severidade}
                for p in exc.pendencias
            ]
        }
    return problem_response(
        status, HTTPStatus(status).phrase, detail=exc.motivo, instance=instance, extra=extra
    )


class RotaComErrosDeDominio(APIRoute):
    """Traduz ErroDominio no próprio router (mapa fica aqui, como documenta erros.py)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except ErroDominio as exc:
                return _problema_de_dominio(exc, request.url.path)

        return handler


# ------------------------------------------------------------------ Dependências
_relogio = RelogioSistema()


def get_repositorio_os(request: Request) -> RepositorioOs:
    """Repositório em memória por app (CHANGELOG M1); adapter Postgres entra sem tocar aqui
    além desta função (hexagonal §2.1). Testes acessam via `app.state.repositorio_os`."""
    repo = getattr(request.app.state, "repositorio_os", None)
    if repo is None:
        repo = RepositorioOsMemoria()
        request.app.state.repositorio_os = repo
    return repo


def get_servico_os(
    repositorio: Annotated[RepositorioOs, Depends(get_repositorio_os)],
) -> ServicoOs:
    return ServicoOs(repositorio, _relogio)


def get_tenant(request: Request) -> str:
    return request.state.tenant_id  # garantido pelo middleware X-Tenant (app/main.py, §8)


_papel_escrita = require_role("analista", "lider")

Tenant = Annotated[str, Depends(get_tenant)]
Servico = Annotated[ServicoOs, Depends(get_servico_os)]
Autenticado = Annotated[Usuario, Depends(get_current_user)]
Escritor = Annotated[Usuario, Depends(_papel_escrita)]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)
FaseOs = Literal[
    "pensada",
    "discutida",
    "criada",
    "avaliada",
    "configurada",
    "disparada",
    "monitorada",
    "encerrada",
]


class OsCriar(BaseModel):
    nome: str = Field(min_length=1)
    tshirt: Literal["P", "M", "G", "GG"]
    briefing: dict[str, Any] = Field(default_factory=dict)
    codigo: str | None = None  # None → gerado OS-{ano}-{seq:04d}


class OsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: str
    codigo: str
    nome: str
    tshirt: str
    fase: str
    briefing: dict[str, Any]
    frozen: dict[str, Any] | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class MudancaFase(BaseModel):
    fase: FaseOs


class PendenciaCriar(BaseModel):
    titulo: str = Field(min_length=1)
    tipo: Literal["risk", "assumption", "issue", "dependency"] | None = None
    descricao: str | None = None
    severidade: Literal["baixa", "media", "alta"] | None = None
    bloqueante: bool = True  # default do DDL §4.1
    bloqueia_etapa: FaseOs | None = None  # None = bloqueia qualquer avanço
    accountable: uuid.UUID | None = None
    origem: str | None = None
    via_ai: bool = False


class PendenciaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    os_id: uuid.UUID
    numero: int
    tipo: str | None
    titulo: str
    descricao: str | None
    severidade: str | None
    bloqueante: bool
    bloqueia_etapa: str | None
    status: str
    accountable: uuid.UUID | None
    aceite: dict[str, Any] | None
    origem: str | None
    via_ai: bool
    created_at: datetime


class PendenciaAceitar(BaseModel):
    justificativa: str  # vazia/branca → JustificativaObrigatoria (422, A2)


class SaudeOut(BaseModel):
    os_id: uuid.UUID
    saude: Literal["normal", "em_risco"]


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaComErrosDeDominio, tags=["os"])


@router.post("/os", status_code=201, response_model=OsOut)
async def criar_os(payload: OsCriar, tenant: Tenant, servico: Servico, user: Escritor) -> OsOut:
    os_ = servico.criar_os(
        tenant,
        nome=payload.nome,
        tshirt=payload.tshirt,
        briefing=payload.briefing,
        created_by=user.id,
        codigo=payload.codigo,
    )
    return OsOut.model_validate(os_)


@router.get("/os", response_model=list[OsOut])
async def listar_os(
    tenant: Tenant,
    servico: Servico,
    _user: Autenticado,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[OsOut]:
    return [OsOut.model_validate(o) for o in servico.listar_os(tenant, limit=limit, offset=offset)]


@router.get("/os/{os_id}", response_model=OsOut)
async def obter_os(os_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado) -> OsOut:
    return OsOut.model_validate(servico.obter_os(tenant, os_id))


@router.post("/os/{os_id}/fase", response_model=OsOut)
async def mudar_fase(
    os_id: uuid.UUID, payload: MudancaFase, tenant: Tenant, servico: Servico, user: Escritor
) -> OsOut:
    """Só transições legais; portão de pendências checado (A1: bloqueante aberta → 409)."""
    return OsOut.model_validate(servico.mudar_fase(tenant, os_id, payload.fase, actor=user.email))


@router.get("/os/{os_id}/pendencias", response_model=list[PendenciaOut])
async def listar_pendencias(
    os_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> list[PendenciaOut]:
    """Emenda B01 (UAT #2): pendências da OS em ordem de `numero` — numero, titulo,
    severidade, status, bloqueante, accountable e a `origem` que ancora no campo
    (`validacao:{campo}`). Leitura pura: a rota só aceitava POST (405), e por isso o
    que estava aberto sumia da tela a cada reload."""
    return [PendenciaOut.model_validate(p) for p in servico.listar_pendencias(tenant, os_id)]


@router.post("/os/{os_id}/pendencias", status_code=201, response_model=PendenciaOut)
async def abrir_pendencia(
    os_id: uuid.UUID, payload: PendenciaCriar, tenant: Tenant, servico: Servico, user: Escritor
) -> PendenciaOut:
    pendencia = servico.abrir_pendencia(
        tenant,
        os_id,
        titulo=payload.titulo,
        tipo=payload.tipo,
        descricao=payload.descricao,
        severidade=payload.severidade,
        bloqueante=payload.bloqueante,
        bloqueia_etapa=payload.bloqueia_etapa,
        accountable=payload.accountable,
        origem=payload.origem,
        via_ai=payload.via_ai,
        actor=user.email,
    )
    return PendenciaOut.model_validate(pendencia)


@router.post("/pendencias/{pendencia_id}/resolver", response_model=PendenciaOut)
async def resolver_pendencia(
    pendencia_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Escritor
) -> PendenciaOut:
    return PendenciaOut.model_validate(
        servico.resolver_pendencia(tenant, pendencia_id, actor=user.email)
    )


@router.post("/pendencias/{pendencia_id}/aceitar", response_model=PendenciaOut)
async def aceitar_pendencia(
    pendencia_id: uuid.UUID,
    payload: PendenciaAceitar,
    tenant: Tenant,
    servico: Servico,
    user: Autenticado,
) -> PendenciaOut:
    """A2: aceite exige o accountable da pendência (`por` = usuário autenticado) + justificativa;
    gera `domain_event` pendencia.accepted (§2.3)."""
    pendencia = servico.aceitar_pendencia(
        tenant,
        pendencia_id,
        por=user.id,
        justificativa=payload.justificativa,
        actor=user.email,
    )
    return PendenciaOut.model_validate(pendencia)


@router.get("/os/{os_id}/saude", response_model=SaudeOut)
async def saude_da_os(
    os_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> SaudeOut:
    """A3: saúde é view derivada (§4.1) — este GET é a ÚNICA rota de /saude (sem escrita)."""
    return SaudeOut.model_validate({"os_id": os_id, "saude": servico.saude_da_os(tenant, os_id)})
