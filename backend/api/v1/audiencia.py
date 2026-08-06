"""Rotas do M5 · Audiência / T5 (SDD §8-M5) — tag OpenAPI `audiencia`.

`POST /os/{id}/segmento/gerar-sql` (engineer via LLMPort) · `POST /segmentos/{id}/recontar`
(dry-run no read model: waterfall + líquido + volume por canal + frescor) ·
`PUT /segmentos/{id}/holdout` · `POST /segmentos/{id}/certificar` (GUARD DETERMINÍSTICO:
varre 7 listas + opt-in e emite `certificado_elegibilidade` — zero LLM, §10.6).

Erros: domínio → RFC-7807 (mapa do M1; SegmentoSemSql/CertificadoExpirado→409 por
herança) + traduções deste router: LLMIndisponivel→503 degraded (§10.6);
CertificadoReprovado→422 com `listas_faltantes`/`problemas` (A1);
HoldoutForaDaPolitica/SaidaDoEngineerInvalida→422. RBAC (§8-M0): mutações exigem
analista|lider.
"""

import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from adapters.datacloud.fixtures import DataCloudFixtures
from adapters.fontes.read_model import ReadModelFixtures
from adapters.publicacoes import publicacoes_vigentes
from adapters.relogio import RelogioSistema
from api.v1.intake import get_llm, get_retriever, get_tracer
from api.v1.os_governanca import (
    Escritor,
    Tenant,
    _problema_de_dominio,
    get_repositorio_os,
    get_servico_os,
)
from app.errors import problem_response
from application.ports.datacloud import DataCloudPort
from application.ports.llm import LLMIndisponivel
from application.ports.publicacoes_ia import PublicacoesIaPort
from application.ports.read_model_audiencia import ReadModelAudienciaPort
from application.ports.repositorio_audiencia import RepositorioAudiencia
from application.services.audiencia_service import ServicoAudiencia
from application.services.os_service import ServicoOs
from domain.audiencia.erros import (
    CertificadoReprovado,
    HoldoutForaDaPolitica,
    SaidaDoEngineerInvalida,
)
from domain.campanha.erros import ErroDominio


