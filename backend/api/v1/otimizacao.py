"""Rotas do M11 · Otimização/Retro/Calibração T15 (SDD §8-M11) — tag OpenAPI
`otimizacao`.

`GET /os/{id}/propostas` (optimize: diff JGC + impacto PRÉ-SIMULADO via
SimuladorService, ranqueadas lift×esforço×risco — propor é a ÚNICA ação autônoma) ·
`POST /propostas/{id}/aprovar` (nova `jornada_versao` + mini-ciclo M8→M9 expresso:
nova aprovação EXPRESSA antes do apply) · `POST /propostas/{id}/rejeitar` (motivo
OBRIGATÓRIO — vira sinal) · `POST /experimentos/{id}/apurar` (ANTI-PEEKING: 425 Too
Early antes do fim da janela — A1; depois lift com IC95 e significativo SÓ com IC
excluindo zero — A2) · `POST /os/{id}/clonar-com-aprendizados` (A3) ·
`POST /calibracao/publicar` (CalibrateService — backtest OBRIGATÓRIO, versionado em
`calibracao_prior`).

ZERO LLM em apurar/aprovar/rejeitar/clonar/calibrar (§10.6) — só o PROPOR invoca o
optimize (e degrada com hub fora, sem 503 num GET). Erros: mapa RFC-7807 do M1 +
traduções próprias: ApuracaoAntesDaJanela→425 Too Early ·
GrafoInvalido/MotivoObrigatorio/SaidaDoOptimizeInvalida→422 · LLMIndisponivel→503.
RBAC (§8-M0): mutações exigem analista|lider; GET propostas é leitura autenticada
(a geração é a ação autônoma do agente — decidir continua humano §1.1.3).
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from adapters.relogio import RelogioSistema
from api.v1.intake import get_embedding, get_llm, get_tracer
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    Tenant,
    _problema_de_dominio,
    get_repositorio_os,
)
from api.v1.simulador import get_servico_simulador
from app.errors import problem_response
from application.ports.clock import ClockPort
from application.ports.llm import LLMIndisponivel
from application.ports.repositorio_otimizacao import RepositorioOtimizacao
from application.services.otimizacao_service import ServicoCalibracao, ServicoOtimizacao
from domain.campanha.erros import ErroDominio, JustificativaObrigatoria
from domain.jornada.erros import GrafoInvalido
from domain.otimizacao.erros import ApuracaoAntesDaJanela, SaidaDoOptimizeInvalida


class RotaOtimizacao(APIRoute):
    """Traduções do M11 ANTES do mapa genérico do M1 (padrão M4/M5/M8/M10)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except ApuracaoAntesDaJanela as exc:  # A1: anti-peeking
                return problem_response(
                    425,
                    "Too Early",
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra={"fim_janela": exc.fim_janela.isoformat() if exc.fim_janela else None},
                )
            except GrafoInvalido as exc:
                return problem_response(
                    422,
                    "Unprocessable Entity",
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra={"erros": exc.erros},
                )
            except (SaidaDoOptimizeInvalida, JustificativaObrigatoria) as exc:
                return problem_response(
                    422, "Unprocessable Entity", detail=exc.motivo, instance=request.url.path
                )
            except LLMIndisponivel as exc:  # §10.6 (mutação que exigisse LLM)
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
    """Relógio atrás de porta (§2.1: clock injetável): testes manipulam
    `app.state.relogio` para provar o anti-peeking A1 (425→200 SÓ pelo avanço do
    relógio, sem tocar telemetria); default = relógio de sistema."""
    relogio = getattr(request.app.state, "relogio", None)
    return relogio if relogio is not None else _relogio


def get_servico_otimizacao(request: Request) -> ServicoOtimizacao:
    """Mesma instância de repositório da OS (app.state) — RepositorioOsMemoria implementa
    todas as portas (tipagem estrutural §2.1); o cast só informa o mypy."""
    repositorio = cast(RepositorioOtimizacao, get_repositorio_os(request))
    return ServicoOtimizacao(
        repositorio,
        get_relogio(request),
        get_llm(request),
        get_tracer(request),
        get_servico_simulador(request),  # impacto pré-simulado (§8-M11)
        embedding=get_embedding(request),  # A11: embed melhor-esforço na promoção (A3)
    )


