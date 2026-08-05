"""Rotas do M-Guia — chat "IA, me ajude com esta página" (§8-M-Guia, emenda
2026-08-05) — tag OpenAPI `ajuda`.

`POST /ajuda/perguntar`: agente ajuda (LLM 20b — §3: resumos de UI) responde SÓ
sobre a plataforma Jornada e a página em questão. O front envia o conteúdo do guia
da página como `contexto` (fonte única em frontend/src/guia/conteudo.ts — duplicar
no back seria drift) e o contrato valida ≤ 8k chars (422 além disso). Ledger
`invocacao` via_ai com `os_id` NULL (a ajuda é da página, não de uma OS) + trace
Langfuse (§10.8). Hub fora / `forced_off` → 503 `modo: degraded` (§10.6) — o front
oferece o guia estático como modo manual. RBAC: leitura assistida — qualquer
autenticado (padrão do insight §8-M10); a rota não muda estado além do ledger.
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from api.v1.compilador import _relogio
from api.v1.intake import get_llm, get_tracer
from api.v1.os_governanca import Autenticado, Tenant, get_repositorio_os
from app.errors import problem_response
from application.ports.llm import LLMIndisponivel
from application.ports.repositorio_ajuda import RepositorioAjuda
from application.services.ajuda_service import ServicoAjuda


class RotaAjuda(APIRoute):
    """LLMIndisponivel→503 degraded (§10.6) ANTES do mapa genérico do M1."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except LLMIndisponivel as exc:  # §10.6: UI oferece o guia estático
                return problem_response(
                    503,
                    "Service Unavailable",
                    detail=str(exc),
                    instance=request.url.path,
                    extra={"modo": "degraded"},
                )

        return handler


# ------------------------------------------------------------------ Dependências


def get_servico_ajuda(request: Request) -> ServicoAjuda:
    """Mesma instância de repositório (app.state) — RepositorioOsMemoria implementa
    todas as portas (tipagem estrutural §2.1); o cast só informa o mypy (padrão M5)."""
    return ServicoAjuda(
        cast(RepositorioAjuda, get_repositorio_os(request)),
        _relogio,
        get_llm(request),
        get_tracer(request),
    )


Servico = Annotated[ServicoAjuda, Depends(get_servico_ajuda)]

# ------------------------------------------- Contratos Pydantic (§1.3.2, §8-M-Guia)


class MensagemHistorico(BaseModel):
    """Turno anterior da sessão do navegador (nada persistido além do ledger)."""

    papel: Literal["usuario", "ia"]
    texto: str = Field(min_length=1, max_length=4000)


class AjudaPerguntaIn(BaseModel):
    pagina: str = Field(min_length=1, max_length=60)  # chave do guia (ex.: "cockpit")
    pergunta: str = Field(min_length=1, max_length=2000)
    # Conteúdo do guia da página, enviado pelo FRONT (fonte única) — ≤ 8k chars (§8-M-Guia)
    contexto: str = Field(min_length=1, max_length=8000)
    historico: list[MensagemHistorico] = Field(default_factory=list, max_length=20)


class AjudaRespostaOut(BaseModel):
    resposta: str
    pagina: str
    via_ai: bool = True
    invocacao_id: uuid.UUID


# ------------------------------------------------------------------------- Rotas
router = APIRouter(route_class=RotaAjuda, tags=["ajuda"])


@router.post("/ajuda/perguntar", response_model=AjudaRespostaOut)
async def perguntar(
    payload: AjudaPerguntaIn, tenant: Tenant, servico: Servico, user: Autenticado
) -> AjudaRespostaOut:
    """§8-M-Guia: pergunta + contexto do guia da página → resposta didática do
    agente ajuda (20b). Fora da plataforma → recusa (instrução da skill §7.1);
    hub fora → 503 degraded (§10.6)."""
    resultado = servico.perguntar(
        tenant,
        pagina=payload.pagina,
        pergunta=payload.pergunta,
        contexto=payload.contexto,
        historico=[m.model_dump() for m in payload.historico],
        portador_id=user.id,
    )
    return AjudaRespostaOut(
        resposta=resultado["resposta"],
        pagina=resultado["pagina"],
        invocacao_id=resultado["invocacao_id"],
    )