class RotaAudiencia(APIRoute):
    """Traduções do M5 ANTES do mapa genérico do M1 (padrão da RotaValidacao/M4):
    os erros específicos herdam ErroDominio e precisam ser interceptados primeiro."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except CertificadoReprovado as exc:  # A1: guard reprova com as listas no corpo
                return problem_response(
                    422,
                    "Unprocessable Entity",
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra={"listas_faltantes": exc.listas_faltantes, "problemas": exc.problemas},
                )
            except (HoldoutForaDaPolitica, SaidaDoEngineerInvalida) as exc:
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


def get_datacloud(request: Request) -> DataCloudPort:
    """Data Cloud atrás de porta (§2.1): dev/teste = fixtures (§11.2, nenhuma rede);
    o adapter HTTP (adapters/datacloud/cliente.py) entra via `app.state.datacloud`
    no compose — mesmo padrão de `app.state.llm`."""
    datacloud = getattr(request.app.state, "datacloud", None)
    if datacloud is None:
        datacloud = DataCloudFixtures()
        request.app.state.datacloud = datacloud
    return datacloud


def get_read_model(request: Request) -> ReadModelAudienciaPort:
    """Read model de ativação (dry-run §8-M5): fixtures em dev/teste (§11)."""
    read_model = getattr(request.app.state, "read_model_audiencia", None)
    if read_model is None:
        read_model = ReadModelFixtures()
        request.app.state.read_model_audiencia = read_model
    return read_model


def get_servico_audiencia(
    request: Request, servico_os: Annotated[ServicoOs, Depends(get_servico_os)]
) -> ServicoAudiencia:
    """Mesma instância de repositório da OS (app.state) — RepositorioOsMemoria implementa
    todas as portas (tipagem estrutural §2.1); o cast só informa o mypy."""
    repositorio = get_repositorio_os(request)
    return ServicoAudiencia(
        cast(RepositorioAudiencia, repositorio),
        _relogio,
        servico_os,
        get_llm(request),
        get_tracer(request),
        get_datacloud(request),
        get_read_model(request),
        # achado 8 (UAT #5): era `PublicacoesLocais` — a política publicada no banco
        # existia e o holdout_min continuava vindo da CONSTANTE do domínio.
        publicacoes_vigentes(repositorio),
        # política de IA Responsável PUBLICADA (§10.2) — a MESMA fábrica, para não
        # existir uma segunda fonte de política (achado 8 UAT #5).
        cast(PublicacoesIaPort, publicacoes_vigentes(repositorio)),
        retriever=get_retriever(request),  # A11: preparar_contexto RAG (§7.3/§7.4)
    )


Servico = Annotated[ServicoAudiencia, Depends(get_servico_audiencia)]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class SegmentoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    os_id: uuid.UUID | None
    origem: Literal["estudio_sql", "data_cloud"]
    dc_segment_id: str | None
    sql_publico: str | None
    criterios_resumo: str | None
    contagem_bruta: int | None
    contagem_liquida: int | None
    waterfall: list[dict[str, Any]]
    volume_abordagem: dict[str, Any]
    holdout_pct: float
    frescor: dict[str, Any]  # {fonte: ultima_atualizacao} (§4.1 — A4)


class GerarSqlIn(BaseModel):
    instrucoes: str = Field(min_length=1)  # pedido em NL para o engineer (T5)


class GerarSqlOut(BaseModel):
    """Prévia do engineer (contrato §7.2: SQL + explicação por cláusula + evidências).

    `avisos` = pré-check informativo do Guard; a reprovação dura é na certificação (A1).
    """

    segmento: SegmentoOut
    explicacao: list[dict[str, str]]
    evidencias: list[str]
    avisos: list[str]
    via_ai: bool = True
    invocacao_id: uuid.UUID


class HoldoutIn(BaseModel):
    holdout_pct: float = Field(ge=0.0, lt=100.0)  # política valida o mínimo (§4.1)


class CertificadoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    os_id: uuid.UUID
    hash: str
    suprimidos: dict[str, int]  # {lista: contagem} — as 7 listas (§4.1)
    liquido: int
    emitido_em: datetime
    valido_ate: datetime | None
    last_mile: dict[str, Any] | None


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaAudiencia, tags=["audiencia"])


@router.post("/os/{os_id}/segmento/gerar-sql", status_code=201, response_model=GerarSqlOut)
async def gerar_sql(
    os_id: uuid.UUID, payload: GerarSqlIn, tenant: Tenant, servico: Servico, user: Escritor
) -> GerarSqlOut:
    """Engineer (LLM 120b — roster §7.2) gera o SQL público como PRÉVIA (§1.1.3);
    ledger `invocacao` via_ai + trace Langfuse (§10.8)."""
    segmento, saida, avisos, invocacao = servico.gerar_sql(
        tenant, os_id, instrucoes=payload.instrucoes, portador_id=user.id
    )
    return GerarSqlOut(
        segmento=SegmentoOut.model_validate(segmento),
        explicacao=list(saida.explicacao),
        evidencias=list(saida.evidencias),
        avisos=avisos,
        invocacao_id=invocacao.id,
    )


@router.post("/segmentos/{segmento_id}/recontar", response_model=SegmentoOut)
async def recontar(
    segmento_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Escritor
) -> SegmentoOut:
    """Dry-run no read model (§8-M5): waterfall + líquido + volume de abordagem por
    canal (A2) + frescor por fonte (A4 — Hybris D-1 nas fixtures)."""
    return SegmentoOut.model_validate(servico.recontar(tenant, segmento_id, actor=user.email))


@router.put("/segmentos/{segmento_id}/holdout", response_model=SegmentoOut)
async def definir_holdout(
    segmento_id: uuid.UUID, payload: HoldoutIn, tenant: Tenant, servico: Servico, user: Escritor
) -> SegmentoOut:
    """Define o holdout do segmento; abaixo do `holdout_min` da política → 422."""
    return SegmentoOut.model_validate(
        servico.definir_holdout(
            tenant, segmento_id, holdout_pct=payload.holdout_pct, actor=user.email
        )
    )


@router.post("/segmentos/{segmento_id}/certificar", status_code=201, response_model=CertificadoOut)
async def certificar(
    segmento_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Escritor
) -> CertificadoOut:
    """GUARD DETERMINÍSTICO (§7.2 — zero LLM): varre as 7 listas + opt-in no WHERE (A1)
    e emite `certificado_elegibilidade` com hash e validade (A3); reprova → 422."""
    return CertificadoOut.model_validate(servico.certificar(tenant, segmento_id, actor=user.email))
