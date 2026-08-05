"""Routers /api/v1 — um router por módulo do §8; nomes = tags OpenAPI.

M0 não define endpoints de negócio; os routers dos módulos M1+ são incluídos aqui.
"""

from fastapi import APIRouter

from api.v1 import (
    audiencia,
    compilador,
    criativo,
    datacloud,
    esteira,
    insight,
    intake,
    jornada,
    lancamento,
    os_governanca,
    portoes,
    prevoo,
    simulador,
    validacao,
)

api_router = APIRouter()

api_router.include_router(os_governanca.router)  # M1 · Núcleo OS/governança (§8-M1)
api_router.include_router(esteira.router)  # M2 · Esteira de Produção ex-Hike (§8-M2)
api_router.include_router(intake.router)  # M3 · Intake & Consultor (§8-M3)
api_router.include_router(validacao.router)  # M4 · Validação campo-a-campo & War Room (§8-M4)
api_router.include_router(audiencia.router)  # M5 · Audiência + Guard (§8-M5)
api_router.include_router(datacloud.router)  # M5 · Data Cloud T5a (§8-M5)
api_router.include_router(criativo.router)  # M6 · Criativo T6 (§8-M6)
api_router.include_router(jornada.router)  # M7 · Twin Canvas T7 (§5, §8-M7)
api_router.include_router(simulador.router)  # M8 (parte 1) · Simulador T8 (§6, §8-M8)
api_router.include_router(portoes.router_portoes)  # M8 (parte 2) · Portões T9 (§8-M8)
api_router.include_router(portoes.router_aprovacao)  # M8 (parte 2) · Aprovação T10 (§8-M8)
api_router.include_router(compilador.router)  # M9 (fatia 1) · Compilador plan/apply (§5.4)
api_router.include_router(prevoo.router)  # M9 (fatia 2) · Pré-voo & Drift T11 (§5.4.5, §8-M9)
api_router.include_router(lancamento.router)  # M10 (parte 1) · Torre de Lançamento T12 (§8-M10)
api_router.include_router(insight.router)  # M10 (parte 3) · Pergunte aos Dados T13/T14 (§8-M10)
