"""Rotas de administração de dados (SDD §10.4) — tag OpenAPI `admin`.

`POST /admin/purge` — aplica a retenção (`retencao_dias`) da política VIGENTE do banco
sobre `telemetry_event` e `dc_segment_cache`, registrando a destruição no outbox
(`dados.purgados`, §2.3). Fecha o achado 20 do UAT #5: até aqui `retencao_dias` era
validado, exibido na tela de Políticas e não tinha consumidor nenhum.

**Dry-run por default.** Apagar dado é irreversível, então a rota SÓ destrói com
`?aplicar=true`; sem o parâmetro devolve o relatório do que seria apagado — os mesmos
números, calculados pelo mesmo predicado. Idempotente: rodar de novo não apaga nada
porque nada mais é elegível (não há flag de "já rodou" — a idempotência é do dado).

**Agendamento: cron do HOST, não scheduler na aplicação.** Decisão registrada no
CHANGELOG: acrescentar apscheduler/celery para um job diário traria um segundo modelo
de execução (worker, lease, retry, timezone) e um novo modo de falha silenciosa —
justamente o que o §10.4 já sofreu. Um `curl` no cron do host é observável (log do
cron, código HTTP, evento no outbox), roda no mesmo binário e é revogável apagando uma
linha. Exemplo no README/docker-compose.

RBAC: `dpo` (admin sempre passa, §8-M0) — é a função que responde pelo titular na LGPD.
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.routing import APIRoute

from adapters.publicacoes import publicacoes_vigentes
from adapters.relogio import RelogioSistema
from api.v1.os_governanca import Tenant, get_repositorio_os
from app.auth import Usuario, require_role
from app.errors import problem_response
from application.ports.publicacoes import PublicacoesPort
from application.ports.repositorio_purge import RepositorioPurge
from application.services.purge_service import RetencaoInvalida, ServicoPurge

_relogio = RelogioSistema()


class RotaAdmin(APIRoute):
    """`RetencaoInvalida` → 422: política vigente com `retencao_dias` fora do §4.1.
    Falha DURA — purgar com valor absurdo apagaria a base."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except RetencaoInvalida as exc:
                return problem_response(
                    422,
                    "Unprocessable Entity",
                    detail=exc.motivo,
                    instance=request.url.path,
                )

        return handler


def get_servico_purge(request: Request) -> ServicoPurge:
    """Mesma instância de repositório do app (tipagem estrutural §2.1): `RepositorioPurge`
    é implementada por RepositorioOsMemoria e RepositorioSql. A régua da retenção vem
    da fábrica ÚNICA de publicações — nunca de constante compilada (achado 8 UAT #5)."""
    repositorio = get_repositorio_os(request)
    return ServicoPurge(
        cast(RepositorioPurge, repositorio),
        _relogio,
        cast(PublicacoesPort, publicacoes_vigentes(repositorio)),
    )


Servico = Annotated[ServicoPurge, Depends(get_servico_purge)]
Dpo = Annotated[Usuario, Depends(require_role("dpo"))]

router = APIRouter(route_class=RotaAdmin, tags=["admin"])


@router.post("/admin/purge")
async def purgar(
    tenant: Tenant,
    servico: Servico,
    user: Dpo,
    aplicar: Annotated[
        bool,
        Query(description="false (default) = dry-run; true = APAGA de verdade (irreversível)."),
    ] = False,
) -> dict[str, Any]:
    """Purge §10.4 do tenant. Default é dry-run — `?aplicar=true` destrói.

    Resposta: `{aplicado, retencao_dias, policy_versao, corte,
    removidos:{telemetry_event, dc_segment_cache}, total}`. `policy_versao` carimba
    QUAL régua valeu — a política publicada governa de verdade (achado 8 do UAT #5).
    """
    return servico.purgar(tenant, aplicar=aplicar, actor=user.email)
