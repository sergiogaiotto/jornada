"""Rotas do M8 (parte 2) · Portões T9 + Aprovação T10 (SDD §8-M8) — tags OpenAPI
`portoes` e `aprovacao`.

Portões: `GET /os/{id}/portoes` (certificado, experimento, custo/alçada, governor
stub) · `POST /experimentos` (pré-registro + poder/n mínimo) ·
`POST /os/{id}/custo/enviar-alcada` (faixas `alcadas` da política §11.4).
Aprovação: `POST /snapshots` (hash composto §4.1) · `POST /snapshots/{id}/link-magico`
(A6: exige `aprovador_email` — o link nasce endereçado e criador ≠ aprovador é checado
aqui, §10.5) · `GET /aprovacao/{token}` (página standalone — o TOKEN é a credencial, sem
Bearer e sem X-Tenant: o tenant é derivado do token no servidor, emenda C03 §8-M8-A5) ·
`POST /aprovacao/{token}/decidir` (A3: uso único, expira, ip/device; ressalvas →
pendências. A4: custo >10% pós-aprovação invalida. A6: identidade vem do token).

ZERO LLM em todo o caminho (§10.6). Erros: mapa RFC-7807 do M1 + tradução própria:
LinkExpirado→410 Gone · HoldoutAbaixoDaPolitica/RessalvasObrigatorias→422.
RBAC (§8-M0): mutações autenticadas exigem analista|lider.
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from adapters.relogio import RelogioSistema
from api.v1.os_governanca import Escritor, Tenant, _problema_de_dominio, get_repositorio_os
from app.auth import DEV_TOKENS, PORTAL_TOKENS
from app.config import get_settings
from app.errors import problem_response
from application.ports.repositorio_aprovacao import RepositorioAprovacao
from application.services.aprovacao_service import (
    VALIDADE_LINK_HORAS_DEFAULT,
    ServicoAprovacao,
    ServicoPortoes,
)
from domain.campanha.erros import ErroDominio
from domain.governanca.erros import (
    HoldoutAbaixoDaPolitica,
    LinkExpirado,
    RessalvasObrigatorias,
)


class RotaPortoesAprovacao(APIRoute):
    """LinkExpirado→410 e 422s próprios ANTES do mapa genérico do M1 (padrão M4/M5/M8)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except LinkExpirado as exc:
                return problem_response(410, "Gone", detail=exc.motivo, instance=request.url.path)
            except (HoldoutAbaixoDaPolitica, RessalvasObrigatorias) as exc:
                return problem_response(
                    422, "Unprocessable Entity", detail=exc.motivo, instance=request.url.path
                )
            except ErroDominio as exc:
                return _problema_de_dominio(exc, request.url.path)

        return handler


# ------------------------------------------------------------------ Dependências
_relogio = RelogioSistema()


def get_servico_portoes(request: Request) -> ServicoPortoes:
    """Mesma instância de repositório da OS (app.state) — RepositorioOsMemoria implementa
    todas as portas (tipagem estrutural §2.1); o cast só informa o mypy."""
    repositorio = cast(RepositorioAprovacao, get_repositorio_os(request))
    return ServicoPortoes(repositorio, _relogio)


def get_servico_aprovacao(request: Request) -> ServicoAprovacao:
    repositorio = cast(RepositorioAprovacao, get_repositorio_os(request))
    return ServicoAprovacao(repositorio, _relogio, get_settings().web_base_url)


def get_tenant_opcional(request: Request) -> str | None:
    """Tenant ANUNCIADO pelo cliente nas rotas públicas do link mágico (C03).

    O middleware (`app/main.py` ROTAS_PUBLICAS) isenta `/aprovacao/*` do X-Tenant: o
    aprovador externo não tem como mandar header. Vindo (a SPA manda), o serviço o
    confere contra o tenant real do pacote — anúncio, nunca fonte da verdade."""
    return getattr(request.state, "tenant_id", None)


