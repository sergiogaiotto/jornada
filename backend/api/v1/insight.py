"""Rotas do M10 · parte 3 — Pergunte aos Dados T13/T14 (SDD §8-M10, §7.2 insight) —
tag OpenAPI `insight`.

`POST /os/{id}/perguntar`: agente insight (LLM 120b) traduz NL → consulta NOMEADA
`vw_metricas_*` + parâmetros do dicionário versionado (camada semântica em
domain/lancamento/semantica.py) — NUNCA SQL livre; a resposta anexa a consulta
executada (§8-M10: "resposta inclui a query"). Fora do escopo (ex.: pedido de CPF)
⇒ RECUSA PADRÃO sem executar nada (A4) — a pré-guarda de PII recusa SEM chamar o
LLM (§1.3.5/§10.2). Ledger `invocacao` via_ai + trace Langfuse (§10.8).

Router SEPARADO do lancamento.py de propósito: aquele caminho (breakers/kill) é
crítico e LLM-proibido (§10.6); perguntar é leitura assistida por IA — hub fora ⇒
503 degraded, e NADA do caminho crítico depende desta rota. Erros: mapa RFC-7807
do M1 + LLMIndisponivel→503 (padrão M5). RBAC: leitura — qualquer autenticado
(padrão GET /os/{id}/monitor); a rota não muda estado além do ledger.
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from adapters.publicacoes import publicacoes_vigentes
from api.v1.compilador import _relogio
from api.v1.intake import get_llm, get_tracer
from api.v1.os_governanca import (
    Autenticado,
    Tenant,
    _problema_de_dominio,
    get_repositorio_os,
)
from app.errors import problem_response
from application.ports.llm import LLMIndisponivel
from application.ports.publicacoes_ia import PublicacoesIaPort
from application.ports.repositorio_insight import RepositorioInsight
from application.services.insight_service import ServicoInsight
from domain.campanha.erros import ErroDominio


class RotaInsight(APIRoute):
    """LLMIndisponivel→503 degraded (§10.6) ANTES do mapa genérico do M1."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except LLMIndisponivel as exc:  # §10.6: UI oferece modo manual
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


def get_servico_insight(request: Request) -> ServicoInsight:
    """Mesma instância de repositório (app.state) — RepositorioOsMemoria implementa
    todas as portas (tipagem estrutural §2.1); o cast só informa o mypy (padrão M5)."""
    repositorio = get_repositorio_os(request)
    return ServicoInsight(
        cast(RepositorioInsight, repositorio),
        _relogio,
        get_llm(request),
        get_tracer(request),
        cast(PublicacoesIaPort, publicacoes_vigentes(repositorio)),  # política de IA (§10.2)
    )


Servico = Annotated[ServicoInsight, Depends(get_servico_insight)]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §7.2)


class PerguntaIn(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2000)  # NL — T13/T14


class ConsultaExecutadaOut(BaseModel):
    """A consulta NOMEADA que respondeu à pergunta — sempre anexada (§8-M10)."""

    nome: str  # vw_metricas_*
    metrica: str
    versao: str
    parametros: dict[str, Any]
    sql: str  # definição da view (a "query" — §7.2: "mostra a query")
    resultado: dict[str, Any]


class PerguntaOut(BaseModel):
    """Recusa NÃO é erro (A4): 200 com `recusado=true`, `consulta_executada=null`
    e a recusa padrão em `resposta` — zero consulta executada."""

    resposta: str
    recusado: bool
    motivo_recusa: str | None
    consulta_executada: ConsultaExecutadaOut | None
    camada_semantica: dict[str, Any]  # {versao, consultas: [vw_metricas_*]}
    via_ai: bool = True
    invocacao_id: uuid.UUID


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaInsight, tags=["insight"])


@router.post("/os/{os_id}/perguntar", response_model=PerguntaOut)
async def perguntar(
    os_id: uuid.UUID, payload: PerguntaIn, tenant: Tenant, servico: Servico, user: Autenticado
) -> PerguntaOut:
    """§8-M10 (parte 3): NL→consulta nomeada sobre a camada semântica `vw_metricas_*`
    (roas, lift, custo_por_pedido, atingimento_meta); resposta inclui a consulta
    executada; fora do escopo → recusa padrão SEM executar nada (A4). OS sem
    Previsto congelado → 409 (mesma régua do monitor §1.1.2)."""
    resultado = servico.perguntar(tenant, os_id, pergunta=payload.pergunta, portador_id=user.id)
    return PerguntaOut(
        resposta=resultado["resposta"],
        recusado=resultado["recusado"],
        motivo_recusa=resultado["motivo_recusa"],
        consulta_executada=(
            None
            if resultado["consulta_executada"] is None
            else ConsultaExecutadaOut.model_validate(resultado["consulta_executada"])
        ),
        camada_semantica=resultado["camada_semantica"],
        invocacao_id=resultado["invocacao_id"],
    )
