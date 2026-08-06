"""Rotas do M8 (parte 2) · Portões T9 + Aprovação T10 (SDD §8-M8) — tags OpenAPI
`portoes` e `aprovacao`.

Portões: `GET /os/{id}/portoes` (certificado, experimento, custo/alçada, governor
stub) · `POST /experimentos` (pré-registro + poder/n mínimo) ·
`POST /os/{id}/custo/enviar-alcada` (faixas `alcadas` da política §11.4).
Aprovação: `POST /snapshots` (hash composto §4.1) · `POST /snapshots/{id}/link-magico`
(A6: exige `aprovador_email` — o link nasce endereçado e criador ≠ aprovador é checado
aqui, §10.5; E03: o e-mail precisa ter CONTA) · `GET /aprovacao/{token}` (página
standalone — exige SESSÃO e dispensa X-Tenant: o escopo vem da sessão e é conferido
contra o tenant do pacote, evolução do C03 §8-M8-A5) · `POST /aprovacao/{token}/decidir`
(A3: uso único, expira, ip/device; ressalvas → pendências. A4: custo >10% pós-aprovação
invalida. E03: só decide a SESSÃO do aprovador designado — 403 se não for).

E03 (§10.5 — frente 3): as duas rotas de `/aprovacao/*` deixam de ser anônimas. O token
continua sendo o que localiza o pacote (ninguém precisa saber ids nem tenant), mas quem
lê e quem decide sai da sessão autenticada. É isso que tira do emissor — que recebe o
token em claro na emissão — o poder de decidir no lugar do aprovador.

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
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    Tenant,
    _problema_de_dominio,
    get_repositorio_os,
)
from app.auth import DEV_TOKENS, PORTAL_TOKENS, repositorio_identidade, tokens_dev_ativos
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
from domain.identidade.modelos import normalizar_email


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


def get_tenant_do_aprovador(usuario: Autenticado) -> str:
    """Tenant efetivo das rotas de `/aprovacao/*` — vem da SESSÃO (E03 §10.5).

    O middleware isenta este prefixo do `X-Tenant` OBRIGATÓRIO (`app/main.py`
    ROTAS_PUBLICAS) e a isenção continua fazendo sentido depois do login: esta é a URL
    que se abre antes de ter app aberto (link colado no chat, deep link), quando o
    cliente ainda não sabe qual tenant anunciar. O que mudou foi a FONTE: antes o tenant
    era derivado do TOKEN (C03), agora vem do portador autenticado, como no resto da API
    desde o achado 5 do UAT #5. `_por_token` confere o pacote contra ele e devolve 404
    quando o token é de outro tenant — sem vazar que o link existe.

    Não há conferência de header a fazer aqui: `get_current_user` (emenda G01) já casa o
    `X-Tenant` anunciado com o escopo da credencial e responde 403 na divergência, para
    sessão e para Bearer. Duplicar a regra só criaria dois lugares para ela divergir.
    """
    return usuario.tenant_id


Portoes = Annotated[ServicoPortoes, Depends(get_servico_portoes)]
Aprovacoes = Annotated[ServicoAprovacao, Depends(get_servico_aprovacao)]
TenantDoAprovador = Annotated[str, Depends(get_tenant_do_aprovador)]

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


def _papeis_no_roster(request: Request, tenant_id: str, email: str) -> tuple[str, ...] | None:
    """Papéis de QUEM PODE ENTRAR com este e-mail neste tenant — ou `None` se ninguém pode.

    Fica na borda porque o roster mora em `app.*` e a camada de aplicação não importa
    `app.*` (§2.1). `None` = e-mail SEM CONTA e, desde o E03 (§10.5), isso é RECUSA na
    emissão, não mais "aprovador de fora, pula a alçada": quem decide precisa de SESSÃO,
    então um link para quem não tem conta nasceria morto — e o e-mail de fora era também
    o jeito de pular a checagem de papel/alçada.

    Duas fontes, nesta ordem, porque "poder entrar" tem duas formas neste projeto:

    1. A tabela `usuario` (emenda G01/frente 1) — a autoridade. Escopada por tenant de
       propósito (`obter_usuario_por_email` exige `tenant_id`): conta de outro tenant não
       é conta aqui, e perguntar sem escopo seria o oráculo cross-tenant do achado 22.
       Conta DESATIVADA conta como inexistente — ela não loga, logo não decide.
    2. Os tokens de dev (`DEV_TOKENS` + `PORTAL_TOKENS`), e SÓ quando `tokens_dev_ativos()`
       — são fixtures de ambiente, não credenciais; em prod não existem e esta perna
       simplesmente não roda. Varrer também `PORTAL_TOKENS` importa: olhar só o primeiro
       roster deixava `portal@` passar por "e-mail de fora" e escapar da alçada.
    """
    conta = repositorio_identidade(request).obter_usuario_por_email(
        tenant_id, normalizar_email(email)
    )
    if conta is not None:
        return tuple(conta.papeis) if conta.ativo else None
    if not tokens_dev_ativos():
        return None
    alvo = normalizar_email(email)
    roster = (*DEV_TOKENS.values(), *PORTAL_TOKENS.values())
    return next((u.papeis for u in roster if u.email.lower() == alvo), None)


@router_aprovacao.post("/snapshots/{snapshot_id}/link-magico", status_code=201)
async def criar_link_magico(
    snapshot_id: uuid.UUID,
    payload: LinkMagicoCriar,
    tenant: Tenant,
    servico: Aprovacoes,
    user: Escritor,
    request: Request,
) -> dict[str, Any]:
    """Link mágico (T10): token único retornado UMA vez (persistido só o sha256),
    expiração e alçada da faixa da política — URL standalone §12 `/aprovacao/:token`.

    A6 (§10.5): o corpo passa a exigir `aprovador_email` (o destinatário é carimbado na
    emissão) — criador ≠ aprovador → 409, papel fora da alçada → 409.
    E03 (§10.5): aprovador SEM CONTA no tenant → 409. Como a decisão passou a exigir
    sessão, emitir para quem não pode entrar seria entregar um link natimorto."""
    return servico.criar_link_magico(
        tenant,
        snapshot_id,
        aprovador_email=payload.aprovador_email,
        papeis_aprovador=_papeis_no_roster(request, tenant, payload.aprovador_email),
        validade_horas=payload.validade_horas,
        actor=user.email,
    )


@router_aprovacao.get("/aprovacao/{token}")
async def pagina_aprovacao(
    token: str, tenant: TenantDoAprovador, servico: Aprovacoes, usuario: Autenticado
) -> dict[str, Any]:
    """Página standalone (§8-M8): resumo, waterfall, criativos, replay do previsto e
    hash. Sem X-Tenant obrigatório (C03), mas COM sessão (E03 §10.5): o pacote traz custo,
    criativos e — pelo achado 9 do UAT #5 — PII herdada do briefing, e uma URL com token
    de 72h vaza por histórico, referer, print e encaminhamento. Ler é de qualquer sessão
    do tenant dono do pacote; decidir é só do destinatário (`sessao.pode_decidir` no
    corpo). Expirado e não decidido → 410."""
    return servico.payload_aprovacao(
        token, tenant_id=tenant, sessao_email=usuario.email, sessao_nome=usuario.nome
    )


@router_aprovacao.post("/aprovacao/{token}/decidir")
async def decidir_aprovacao(
    token: str,
    payload: Decisao,
    tenant: TenantDoAprovador,
    servico: Aprovacoes,
    usuario: Autenticado,
    request: Request,
) -> dict[str, Any]:
    """A3: decisão de uso ÚNICO com registro de ip/device; ressalvas viram pendências
    automáticas bloqueantes. A4: aprovação invalidada por custo → 409 (snapshot novo).

    E03 (§10.5): EXIGE sessão e a sessão tem que ser a do `aprovador_email` congelado na
    emissão — 401 sem sessão, 403 com sessão de outra pessoa (mesmo de posse do token, que
    volta em claro para quem emite). A6: `decidido_por` no corpo continua sendo asserção
    conferida, nunca a fonte da identidade → 409 se divergir."""
    return servico.decidir(
        token,
        tenant_id=tenant,
        sessao_email=usuario.email,
        decisao=payload.decisao,
        ressalvas=payload.ressalvas,
        decidido_por=payload.decidido_por,
        ip=request.client.host if request.client else None,
        device=request.headers.get("user-agent"),
    )