Portoes = Annotated[ServicoPortoes, Depends(get_servico_portoes)]
Aprovacoes = Annotated[ServicoAprovacao, Depends(get_servico_aprovacao)]
TenantOpcional = Annotated[str | None, Depends(get_tenant_opcional)]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class ExperimentoCriar(BaseModel):
    """Pré-registro (§8-M8): n_minimo é CALCULADO no servidor (poder.py), nunca input."""

    os_id: uuid.UUID
    mde_pp: float = Field(gt=0, le=50)  # MDE em pontos percentuais
    janela_dias: int = Field(ge=1, le=365)
    holdout_pct: float | None = Field(default=None, ge=0, le=50)  # None → holdout_min da política
    metricas: dict[str, Any] = Field(default_factory=lambda: {"primaria": "conversao"})


class ExperimentoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    os_id: uuid.UUID
    holdout_pct: float
    n_minimo: int
    mde_pp: float
    janela_dias: int
    metricas: dict[str, Any]
    travado_em: Any
    estado: str


class ExperimentoPreRegistradoOut(BaseModel):
    experimento: ExperimentoOut
    poder: dict[str, Any]


class SnapshotCriar(BaseModel):
    os_id: uuid.UUID


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    os_id: uuid.UUID
    hash: str
    conteudo: dict[str, Any]
    previsto: dict[str, Any] | None
    created_at: Any


class LinkMagicoCriar(BaseModel):
    """A6 (§10.5): `aprovador_email` é OBRIGATÓRIO — o link mágico nasce endereçado.

    O `pattern` só barra lixo óbvio na borda (422); a regra que importa — criador ≠
    aprovador e papel vs. alçada — é do serviço, que é onde ela é inescapável."""

    aprovador_email: Annotated[
        str,
        StringConstraints(  # normaliza ANTES do pattern (caixa/espaços não driblam §10.5)
            strip_whitespace=True,
            to_lower=True,
            min_length=5,
            max_length=254,
            pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        ),
    ]
    validade_horas: int = Field(default=VALIDADE_LINK_HORAS_DEFAULT, ge=1, le=720)


class Decisao(BaseModel):
    decisao: Literal["aprovado", "aprovado_ressalvas", "reprovado"]
    ressalvas: list[str] = Field(default_factory=list)  # exigidas em aprovado_ressalvas (A3)
    # A6 (§10.5): ASSERÇÃO a conferir contra o e-mail congelado no link, nunca a fonte da
    # identidade — divergiu, 409. Mantido por compatibilidade com clientes já publicados.
    decidido_por: str | None = None


# ---------------------------------------------------------------- Rotas · Portões T9
router_portoes = APIRouter(route_class=RotaPortoesAprovacao, tags=["portoes"])


@router_portoes.get("/os/{os_id}/portoes")
async def portoes_da_os(
    os_id: uuid.UUID, tenant: Tenant, servico: Portoes, user: Escritor
) -> dict[str, Any]:
    """Painel T9 (§8-M8): certificado (M5-A3), experimento (A2), custo/alçada e
    governor (stub — pleno no M10) + estado da aprovação (invalidação A4 aplicada)."""
    return servico.portoes(tenant, os_id)


@router_portoes.post("/experimentos", status_code=201, response_model=ExperimentoPreRegistradoOut)
async def pre_registrar_experimento(
    payload: ExperimentoCriar, tenant: Tenant, servico: Portoes, user: Escritor
) -> ExperimentoPreRegistradoOut:
    """Pré-registro com cálculo de poder e n mínimo (§8-M8) — nasce travado
    (anti-p-hacking; a apuração anti-peeking chega no M11)."""
    resultado = servico.pre_registrar_experimento(
        tenant,
        payload.os_id,
        holdout_pct=payload.holdout_pct,
        mde_pp=payload.mde_pp,
        janela_dias=payload.janela_dias,
        metricas=payload.metricas,
        actor=user.email,
    )
    return ExperimentoPreRegistradoOut(
        experimento=ExperimentoOut.model_validate(resultado["experimento"]),
        poder=resultado["poder"],
    )


@router_portoes.post("/os/{os_id}/custo/enviar-alcada")
async def enviar_custo_alcada(
    os_id: uuid.UUID, tenant: Tenant, servico: Portoes, user: Escritor
) -> dict[str, Any]:
    """Envia o custo previsto (P50 do Ensaio Geral) à faixa de alçada da política
    (§11.4 `alcadas` [{ate, papel}]); acima da maior faixa → 409."""
    return servico.enviar_custo_alcada(tenant, os_id, actor=user.email)


