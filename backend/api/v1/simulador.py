"""Rotas do M8 (parte 1) · Simulador T8 / Ensaio Geral (SDD §6, §8-M8) — tag
OpenAPI `simulador`.

`POST /jornadas/{id}/simular` (§6; persiste resultado em `jornada_versao.simulacao`) ·
`POST /jornadas/{id}/congelar-previsto` · `POST /simulacoes/comparar` (cenários).

ZERO LLM neste caminho (§10.6): Monte Carlo é código determinístico; RngPort/ClockPort
injetáveis → mesma seed reproduz os mesmos P10/P50/P90 (A1). Erros: domínio → RFC-7807
(mapa do M1: NaoEncontrado→404; SegmentoAusente/SimulacaoAusente/EstadoInvalido→409)
+ tradução deste router: GrafoInvalido→422 com `erros[{no, regra, mensagem}]`.
RBAC (§8-M0): mutações exigem analista|lider.
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from adapters.aleatorio import rng_disponivel
from adapters.relogio import RelogioSistema
from api.v1.os_governanca import Escritor, Tenant, _problema_de_dominio, get_repositorio_os
from app.errors import problem_response
from application.ports.repositorio_jornada import RepositorioJornada
from application.ports.repositorio_os import RepositorioOs
from application.ports.rng import RngPort
from application.services.persona_service import ServicoPersona
from application.services.simulador_service import (
    N_PERSONAS_DEFAULT,
    RUNS_DEFAULT,
    SEED_DEFAULT,
    ServicoSimulador,
)
from domain.campanha.erros import ErroDominio
from domain.jornada.erros import GrafoInvalido


class RotaSimulador(APIRoute):
    """GrafoInvalido→422 apontando o nó ANTES do mapa genérico do M1 (padrão M4/M5)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except GrafoInvalido as exc:
                return problem_response(
                    422,
                    "Unprocessable Entity",
                    detail=exc.motivo,
                    instance=request.url.path,
                    extra={"erros": exc.erros},
                )
            except ErroDominio as exc:
                return _problema_de_dominio(exc, request.url.path)

        return handler


# ------------------------------------------------------------------ Dependências
_relogio = RelogioSistema()
_personas = ServicoPersona()


def get_rng(request: Request) -> RngPort:
    """RNG atrás de porta (§2.1): numpy vetorizado quando instalado, stdlib puro senão;
    testes podem trocar via `app.state.rng` (mesmo padrão de `app.state.llm`)."""
    rng = getattr(request.app.state, "rng", None)
    if rng is None:
        rng = rng_disponivel()
        request.app.state.rng = rng
    return rng


def get_servico_simulador(request: Request) -> ServicoSimulador:
    """Mesma instância de repositório da OS (app.state) — RepositorioOsMemoria implementa
    todas as portas (tipagem estrutural §2.1); o cast só informa o mypy."""
    repositorio = get_repositorio_os(request)
    return ServicoSimulador(
        cast(RepositorioJornada, repositorio),
        cast(RepositorioOs, repositorio),
        _relogio,
        get_rng(request),
        _personas,
    )


Servico = Annotated[ServicoSimulador, Depends(get_servico_simulador)]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class SimularIn(BaseModel):
    """Parâmetros do run (§6: N=10.000 personas × K=500 runs; seed fixa por run)."""

    seed: int = SEED_DEFAULT
    runs: int = Field(default=RUNS_DEFAULT, ge=10, le=5000)
    n_personas: int = Field(default=N_PERSONAS_DEFAULT, ge=100, le=1_000_000)


class JornadaSimuladaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    os_id: uuid.UUID
    versao: int
    hash: str
    estado: str
    simulacao: dict[str, Any] | None
    previsto: dict[str, Any] | None


class CompararIn(BaseModel):
    jornada_ids: list[uuid.UUID] = Field(min_length=2, max_length=10)


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaSimulador, tags=["simulador"])


@router.post("/jornadas/{jornada_id}/simular", response_model=JornadaSimuladaOut)
async def simular(
    jornada_id: uuid.UUID,
    tenant: Tenant,
    servico: Servico,
    user: Escritor,
    payload: SimularIn | None = None,
) -> JornadaSimuladaOut:
    """Ensaio Geral (§6) — portão obrigatório: Monte Carlo com relógio virtual (waits,
    quiet hours, throttle, STO amostrado, frequency split via governor); saída
    P10/P50/P90 persistida em `jornada_versao.simulacao`; semáforo §6 (A1/A2)."""
    parametros = payload or SimularIn()
    jornada = servico.simular(
        tenant,
        jornada_id,
        seed=parametros.seed,
        runs=parametros.runs,
        n_personas=parametros.n_personas,
        actor=user.email,
    )
    return JornadaSimuladaOut.model_validate(jornada)


@router.post("/jornadas/{jornada_id}/congelar-previsto", response_model=JornadaSimuladaOut)
async def congelar_previsto(
    jornada_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Escritor
) -> JornadaSimuladaOut:
    """Congela a simulação corrente como Previsto (§1.1.2: régua do pós-disparo);
    sem simulação persistida → 409."""
    return JornadaSimuladaOut.model_validate(
        servico.congelar_previsto(tenant, jornada_id, actor=user.email)
    )


@router.post("/simulacoes/comparar")
async def comparar(
    payload: CompararIn, tenant: Tenant, servico: Servico, user: Escritor
) -> dict[str, Any]:
    """Cenários lado a lado (§8-M8): P50s por versão + deltas vs baseline (o primeiro)."""
    return servico.comparar(tenant, payload.jornada_ids)
