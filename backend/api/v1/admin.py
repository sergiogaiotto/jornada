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
linha. Quem INSTALA a linha é `deploy/deploy.sh`; quem a executa é
`scripts/purge_retencao.sh` (F04 — antes disso o cron existia só como comentário).

RBAC: `dpo` (admin sempre passa, §8-M0) — é a função que responde pelo titular na LGPD.
**Mais a credencial de MÁQUINA** (`JORNADA_PURGE_TOKEN`, ver `ator_do_purge`): em
`APP_ENV=prod` não existe Bearer nenhum (`app/config.py::_prod_proibe_tokens_dev`) e a
sessão é cookie de pessoa — sem esta porta o cron simplesmente não teria como
autenticar em produção, que é onde o purge precisa rodar.
"""

import os
import secrets
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from adapters.publicacoes import publicacoes_vigentes
from adapters.relogio import RelogioSistema
from api.v1.os_governanca import Tenant, get_repositorio_os
from app.auth import get_current_user, require_role
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

# ------------------------------------------------- Credencial de MÁQUINA (F04, §10.4)
# Variável de ambiente do servidor (`.env` da VPS, 0600, gerada pelo deploy com
# `openssl rand -hex 32`). NUNCA no repositório, nunca no CI — o repo só conhece o NOME.
VAR_TOKEN_SERVICO = "JORNADA_PURGE_TOKEN"
# 32 caracteres é o piso: abaixo disso o token é tratado como AUSENTE (fail-closed). É
# deliberado não haver "token fraco aceito com aviso no log" — aviso em log é
# exatamente o modo de falha silenciosa que esta frente veio consertar; token curto
# devolve 401 e o script do cron falha alto, na cara do operador.
TAMANHO_MINIMO_TOKEN = 32
# Ator gravado no `domain_event` da destruição (§2.3): a auditoria tem de distinguir
# "o DPO apagou" de "o cron apagou". Não é e-mail de ninguém — de propósito.
ATOR_SERVICO = "maquina:purge-cron"

_bearer = HTTPBearer(auto_error=False)
_exige_dpo = require_role("dpo")


def _token_de_servico() -> str | None:
    """Token de máquina configurado neste processo, ou `None` (porta fechada).

    Lido de `os.environ` a cada chamada — sem cache — porque a ausência da variável é
    a configuração PADRÃO e precisa continuar sendo o caminho barato: sem
    `JORNADA_PURGE_TOKEN` no ambiente esta função devolve `None` e a rota volta a ser
    exatamente o que era antes do F04 (só `dpo`/`admin` humano).
    """
    bruto = os.environ.get(VAR_TOKEN_SERVICO, "").strip()
    return bruto if len(bruto) >= TAMANHO_MINIMO_TOKEN else None


async def ator_do_purge(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> str:
    """Quem está mandando purgar: um `dpo`/`admin` humano OU a máquina do cron.

    Por que a credencial de máquina mora AQUI e não em `app/auth.py`: um Bearer estático
    de vida longa com poder destrutivo é exatamente o que o UAT #5 condenou nos
    `dev-<papel>`. A diferença é o escopo — este token vale numa rota só, e ampliá-lo
    para o resto da API exigiria uma edição visível em cada rota. Um portador novo em
    `get_current_user` valeria, calado, em toda rota autenticada do §8.

    Alternativas descartadas (registrar para o próximo que reabrir isto):
    · **conta de serviço com senha no `.env`** (login → cookie → purge): não muda uma
      linha do backend, mas troca um token de UMA rota por uma SESSÃO PLENA, esbarra no
      `senha_expirada` do bootstrap (403 no primeiro uso) e no bloqueio por tentativas —
      um cron pode se auto-trancar por 15 min e o purge do dia não roda;
    · **liberar a rota na rede interna do compose** (sem auth, só `api:8000`): a api não
      publica porta, mas quem alcança a rede alcança a rota — "topologia" não é
      autenticação, e um mock comprometido purgaria a base;
    · **scheduler na aplicação** (sem HTTP, sem credencial): rejeitado no CHANGELOG e
      mantido rejeitado — ver o cabeçalho deste módulo.

    Ordem: token de máquina primeiro (comparado em tempo constante), e só depois o
    caminho humano — que continua sendo `get_current_user` + `require_role("dpo")`
    INTACTOS, com os mesmos 401/403 e as mesmas mensagens de sempre.

    A comparação é em BYTES (`.encode`) e não em `str`: `compare_digest` com strings
    exige ASCII puro e levanta `TypeError` diante de qualquer caractere fora dele. Como
    o header chega decodificado em latin-1, um `Authorization: Bearer café` bastava para
    trocar o 401 por um 500 numa rota destrutiva — erro não autenticado, e ainda um
    oráculo de "este host TEM token de máquina configurado" (401 vs 500). Em bytes a
    função nunca levanta: credencial errada é 401, ponto.
    """
    token = _token_de_servico()
    apresentado = (
        credentials.credentials
        if credentials is not None and credentials.scheme.lower() == "bearer"
        else ""
    )
    if (
        token is not None
        and apresentado
        and secrets.compare_digest(apresentado.encode("utf-8"), token.encode("utf-8"))
    ):
        return ATOR_SERVICO
    usuario = await get_current_user(request, credentials)
    return (await _exige_dpo(user=usuario)).email


Ator = Annotated[str, Depends(ator_do_purge)]

router = APIRouter(route_class=RotaAdmin, tags=["admin"])


@router.post("/admin/purge")
async def purgar(
    tenant: Tenant,
    servico: Servico,
    ator: Ator,
    aplicar: Annotated[
        bool,
        Query(description="false (default) = dry-run; true = APAGA de verdade (irreversível)."),
    ] = False,
) -> dict[str, Any]:
    """Purge §10.4 do tenant. Default é dry-run — `?aplicar=true` destrói.

    Resposta: `{aplicado, retencao_dias, policy_versao, corte,
    removidos:{telemetry_event, dc_segment_cache}, total}`. `policy_versao` carimba
    QUAL régua valeu — a política publicada governa de verdade (achado 8 do UAT #5).
    O `ator` (e-mail do DPO ou `maquina:purge-cron`) vai para o `domain_event`.
    """
    return servico.purgar(tenant, aplicar=aplicar, actor=ator)