# -------------------------------------------------------------- Rotas · Aprovação T10
router_aprovacao = APIRouter(route_class=RotaPortoesAprovacao, tags=["aprovacao"])


@router_aprovacao.post("/snapshots", status_code=201, response_model=SnapshotOut)
async def criar_snapshot(
    payload: SnapshotCriar, tenant: Tenant, servico: Aprovacoes, user: Escritor
) -> SnapshotOut:
    """Pacote imutável de aprovação (§4.1): hash composto sha256 de JGC+SQL+criativos+
    política+custo+experimento; exige simulação + Previsto congelado (409 senão)."""
    snapshot = servico.criar_snapshot(tenant, payload.os_id, actor=user.email)
    return SnapshotOut.model_validate(snapshot)


def _papeis_no_roster(email: str) -> tuple[str, ...] | None:
    """Papéis do e-mail QUANDO ele é um usuário do sistema (roster do §8-M0).

    Fica na borda porque o roster mora em `app.auth` e a camada de aplicação não importa
    `app.*` (§2.1). `None` = e-mail fora do roster — o caso normal do link mágico, em que
    o aprovador é o cliente; sem informação, o serviço não inventa veredito de alçada.
    Dev usa os tokens estáticos; quando o IdP entrar, só esta função muda.

    Varre os DOIS rosters: `DEV_TOKENS` (login pleno) e `PORTAL_TOKENS` (§8-M3). Olhar só
    o primeiro deixava o solicitante do portal passar por "e-mail de fora" e escapar da
    checagem de alçada — justamente o papel que o §10.5 quer barrar."""
    alvo = email.strip().lower()
    roster = (*DEV_TOKENS.values(), *PORTAL_TOKENS.values())
    return next((u.papeis for u in roster if u.email.lower() == alvo), None)


@router_aprovacao.post("/snapshots/{snapshot_id}/link-magico", status_code=201)
async def criar_link_magico(
    snapshot_id: uuid.UUID,
    payload: LinkMagicoCriar,
    tenant: Tenant,
    servico: Aprovacoes,
    user: Escritor,
) -> dict[str, Any]:
    """Link mágico (T10): token único retornado UMA vez (persistido só o sha256),
    expiração e alçada da faixa da política — URL standalone §12 `/aprovacao/:token`.

    A6 (§10.5): o corpo passa a exigir `aprovador_email` (o destinatário é carimbado na
    emissão) — criador ≠ aprovador → 409, papel fora da alçada → 409."""
    return servico.criar_link_magico(
        tenant,
        snapshot_id,
        aprovador_email=payload.aprovador_email,
        papeis_aprovador=_papeis_no_roster(payload.aprovador_email),
        validade_horas=payload.validade_horas,
        actor=user.email,
    )


@router_aprovacao.get("/aprovacao/{token}")
async def pagina_aprovacao(
    token: str, tenant: TenantOpcional, servico: Aprovacoes
) -> dict[str, Any]:
    """Página standalone (§8-M8): resumo, waterfall, criativos, replay do previsto e
    hash. SEM Bearer e SEM X-Tenant (C03) — o token É a credencial e carrega o escopo
    (expirado e não decidido → 410)."""
    return servico.payload_aprovacao(token, tenant_id=tenant)


@router_aprovacao.post("/aprovacao/{token}/decidir")
async def decidir_aprovacao(
    token: str, payload: Decisao, tenant: TenantOpcional, servico: Aprovacoes, request: Request
) -> dict[str, Any]:
    """A3: decisão de uso ÚNICO com registro de ip/device; ressalvas viram pendências
    automáticas bloqueantes. A4: aprovação invalidada por custo → 409 (snapshot novo).
    C03: sem X-Tenant — o tenant vem do token. A6: a identidade do aprovador vem do
    link (§10.5); `decidido_por` divergente → 409."""
    return servico.decidir(
        token,
        tenant_id=tenant,
        decisao=payload.decisao,
        ressalvas=payload.ressalvas,
        decidido_por=payload.decidido_por,
        ip=request.client.host if request.client else None,
        device=request.headers.get("user-agent"),
    )