def get_servico_calibracao(request: Request) -> ServicoCalibracao:
    repositorio = cast(RepositorioOtimizacao, get_repositorio_os(request))
    return ServicoCalibracao(repositorio, get_relogio(request))


Servico = Annotated[ServicoOtimizacao, Depends(get_servico_otimizacao)]
Calibrador = Annotated[ServicoCalibracao, Depends(get_servico_calibracao)]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class RejeitarIn(BaseModel):
    motivo: str = Field(min_length=1, max_length=2000)  # §8-M11: motivo vira sinal


class ClonarIn(BaseModel):
    nome: str | None = Field(default=None, max_length=200)
    tshirt: Literal["P", "M", "G", "GG"] | None = None


class CalibrarIn(BaseModel):
    tipo_campanha: str | None = Field(default=None, max_length=100)  # §4.1 calibracao_prior


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaOtimizacao, tags=["otimizacao"])


@router.get("/os/{os_id}/propostas")
async def propostas_da_os(
    os_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Autenticado
) -> dict[str, Any]:
    """Propostas do optimize (§8-M11): diff JGC + impacto pré-simulado (§6),
    ranqueadas lift×esforço×risco. Sem pendentes, o agente PROPÕE (única ação
    autônoma; hub fora → lista degradada, nunca 503 na leitura §10.6)."""
    return servico.propostas(tenant, os_id, portador_id=user.id)


@router.post("/propostas/{proposta_id}/aprovar")
async def aprovar_proposta(
    proposta_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Escritor
) -> dict[str, Any]:
    """Gera NOVA `jornada_versao` (rascunho) e devolve o mini-ciclo M8→M9 expresso —
    snapshot NOVO + aprovação EXPRESSA (link mágico) antes de qualquer apply."""
    return servico.aprovar(tenant, proposta_id, actor=user.email)


@router.post("/propostas/{proposta_id}/rejeitar")
async def rejeitar_proposta(
    proposta_id: uuid.UUID,
    payload: RejeitarIn,
    tenant: Tenant,
    servico: Servico,
    user: Escritor,
) -> dict[str, Any]:
    """Rejeita a proposta; o motivo (obrigatório) vira SINAL para o optimize
    (§8-M11) — não re-propor o que já foi rejeitado por essa razão."""
    return servico.rejeitar(tenant, proposta_id, motivo=payload.motivo, actor=user.email)


@router.post("/experimentos/{experimento_id}/apurar")
async def apurar_experimento(
    experimento_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Escritor
) -> dict[str, Any]:
    """Apuração (§8-M11): 425 Too Early antes do fim da janela (A1 anti-peeking);
    depois, lift com IC95 e `significativo` SÓ com IC excluindo zero (A2). Resultado
    imutável em `experimento.resultado` (§4.1); significativo promove aprendizado à
    base RAG `resultados` (A3, stub de ingestão)."""
    return servico.apurar(tenant, experimento_id, actor=user.email)


@router.post("/os/{os_id}/clonar-com-aprendizados", status_code=201)
async def clonar_com_aprendizados(
    os_id: uuid.UUID,
    tenant: Tenant,
    servico: Servico,
    user: Escritor,
    payload: ClonarIn | None = None,
) -> dict[str, Any]:
    """Clone (§8-M11-A3): nova OS herdando aprendizados ACEITOS/PROMOVIDOS
    (`herdado_de`) + priors VIGENTES (última `calibracao_prior` publicada)."""
    parametros = payload or ClonarIn()
    return servico.clonar_com_aprendizados(
        tenant,
        os_id,
        nome=parametros.nome,
        tshirt=parametros.tshirt,
        created_by=user.id,
        actor=user.email,
    )


@router.post("/calibracao/publicar", status_code=201)
async def publicar_calibracao(
    tenant: Tenant,
    servico: Calibrador,
    user: Escritor,
    payload: CalibrarIn | None = None,
) -> dict[str, Any]:
    """CalibrateService (§8-M11): compara previsto congelado × realizado, propõe
    priors novos e publica SÓ com backtest aprovado — versionado em
    `calibracao_prior` (§4.1); o simulador passa a preferi-los (§6)."""
    parametros = payload or CalibrarIn()
    return servico.publicar(tenant, tipo_campanha=parametros.tipo_campanha, actor=user.email)
