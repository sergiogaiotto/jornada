"""Rotas do M12 (parte 2) · Políticas + Auditoria (SDD §8-M12) — tags OpenAPI
`policies` e `auditoria` (mesmo módulo M12, dois recursos — padrão M8 T9/T10).

Policy-as-code: `GET /policies` · `POST /policies` (draft com versão sequencial;
conteúdo validado no conjunto FECHADO §4.1 → 422 com a lista `erros`) ·
`POST /policies/{id}/publicar` (draft→publicada; evento `policy.published` §2.3;
resposta inclui o relatório de policy drift) · `GET /policies/drift` (OSs em voo
congeladas em versão antiga que VIOLARIAM a nova — §8-M12) ·
`POST /policies/drift/pendencias` (pendências de adequação OPCIONAIS: não
bloqueantes, origem `policy_drift:v{n}`, idempotente).

Auditoria (Art. 20 LGPD): `GET /auditoria` (filtros tipo/agente/OS/via_ai; evento
via_ai clicável com detalhe completo do ledger `invocacao`) ·
`POST /auditoria/reconstruir/{invocacao_id}` (devolve EXATAMENTE
input/evidências/output/judge da época — A3).

Erros: mapa RFC-7807 do M1 + tradução própria: PolicyInvalida→422 (lista `erros`,
padrão do parser §7.1). RBAC (§8-M0): leitura = autenticado; criar draft/pendências
= analista|lider; PUBLICAR política = lider (portão de plataforma, como publicar
skill); reconstrução Art. 20 = dpo|lider (atende o titular; admin sempre passa).
"""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel

from adapters.atelie_seeds import semear_atelie, semear_politicas
from adapters.relogio import RelogioSistema
from api.v1.os_governanca import (
    Autenticado,
    Escritor,
    Tenant,
    _problema_de_dominio,
    get_repositorio_os,
    get_servico_os,
)
from app.auth import Usuario, require_role
from app.config import get_settings
from app.errors import problem_response
from application.ports.repositorio_atelie import RepositorioAtelie
from application.ports.repositorio_plataforma import RepositorioPlataforma
from application.services.os_service import ServicoOs
from application.services.plataforma_service import ServicoPlataforma
from domain.campanha.erros import ErroDominio
from domain.governanca.erros import PolicyInvalida


