"""Rotas do M7 · Twin Canvas / T7 (SDD §8-M7) — tag OpenAPI `jornada`.

`POST /os/{id}/jornada/gerar` (flow → JGC) · `GET /os/{id}/jornada` (última versão do
twin — emenda A14; 404 sem versão) · `PUT /jornadas/{id}/grafo` (valida §5.3;
recalcula taxímetro) · `POST /jornadas/{id}/ajustar` (texto livre → diff proposto,
NUNCA aplica direto) · `GET /jornadas/{id}/no/{noId}/sfmc-preview` (JSON que o
compilador gerará — §5.4, determinístico).

Editor "começar do zero" (emenda 2026-08-05 — determinístico, ZERO LLM §10.6):
`POST /os/{id}/jornada` (nova versão `rascunho` a partir de grafo manual validado
§5.3, ou do esqueleto mínimo entry→goal→exit quando o corpo vem sem `grafo`).

Versionamento/exportação (emenda 2026-08-05 — determinístico, ZERO LLM §10.6):
`GET /os/{id}/jornadas` (lista resumida) · `GET /jornadas/{id}` (versão completa) ·
`POST /jornadas/{id}/restaurar` (clona como NOVA versão rascunho — versões nunca são
editadas retroativamente) · `GET /jornadas/{a}/diff/{b}` (diff.py) ·
`GET /jornadas/{id}/export?formato=json|xml` (download Content-Disposition; JSON =
import nativo do JB, XML = auditoria corporativa com XSD — exportacao.py).

Erros: domínio → RFC-7807 (mapa do M1: NaoEncontrado→404, EstadoInvalido→409) +
traduções deste router: GrafoInvalido→422 com `erros[{no, regra, mensagem}]`
apontando o nó (A1/A3); SaidaDoFlowInvalida→422; GrafoNaoCompilavel→422 com `nos`
(export de grafo com nó `exception` §5.2 — padrão do M9); LLMIndisponivel→503
degraded (§10.6 — gerar/ajustar exigem LLM; PUT/preview/export JAMAIS dependem).
RBAC (§8-M0): mutações exigem analista|lider.
"""

import uuid
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from adapters.publicacoes import publicacoes_vigentes
from adapters.relogio import RelogioSistema
from api.v1.intake import get_llm, get_tracer
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    Tenant,
    _problema_de_dominio,
    get_repositorio_os,
)
from app.errors import problem_response
from application.ports.clock import ClockPort
from application.ports.llm import LLMIndisponivel
from application.ports.repositorio_jornada import RepositorioJornada
from application.ports.repositorio_os import RepositorioOs
from application.services.jornada_service import ServicoJornada
from domain.campanha.erros import ErroDominio
from domain.jornada.erros import GrafoInvalido, GrafoNaoCompilavel, SaidaDoFlowInvalida


class RotaJornada(APIRoute):
    """Traduções do M7 ANTES do mapa genérico do M1 (padrão da RotaCriativo/M6)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except GrafoInvalido as exc:  # A1/A3: 422 apontando o nó
                return problem_response(
                    422,
                    "Unprocessable Entity",
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra={"erros": exc.erros},
                )
            except SaidaDoFlowInvalida as exc:
                return problem_response(
                    422, "Unprocessable Entity", detail=exc.motivo, instance=request.url.path
                )
            except GrafoNaoCompilavel as exc:  # export com nó exception (§5.2) — padrão M9
                return problem_response(
                    422,
                    "Unprocessable Entity",
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra={"nos": exc.nos},
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


def get_relogio(request: Request) -> ClockPort:
    """Relógio atrás de porta (§2.1: clock injetável — padrão do M11): testes fixam
    `app.state.relogio` para provar o determinismo do export XML (B5: mesmo
    grafo+clock ⇒ mesmos bytes); default = relógio de sistema."""
    relogio = getattr(request.app.state, "relogio", None)
    return relogio if relogio is not None else _relogio


def get_servico_jornada(request: Request) -> ServicoJornada:
    """Mesma instância de repositório da OS (app.state) — RepositorioOsMemoria implementa
    todas as portas (tipagem estrutural §2.1); o cast só informa o mypy."""
    repositorio = get_repositorio_os(request)
    return ServicoJornada(
        cast(RepositorioJornada, repositorio),
        cast(RepositorioOs, repositorio),
        get_relogio(request),
        get_llm(request),
        get_tracer(request),
        publicacoes_vigentes(repositorio),  # política vigente do banco (achado 8 UAT #5)
    )


Servico = Annotated[ServicoJornada, Depends(get_servico_jornada)]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class JornadaOut(BaseModel):
    """`jornada_versao` §4.1 — a versão do twin com hash canônico e taxímetro."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    os_id: uuid.UUID
    versao: int
    grafo: dict[str, Any]
    hash: str
    estado: str
    premissas: list[str]
    custo_projetado: float | None
    created_at: datetime | None = None


