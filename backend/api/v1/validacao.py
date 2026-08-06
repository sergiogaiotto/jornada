"""Rotas do M4 · Validação campo-a-campo & War Room / T3-T4 (SDD §8-M4) — tag `validacao`.

`POST /os/{id}/validacoes/{campo}` (checagem automática contra fonte: contagem, schema,
frescor; retorna evidência — idempotente por campo desde a emenda B01) ·
`GET /os/{id}/validacoes` (emenda B01: decisão vigente de cada campo — a tela T3 hidrata
daqui, não do estado de sessão) · `POST .../validacoes/{campo}/pendencia` ·
`POST /os/{id}/threads` (ancoradas em campo) · `POST /os/{id}/go` (congela SLAs+versões
em `os.frozen`, fase→criada, .docx executivo em `documento_portao`).

Erros: domínio → RFC-7807 (mapa do M1; CampoForaDoBriefing→404 por herança);
`GoBloqueado` → 409 com `pendencias` + `campos_nao_decididos` no corpo (A1) —
traduzido aqui em `RotaValidacao`. RBAC (§8-M0): validações/pendência/GO exigem
analista|lider; thread do War Room é de qualquer autenticado.
"""

import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from adapters.documentos.docx_portao import GeradorDocxPortao
from adapters.fontes.fixtures import FonteFixtures
from adapters.publicacoes import PublicacoesAtelie, PublicacoesLocais
from adapters.relogio import RelogioSistema
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    OsOut,
    PendenciaOut,
    Tenant,
    _problema_de_dominio,
    get_repositorio_os,
    get_servico_os,
)
from app.errors import problem_response
from application.ports.fonte_validacao import FonteValidacaoPort
from application.ports.repositorio_atelie import RepositorioAtelie
from application.ports.repositorio_plataforma import RepositorioPoliticas
from application.ports.repositorio_validacao import RepositorioValidacao
from application.services.os_service import ServicoOs
from application.services.validacao_service import ServicoValidacao
from domain.campanha.erros import ErroDominio
from domain.validacao.erros import GoBloqueado