class RotaPlataforma(APIRoute):
    """Traduções do M12 parte 2 ANTES do mapa genérico do M1 (padrão M4/M5/M12 p1)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except PolicyInvalida as exc:  # conteúdo §4.1: 422 com a lista de erros
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


def get_repositorio_plataforma(request: Request) -> RepositorioPlataforma:
    """Mesma instância do repositório da OS (app.state — tipagem estrutural §2.1),
    com a política v1 E o roster do Ateliê SEMEADOS na primeira passagem (§11.4 —
    a auditoria resolve o nome do agente pelo roster); idempotente."""
    repositorio = cast(RepositorioPlataforma, get_repositorio_os(request))
    tenant_default = get_settings().default_tenant
    agora = _relogio.agora()
    semear_politicas(repositorio, tenant_id=tenant_default, agora=agora)
    semear_atelie(cast(RepositorioAtelie, repositorio), tenant_id=tenant_default, agora=agora)
    return repositorio


def get_servico_plataforma(
    request: Request, servico_os: Annotated[ServicoOs, Depends(get_servico_os)]
) -> ServicoPlataforma:
    return ServicoPlataforma(get_repositorio_plataforma(request), _relogio, servico_os)


Servico = Annotated[ServicoPlataforma, Depends(get_servico_plataforma)]
Publicador = Annotated[Usuario, Depends(require_role("lider"))]
ReconstrutorLgpd = Annotated[Usuario, Depends(require_role("dpo", "lider"))]

# ------------------------------------------------- Contratos Pydantic (§1.3.2, §4.1)


class PolicyCriar(BaseModel):
    conteudo: dict[str, Any]  # conjunto fechado §4.1 — validado no domínio (422 + erros)


# ------------------------------------------------------------------------- Rotas
router_policies = APIRouter(route_class=RotaPlataforma, tags=["policies"])
router_auditoria = APIRouter(route_class=RotaPlataforma, tags=["auditoria"])


@router_policies.get("/policies")
async def listar_policies(tenant: Tenant, servico: Servico, _user: Autenticado) -> dict[str, Any]:
    """Versões da política (§4.1 `policy_versao`) + a publicada ATUAL (a que o GO
    congela em `os.frozen.policy_version` §8-M4-A2)."""
    return servico.listar_policies(tenant)


@router_policies.post("/policies", status_code=201)
async def criar_policy(
    payload: PolicyCriar, tenant: Tenant, servico: Servico, user: Escritor
) -> dict[str, Any]:
    """Draft com versão SEQUENCIAL; conteúdo validado por CÓDIGO no conjunto fechado
    do §4.1 (compliance nunca é LLM §1.1.3) — inválido → 422 com a lista `erros`."""
    return servico.criar_policy(tenant, conteudo=payload.conteudo, actor=user.email)


@router_policies.post("/policies/{policy_id}/publicar")
async def publicar_policy(
    policy_id: uuid.UUID, tenant: Tenant, servico: Servico, user: Publicador
) -> dict[str, Any]:
    """draft→publicada (evento `policy.published` §2.3); NÃO toca `os.frozen` de OS
    em voo (simetria com A2) — a resposta já traz o relatório de policy drift."""
    return servico.publicar_policy(tenant, policy_id, actor=user.email)


@router_policies.get("/policies/drift")
async def relatorio_drift(tenant: Tenant, servico: Servico, _user: Autenticado) -> dict[str, Any]:
    """Relatório de policy drift (§8-M12): OSs em VOO congeladas em versão antiga que
    VIOLARIAM a política publicada atual (violações calculadas por código)."""
    return servico.relatorio_drift(tenant)


@router_policies.post("/policies/drift/pendencias", status_code=201)
async def abrir_pendencias_adequacao(
    tenant: Tenant, servico: Servico, user: Escritor
) -> dict[str, Any]:
    """Pendências de adequação OPCIONAIS (§8-M12): NÃO bloqueantes (política nova não
    trava retroativamente OS aprovada na antiga), origem `policy_drift:v{n}`,
    idempotente por origem."""
    return servico.abrir_pendencias_adequacao(tenant, actor=user.email)


@router_auditoria.get("/auditoria")
async def listar_auditoria(
    tenant: Tenant,
    servico: Servico,
    user: Autenticado,
    tipo: Annotated[str | None, Query(max_length=100)] = None,
    agente: Annotated[str | None, Query(max_length=100)] = None,
    os_id: Annotated[uuid.UUID | None, Query()] = None,
    via_ai: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Trilha de auditoria (outbox §2.3) com filtros §8-M12; evento via_ai carrega o
    detalhe do ledger `invocacao`.

    Auditoria da onda 6 (J05): o CONTEÚDO do ledger — input/output/judge/evidências —
    é dado do Art. 20 e só vai no payload para quem pode RECONSTRUIR (dpo|lider|admin),
    o mesmo portão de `POST /auditoria/reconstruir`. Para os demais papéis a trilha e
    as MÉTRICAS operacionais (agente, skill, tokens, latência) continuam visíveis — o
    que a T16 precisa mostrar —, mas o prompt/resposta não vazam pela lista. Antes do
    J05 nenhuma tela consumia esta rota, então a inconsistência (lista aberta, reconstruir
    fechado) era latente; o painel novo a expôs."""
    pode_ver_conteudo = bool({"dpo", "lider", "admin"} & set(user.papeis))
    return servico.listar_auditoria(
        tenant,
        tipo=tipo,
        agente=agente,
        os_id=os_id,
        via_ai=via_ai,
        limit=limit,
        offset=offset,
        incluir_conteudo=pode_ver_conteudo,
    )


@router_auditoria.post("/auditoria/reconstruir/{invocacao_id}")
async def reconstruir_invocacao(
    invocacao_id: uuid.UUID, tenant: Tenant, servico: Servico, user: ReconstrutorLgpd
) -> dict[str, Any]:
    """Art. 20 LGPD (A3): devolve EXATAMENTE input/evidências/output/judge da época —
    o ledger é imutável (skill nova publicada depois NÃO muda a resposta); a
    reconstrução em si vira evento `auditoria.reconstruida`."""
    return servico.reconstruir(tenant, invocacao_id, actor=user.email)