class JornadaResumoOut(BaseModel):
    """Item de `GET /os/{id}/jornadas` (emenda §8-M7): resumo SEM grafo — a linha do
    tempo de versões do T7 (id, versao, estado, hash, custo, created)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    versao: int
    estado: str
    hash: str
    custo_projetado: float | None
    created_at: datetime | None


class TaximetroOut(BaseModel):
    """Memória de cálculo do taxímetro (A2) — Σ(volume esperado × tarifa vigente)."""

    custo_projetado: float
    memoria: list[dict[str, Any]]
    avisos: list[str]


class GerarJornadaIn(BaseModel):
    instrucoes: str = ""


class GerarJornadaOut(BaseModel):
    """Prévia do flow (§1.1.3): nova versão nasce `rascunho` — simular/aprovar vêm
    depois (M8); `via_ai` + ledger `invocacao` (§4.1)."""

    jornada: JornadaOut
    resumo: str
    taximetro: TaximetroOut
    via_ai: bool = True
    invocacao_id: uuid.UUID


class GrafoIn(BaseModel):
    grafo: dict[str, Any] = Field(min_length=1)


class CriarJornadaIn(BaseModel):
    """`POST /os/{id}/jornada` (emenda §8-M7): "começar do zero" no editor T7 —
    `grafo` opcional; ausente ⇒ esqueleto mínimo entry→goal→exit gerado no servidor."""

    grafo: dict[str, Any] | None = None


class GrafoOut(BaseModel):
    jornada: JornadaOut
    taximetro: TaximetroOut


class AjustarIn(BaseModel):
    instrucoes: str = Field(min_length=1)


class AjustarOut(BaseModel):
    """Diff PROPOSTO (§8-M7): nunca aplicado — aplicar é PUT humano do grafo proposto."""

    jornada_id: uuid.UUID
    aplicado: bool
    grafo_proposto: dict[str, Any]
    diff: dict[str, Any]
    premissas: list[str]
    resumo: str
    valido: bool
    erros: list[dict[str, Any]]
    custo_projetado_atual: float | None
    custo_projetado_proposto: float
    avisos: list[str]
    via_ai: bool = True
    invocacao_id: uuid.UUID


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaJornada, tags=["jornada"])


@router.post("/os/{os_id}/jornada/gerar", status_code=201, response_model=GerarJornadaOut)
async def gerar_jornada(
    os_id: uuid.UUID,
    tenant: Tenant,
    servico: Servico,
    user: Escritor,
    payload: GerarJornadaIn | None = None,
) -> GerarJornadaOut:
    """Flow (120b — §7.2) desenha o JGC a partir do briefing como PRÉVIA (§1.1.3);
    `jgc_validate` (§5.3) e taxímetro (A2) são código — o agente não tem a palavra
    final. Nova versão do twin em `rascunho` (§4.1)."""
    jornada, saida, invocacao, taximetro = servico.gerar(
        tenant, os_id, instrucoes=(payload.instrucoes if payload else ""), portador_id=user.id
    )
    return GerarJornadaOut(
        jornada=JornadaOut.model_validate(jornada),
        resumo=saida.resumo,
        taximetro=TaximetroOut(custo_projetado=jornada.custo_projetado or 0.0, **taximetro),
        invocacao_id=invocacao.id,
    )


@router.post("/os/{os_id}/jornada", status_code=201, response_model=GrafoOut)
async def criar_jornada_manual(
    os_id: uuid.UUID,
    tenant: Tenant,
    servico: Servico,
    user: Escritor,
    payload: CriarJornadaIn | None = None,
) -> GrafoOut:
    """ "Começar do zero" no editor T7 (emenda §8-M7): NOVA versão `rascunho` 100%
    determinística — ZERO LLM (§10.6). Sem `grafo` no corpo, o servidor cria o
    esqueleto mínimo entry→goal→exit (§5.2); com `grafo`, valida §5.3 (422 apontando
    o nó — A1) antes de persistir; taxímetro recalculado (A2)."""
    jornada, taximetro = servico.criar_manual(
        tenant, os_id, grafo=(payload.grafo if payload else None), actor=user.email
    )
    return GrafoOut(
        jornada=JornadaOut.model_validate(jornada),
        taximetro=TaximetroOut(custo_projetado=jornada.custo_projetado or 0.0, **taximetro),
    )


@router.get("/os/{os_id}/jornada", response_model=JornadaOut)
async def obter_jornada(
    os_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> JornadaOut:
    """Última versão do twin da OS (§8-M7, emenda A14) — o canvas T7 abre o grafo
    persistido sem regenerar nada; 404 problem+json quando a OS não tem versão.
    Leitura 100% determinística — LLM proibido neste caminho (§10.6)."""
    return JornadaOut.model_validate(servico.ultima_versao(tenant, os_id))


@router.put("/jornadas/{jornada_id}/grafo", response_model=GrafoOut)
async def atualizar_grafo(
    jornada_id: uuid.UUID, payload: GrafoIn, tenant: Tenant, servico: Servico, user: Escritor
) -> GrafoOut:
    """Salva o grafo editado: valida §5.3 (422 apontando o nó — A1/A3) e RECALCULA o
    taxímetro (A2). Caminho 100% determinístico — nunca depende de LLM (§10.6)."""
    jornada, taximetro = servico.atualizar_grafo(
        tenant, jornada_id, grafo=payload.grafo, actor=user.email
    )
    return GrafoOut(
        jornada=JornadaOut.model_validate(jornada),
        taximetro=TaximetroOut(custo_projetado=jornada.custo_projetado or 0.0, **taximetro),
    )


@router.post("/jornadas/{jornada_id}/ajustar", response_model=AjustarOut)
async def ajustar_jornada(
    jornada_id: uuid.UUID, payload: AjustarIn, tenant: Tenant, servico: Servico, user: Escritor
) -> AjustarOut:
    """Texto livre → diff proposto (§8-M7) — NUNCA aplica direto: humano aplica via
    PUT do `grafo_proposto` (Aplicar/Rejeitar §1.1.3)."""
    proposta, invocacao = servico.ajustar(
        tenant, jornada_id, instrucoes=payload.instrucoes, portador_id=user.id
    )
    return AjustarOut(**proposta, invocacao_id=invocacao.id)


@router.get("/jornadas/{jornada_id}/no/{no_id}/sfmc-preview")
async def sfmc_preview(
    jornada_id: uuid.UUID, no_id: str, tenant: Tenant, servico: Servico, _user: Autenticado
) -> dict[str, Any]:
    """JSON determinístico que o compilador (M9 — §5.4) gerará para o nó, com
    externalKey idempotente `jrn-{hash[0:12]}-{noId}`. LLM proibido neste caminho."""
    return servico.sfmc_preview(tenant, jornada_id, no_id)


# ------------------------------ Versionamento & exportação (emenda §8-M7 2026-08-05)


@router.get("/os/{os_id}/jornadas", response_model=list[JornadaResumoOut])
async def listar_jornadas(
    os_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> list[JornadaResumoOut]:
    """Linha do tempo do twin: TODAS as versões da OS em ordem de `versao` (§4.1),
    resumidas (sem grafo). OS inexistente → 404; OS sem versão → lista vazia.
    Leitura 100% determinística — LLM proibido neste caminho (§10.6)."""
    return [JornadaResumoOut.model_validate(j) for j in servico.listar_versoes(tenant, os_id)]


@router.get("/jornadas/{jornada_id}", response_model=JornadaOut)
async def obter_versao(
    jornada_id: uuid.UUID, tenant: Tenant, servico: Servico, _user: Autenticado
) -> JornadaOut:
    """Versão ESPECÍFICA completa (grafo incluso) — o T7 abre qualquer ponto da linha
    do tempo; 404 problem+json fora do tenant. Determinístico, ZERO LLM (§10.6)."""
    return JornadaOut.model_validate(servico.versao_especifica(tenant, jornada_id))


@router.post("/jornadas/{jornada_id}/restaurar", status_code=201, response_model=GrafoOut)
async def restaurar_jornada(
    jornada_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Escritor
) -> GrafoOut:
    """Restaura clonando como NOVA versão `rascunho` — versões NUNCA são editadas
    retroativamente (§1.2 non-goals). Grafo e hash idênticos à origem; taxímetro
    recalculado (A2); simulação/previsto não acompanham (§6). ZERO LLM."""
    jornada, taximetro = servico.restaurar(tenant, jornada_id, actor=user.email)
    return GrafoOut(
        jornada=JornadaOut.model_validate(jornada),
        taximetro=TaximetroOut(custo_projetado=jornada.custo_projetado or 0.0, **taximetro),
    )


@router.get("/jornadas/{jornada_a}/diff/{jornada_b}")
async def diff_jornadas(
    jornada_a: uuid.UUID,
    jornada_b: uuid.UUID,
    tenant: Tenant,
    servico: Servico,
    _user: Autenticado,
) -> dict[str, Any]:
    """Diff estrutural entre duas versões (domain/jornada/diff.py — o MESMO diff do
    ajustar/M11): nós/arestas adicionados·removidos·alterados + `meta_alterada`,
    com `de`/`para` (id, versao, hash). Versões de OSs diferentes → 409."""
    return servico.diff_versoes(tenant, jornada_a, jornada_b)


@router.get("/jornadas/{jornada_id}/export")
async def exportar_jornada(
    jornada_id: uuid.UUID,
    tenant: Tenant,
    servico: Servico,
    _user: Autenticado,
    formato: Annotated[Literal["json", "xml"], Query()] = "json",
) -> Response:
    """Download (Content-Disposition) da interaction compilada — determinístico,
    ZERO LLM (§5.4/§10.6). `json` = spec de interaction do Journey Builder (import
    NATIVO do JB — REST /interaction/v1/interactions, via compilador M9);
    `xml` = a MESMA spec canônica com manifest (hash JGC, versao, geradoEm via
    ClockPort, plataforma Jornada), validável contra domain/jornada/journey_export.xsd
    — atende integração/auditoria corporativa (o JB não importa XML).
    Formato fora de json|xml → 422; nó `exception` no grafo → 422 com `nos` (§5.2)."""
    conteudo, media_type, filename = servico.exportar(tenant, jornada_id, formato=formato)
    return Response(
        content=conteudo,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