class RotaValidacao(APIRoute):
    """Mapa do M1 + `GoBloqueado` → 409 listando pendências e campos não decididos (A1)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except GoBloqueado as exc:
                return problem_response(
                    409,
                    "Conflict",
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra={
                        "campos_nao_decididos": exc.campos_nao_decididos,
                        "pendencias": [
                            {"numero": p.numero, "titulo": p.titulo, "severidade": p.severidade}
                            for p in exc.pendencias
                        ],
                    },
                )
            except ErroDominio as exc:
                return _problema_de_dominio(exc, request.url.path)

        return handler


# ------------------------------------------------------------------ Dependências
_relogio = RelogioSistema()
_publicacoes_disco = PublicacoesLocais()
_gerador = GeradorDocxPortao()


def get_fonte_validacao(request: Request) -> FonteValidacaoPort:
    """Fonte atrás de porta (§2.1): dev/teste = fixtures (§11); testes podem trocar o
    adapter em `app.state.fonte_validacao` (mesmo padrão de `app.state.llm`)."""
    fonte = getattr(request.app.state, "fonte_validacao", None)
    if fonte is None:
        fonte = FonteFixtures()
        request.app.state.fonte_validacao = fonte
    return fonte


def get_servico_validacao(
    request: Request, servico_os: Annotated[ServicoOs, Depends(get_servico_os)]
) -> ServicoValidacao:
    """Mesma instância de repositório da OS (app.state) — RepositorioOsMemoria implementa
    todas as portas (tipagem estrutural §2.1); o cast só informa o mypy. O GO congela
    versões do BANCO do Ateliê (M12) com fallback disco — mesmos valores (§8-M4-A2)."""
    repositorio = get_repositorio_os(request)
    publicacoes = PublicacoesAtelie(
        cast(RepositorioAtelie, repositorio),
        fallback=_publicacoes_disco,
        politicas=cast(RepositorioPoliticas, repositorio),  # policy publicada ATUAL (M12 p2)
    )
    return ServicoValidacao(
        cast(RepositorioValidacao, repositorio),
        repositorio,
        _relogio,
        servico_os,
        get_fonte_validacao(request),
        publicacoes,
        _gerador,
    )


Servico = Annotated[ServicoValidacao, Depends(get_servico_validacao)]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class ChecagemOut(BaseModel):
    tipo: str  # contagem|schema|frescor|fonte
    ok: bool
    detalhe: str


class ValidacaoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    os_id: uuid.UUID
    campo: str
    veredito: Literal["ok", "falha"]
    checagens: list[ChecagemOut]
    evidencia: dict[str, Any]
    created_at: datetime  # primeira checagem do campo
    # emenda B01: quem/quando da decisão vigente (None em linhas anteriores à emenda)
    por: str | None = None
    atualizado_em: datetime | None = None


class PendenciaDeCampoCriar(BaseModel):
    """Pendência ancorada no campo (origem `validacao:{campo}`); default bloqueante (§4.1)."""

    titulo: str | None = None  # None → título padrão citando o campo
    descricao: str | None = None
    severidade: Literal["baixa", "media", "alta"] | None = None
    bloqueante: bool = True
    accountable: uuid.UUID | None = None


class ThreadCriar(BaseModel):
    campo: str = Field(min_length=1)  # âncora obrigatória (§8-M4: threads ancoradas)
    titulo: str | None = None
    mensagem: str = Field(min_length=1)


class MensagemThreadOut(BaseModel):
    autor: str
    texto: str
    em: datetime


class ThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    os_id: uuid.UUID
    campo: str
    titulo: str | None
    mensagens: list[MensagemThreadOut]
    status: Literal["aberta", "resolvida"]
    created_at: datetime


class DocumentoPortaoOut(BaseModel):
    """Metadados do .docx armazenado em `documento_portao` (A3) — sem os bytes."""

    id: uuid.UUID
    os_id: uuid.UUID
    portao: str
    nome_arquivo: str
    tamanho_bytes: int
    hash: str
    created_at: datetime


class GoOut(BaseModel):
    os: OsOut
    documento: DocumentoPortaoOut


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaValidacao, tags=["validacao"])


@router.get("/os/{os_id}/validacoes", response_model=list[ValidacaoOut])
async def listar_validacoes(
    os_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> list[ValidacaoOut]:
    """Emenda B01 (UAT #2): decisão vigente de cada campo já checado — uma por campo,
    com veredito, checagens, evidência e quem/quando. É daqui que a tela T3 se recupera
    após reload/restart; sem ela o estado só existia na sessão do navegador."""
    return [ValidacaoOut.model_validate(v) for v in servico.listar_validacoes(tenant, os_id)]


@router.post("/os/{os_id}/validacoes/{campo}", status_code=201, response_model=ValidacaoOut)
async def validar_campo(
    os_id: uuid.UUID, campo: str, tenant: Tenant, servico: Servico, user: Escritor
) -> ValidacaoOut:
    """Checagem automática do campo contra a fonte (contagem, schema, frescor) com
    evidência — determinística, fixtures de fonte em dev/teste (§11).

    IDEMPOTENTE por campo (emenda B01): revalidar atualiza a decisão vigente (mesmo `id`),
    nunca duplica a linha — o 201 devolve a decisão resultante em ambos os casos."""
    return ValidacaoOut.model_validate(
        servico.validar_campo(tenant, os_id, campo, actor=user.email)
    )


@router.post(
    "/os/{os_id}/validacoes/{campo}/pendencia", status_code=201, response_model=PendenciaOut
)
async def abrir_pendencia_de_campo(
    os_id: uuid.UUID,
    campo: str,
    payload: PendenciaDeCampoCriar,
    tenant: Tenant,
    servico: Servico,
    user: Escritor,
) -> PendenciaOut:
    """Pendência ancorada no campo validado (origem `validacao:{campo}`); bloqueante
    trava o GO até resolver/aceitar (A1)."""
    pendencia = servico.abrir_pendencia_de_campo(
        tenant,
        os_id,
        campo,
        titulo=payload.titulo,
        descricao=payload.descricao,
        severidade=payload.severidade,
        bloqueante=payload.bloqueante,
        accountable=payload.accountable,
        actor=user.email,
    )
    return PendenciaOut.model_validate(pendencia)


@router.post("/os/{os_id}/threads", status_code=201, response_model=ThreadOut)
async def criar_thread(
    os_id: uuid.UUID, payload: ThreadCriar, tenant: Tenant, servico: Servico, user: Autenticado
) -> ThreadOut:
    """Thread do War Room (T4) ANCORADA em campo do briefing (campo inexistente → 404)."""
    thread = servico.criar_thread(
        tenant,
        os_id,
        campo=payload.campo,
        titulo=payload.titulo,
        mensagem=payload.mensagem,
        actor=user.email,
    )
    return ThreadOut.model_validate(thread)


@router.post("/os/{os_id}/go", response_model=GoOut)
async def executar_go(os_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Escritor) -> GoOut:
    """GO (§8-M4): campo não decidido ou pendência bloqueante → 409 listando-as (A1);
    congela SLAs+versões em `os.frozen` (A2); gera e armazena o .docx executivo (A3);
    fase→criada."""
    os_, documento = servico.executar_go(tenant, os_id, actor=user.email)
    return GoOut(
        os=OsOut.model_validate(os_),
        documento=DocumentoPortaoOut(
            id=documento.id,
            os_id=documento.os_id,
            portao=documento.portao,
            nome_arquivo=documento.nome_arquivo,
            tamanho_bytes=len(documento.conteudo),
            hash=documento.hash,
            created_at=documento.created_at,
        ),
    )
