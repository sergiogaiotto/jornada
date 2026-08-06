"""Rotas de IA Responsável (SDD §10.2 · F03) — tag OpenAPI `ia-responsavel`.

`GET /ia-responsavel/politicas` (histórico de versões do tenant + a vigente) ·
`GET /ia-responsavel/politica` (a VIGENTE, com o efeito de cada parâmetro em português
e o default conservador para o formulário) · `POST /ia-responsavel/politicas` (publica
uma versão nova — papel `dpo`; `admin` sempre passa, §8-M0).

## Por que `dpo` e não `lider`

Publicar política do M12 é `lider`: aquilo governa o CONTEÚDO da campanha (holdout,
alçada, frequency cap) e é decisão de operação. Isto governa o TRATAMENTO DE DADO
PESSOAL e a decisão automatizada do Art. 20 — é a função que responde pelo titular na
LGPD, o mesmo papel que já guarda o purge (`api/v1/admin.py`) e a reconstrução de
invocação. Um líder de campanha autorizando a IA a aplicar mudanças sozinha, sem o DPO,
é exatamente o desenho que a LGPD não aceita.

## Erros

`PoliticaIaInvalida` → 422 com a lista `erros` (padrão do parser §7.1, mesmo do M12):
campo fora do conjunto FECHADO devolve a mensagem que APONTA o campo, porque o DPO
edita isto por formulário e "conteúdo inválido" sem o nome do campo é um beco.
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from adapters.publicacoes import publicacoes_vigentes
from adapters.relogio import RelogioSistema
from api.v1.os_governanca import Autenticado, Tenant, _problema_de_dominio, get_repositorio_os
from app.auth import Usuario, require_role
from app.errors import problem_response
from application.ports.publicacoes_ia import PublicacoesIaPort, RepositorioPoliticaIa
from application.services.ia_responsavel_service import ServicoIaResponsavel
from domain.campanha.erros import ErroDominio
from domain.ia_responsavel import PoliticaIaInvalida

_relogio = RelogioSistema()


class RotaIaResponsavel(APIRoute):
    """`PoliticaIaInvalida` → 422 com `erros` ANTES do mapa genérico (padrão M12)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler_original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await handler_original(request)
            except PoliticaIaInvalida as exc:
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


def get_servico_ia_responsavel(request: Request) -> ServicoIaResponsavel:
    """Mesma instância de repositório do app (tipagem estrutural §2.1) + a fábrica ÚNICA
    de publicações. A política vigente NUNCA é montada aqui à mão: é a mesma
    `publicacoes_vigentes` que serve o purge e os portões, para que não exista um
    segundo jeito de descobrir qual política governa (era assim que o achado 8 vivia)."""
    repositorio = get_repositorio_os(request)
    return ServicoIaResponsavel(
        cast(RepositorioPoliticaIa, repositorio),
        _relogio,
        cast(PublicacoesIaPort, publicacoes_vigentes(repositorio)),
    )


Servico = Annotated[ServicoIaResponsavel, Depends(get_servico_ia_responsavel)]
# `dpo` é quem responde pelo titular (LGPD); `admin` passa por regra geral do §8-M0.
Dpo = Annotated[Usuario, Depends(require_role("dpo"))]

router = APIRouter(route_class=RotaIaResponsavel, tags=["ia-responsavel"])


class PoliticaIaPublicar(BaseModel):
    """Conteúdo do conjunto FECHADO §10.2 + a justificativa da mudança.

    `conteudo` é `dict` cru de propósito: quem valida é o DOMÍNIO
    (`validar_conteudo`), que acumula TODOS os erros. Um modelo Pydantic aninhado
    devolveria o primeiro erro de schema e esconderia os outros cinco — e quem preenche
    isto é uma pessoa num formulário, não um cliente de máquina.
    """

    conteudo: dict[str, Any]
    motivo: str = Field(min_length=5, max_length=500)


@router.get("/ia-responsavel/politicas")
async def listar_politicas_ia(
    tenant: Tenant, servico: Servico, _user: Autenticado
) -> dict[str, Any]:
    """Histórico versionado do tenant + a vigente. Leitura é de qualquer autenticado:
    saber sob que política de IA a plataforma opera não é privilégio de ninguém."""
    return servico.listar(tenant)


@router.get("/ia-responsavel/politica")
async def obter_politica_ia_vigente(
    tenant: Tenant, servico: Servico, _user: Autenticado
) -> dict[str, Any]:
    """A que GOVERNA agora, com `origem` (`seed` = default de fábrica, ninguém publicou;
    `policy_versao` = assinada por um humano), o efeito de cada parâmetro em português e
    o default conservador para preencher o formulário."""
    return servico.vigente(tenant)


@router.post("/ia-responsavel/politicas", status_code=201)
async def publicar_politica_ia(
    payload: PoliticaIaPublicar, tenant: Tenant, servico: Servico, user: Dpo
) -> dict[str, Any]:
    """Publica versão nova (`max+1`) — a partir da resposta desta rota, é ELA que
    governa. Campo fora do conjunto FECHADO → 422 apontando o campo."""
    return servico.publicar(
        tenant,
        conteudo=payload.conteudo,
        motivo=payload.motivo,
        autor_id=user.id,
        autor_nome=user.nome,
    )
