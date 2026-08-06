"""Identidade + RBAC `require_role` — SDD §8-M0 e emenda G01.

Antes desta emenda a autenticação inteira eram SEIS STRINGS PUBLICADAS NO REPOSITÓRIO
(`dev-admin`, `portal-dev`, ...). O RBAC (`require_role`) já estava certo e continua
intocado: o que faltava era IDENTIDADE por trás dele. Agora existem três portadores
possíveis, resolvidos nesta ordem por `get_current_user`:

1. **Sessão** — cookie httpOnly com um id OPACO, conferido contra a tabela `sessao`
   (revogável: logout, desativação, reset de senha matam o cookie no request seguinte).
   É a credencial de verdade das pessoas.
2. **Bearer `dev-<papel>`** — os tokens estáticos, aceitos SÓ com `APP_ENV=dev` (ou
   opt-in explícito fora de prod). Em prod não existem, e a config nem carrega se
   alguém tentar ligá-los (`config.py::_prod_proibe_tokens_dev`) — achado do UAT #5.
3. **Bearer `portal-dev`** — token de portal (§8-M3), mesma regra de ambiente, e só
   vale nas rotas que declaram `get_portador`.

Duas guardas moram aqui porque `get_current_user` é o ÚNICO ponto por onde toda rota
autenticada passa (`require_role` depende dele):

· **Coerência de tenant do portador de sessão.** O middleware de `app/main.py` confere
  o `X-Tenant` anunciado contra o portador BEARER (achado 5/UAT5), mas ele lê só o
  header `Authorization` — para um usuário de cookie o portador é `None` e o header
  voltaria a ser fonte da verdade. A conferência para sessões é feita aqui, e o
  `request.state.tenant_id` é reescrito com o tenant da CONTA.
· **Senha expirada.** Ver `_barrar_se_senha_expirada`.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from application.ports.repositorio_identidade import RepositorioIdentidade
from application.services.identidade_service import ServicoIdentidade
from domain.identidade.modelos import PAPEIS, ContaUsuario

__all__ = [
    "DEV_TOKENS",
    "PAPEIS",
    "PORTAL_TOKENS",
    "ROTAS_SEM_SENHA_VALIDA",
    "Usuario",
    "get_current_user",
    "get_portador",
    "nome_cookie_sessao",
    "require_role",
    "servico_identidade",
    "tokens_dev_ativos",
    "usuario_do_authorization",
]


@dataclass(frozen=True)
class Usuario:
    """Espelho IMUTÁVEL do portador dentro de um request (§4.1 `usuario`).

    Não é o agregado persistido (`domain.identidade.modelos.ContaUsuario`) — este aqui
    não tem, e nunca deve ter, `senha_hash`: é o objeto que circula por rotas, serviços
    e logs. `senha_expirada` viaja junto porque o guard de navegação depende dele.
    """

    id: uuid.UUID
    tenant_id: str
    nome: str
    email: str
    papeis: tuple[str, ...]
    senha_expirada: bool = False


def _dev_user(papel: str) -> Usuario:
    return Usuario(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"jornada/dev/{papel}"),
        tenant_id="torre-movel",
        nome=f"Dev {papel.capitalize()}",
        email=f"{papel}@dev.jornada.local",
        papeis=(papel,),
    )


# Tokens estáticos de dev (usuários seed) — ex.: `Authorization: Bearer dev-admin`.
# NÃO são credenciais: são fixtures. Só existem com `tokens_dev_ativos()` verdadeiro.
DEV_TOKENS: dict[str, Usuario] = {f"dev-{papel}": _dev_user(papel) for papel in PAPEIS}

# Token de PORTAL (§8-M3): acesso do solicitante via link, sem login pleno — só intake.
PORTAL_TOKENS: dict[str, Usuario] = {
    "portal-dev": Usuario(
        id=uuid.uuid5(uuid.NAMESPACE_URL, "jornada/portal/solicitante"),
        tenant_id="torre-movel",
        nome="Solicitante (Portal)",
        email="portal@dev.jornada.local",
        papeis=("solicitante",),
    )
}

# Rotas liberadas para quem está com a senha expirada (ver `_barrar_se_senha_expirada`).
ROTAS_SEM_SENHA_VALIDA: tuple[str, ...] = (
    "/api/v1/auth/eu",
    "/api/v1/auth/trocar-senha",
    "/api/v1/auth/logout",
)

# Código que a SPA reconhece para redirecionar à tela de troca (ver o guard).
CABECALHO_CODIGO_ERRO = "X-Erro-Codigo"
CODIGO_SENHA_EXPIRADA = "senha_expirada"

_bearer = HTTPBearer(auto_error=False)


def tokens_dev_ativos() -> bool:
    """`dev-<papel>`/`portal-dev` valem neste processo?

    `APP_ENV=dev` sim (é o ambiente para o qual foram feitos). Fora de dev, só com
    `PERMITIR_TOKENS_DEV=true` — e em prod nem isso: a config recusa a combinação no
    startup (§10.3), então aqui não há caminho para `True` com `app_env='prod'`.
    """
    settings = get_settings()
    return settings.app_env == "dev" or settings.permitir_tokens_dev


def nome_cookie_sessao() -> str:
    return get_settings().session_cookie_nome


def servico_identidade(request: Request) -> ServicoIdentidade:
    """Serviço de identidade sobre a MESMA instância de repositório do app (§2.1).

    Import tardio de `RepositorioOsMemoria`/`RelogioSistema` para não amarrar o módulo
    de auth aos adapters em tempo de import (app/auth é importado por app/main).
    """
    from adapters.persistence.memoria import RepositorioOsMemoria
    from adapters.relogio import RelogioSistema

    repositorio = getattr(request.app.state, "repositorio_os", None)
    if repositorio is None:
        repositorio = RepositorioOsMemoria()
        request.app.state.repositorio_os = repositorio
    # Relógio atrás de porta (§2.1): os testes fixam `app.state.relogio` para provar
    # expiração de sessão e desbloqueio SEM `sleep`.
    relogio = getattr(request.app.state, "relogio", None) or RelogioSistema()
    settings = get_settings()
    return ServicoIdentidade(
        repositorio,  # tipagem estrutural §2.1: a instância implementa todas as portas
        relogio,
        ttl_horas=settings.session_ttl_horas,
        max_tentativas=settings.login_max_tentativas,
        bloqueio_minutos=settings.login_bloqueio_minutos,
    )


def repositorio_identidade(request: Request) -> RepositorioIdentidade:
    """Só para quem precisa do repositório cru (bootstrap do root)."""
    from adapters.persistence.memoria import RepositorioOsMemoria

    repositorio = getattr(request.app.state, "repositorio_os", None)
    if repositorio is None:
        repositorio = RepositorioOsMemoria()
        request.app.state.repositorio_os = repositorio
    return repositorio  # tipagem estrutural §2.1 (implementa a porta sem herdar dela)


def usuario_do_request(conta: ContaUsuario) -> Usuario:
    """`ContaUsuario` (agregado, tem segredo) → `Usuario` (portador, não tem)."""
    return Usuario(
        id=conta.id,
        tenant_id=conta.tenant_id,
        nome=conta.nome,
        email=conta.email,
        papeis=tuple(conta.papeis),
        senha_expirada=conta.senha_expirada,
    )


def usuario_do_authorization(authorization: str | None) -> Usuario | None:
    """Portador do header `Authorization` (login pleno OU portal) — SEM levantar 401.

    Serve o middleware de tenant (`app/main.py`, achado 5/UAT5): ele só precisa saber
    QUAL é o escopo real do portador para conferir o `X-Tenant` anunciado; quem decide
    acesso continua sendo a dependência da rota (`get_current_user`/`get_portador`/
    `require_role`). Credencial ausente, de esquema errado ou desconhecida → `None`
    (a rota responde 401 — o middleware não vira um oráculo de tokens válidos).

    Portador de SESSÃO (cookie) devolve `None` aqui de propósito: esta função só recebe
    o header e não tem como abrir a tabela `sessao`. A conferência de tenant desse caso
    é feita em `get_current_user`, que tem o request inteiro.
    """
    if not authorization or not tokens_dev_ativos():
        return None
    esquema, _, token = authorization.partition(" ")
    if esquema.lower() != "bearer":
        return None
    token = token.strip()
    return DEV_TOKENS.get(token) or PORTAL_TOKENS.get(token)


def _erro_401() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Credencial ausente ou inválida (sessão expirada, revogada ou token desconhecido).",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _casar_tenant(request: Request, usuario: Usuario) -> Usuario:
    """O tenant efetivo do request é o da CONTA — o header é asserção, nunca a fonte.

    Regra idêntica à do middleware para portadores Bearer (achado 5/UAT5), aplicada
    aqui para os de sessão: divergiu do `X-Tenant` anunciado, 403 e nada chega à rota.
    """
    anunciado = getattr(request.state, "tenant_id", None)
    if anunciado is not None and anunciado != usuario.tenant_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Header X-Tenant diverge do escopo da credencial "
                "(o tenant vem do portador autenticado — SDD §8)."
            ),
        )
    request.state.tenant_id = usuario.tenant_id
    return usuario


def _barrar_se_senha_expirada(request: Request, usuario: Usuario) -> Usuario:
    """Com `senha_expirada=True` a conta AUTENTICA mas não NAVEGA (§8-M0, emenda G01).

    Por que o guard mora aqui, e não numa dependência por rota nem num middleware:

    · **Dependência por rota** exigiria editar todas as ~20 rotas do §8 e — pior — o
      esquecimento seria SILENCIOSO: a rota nova de amanhã nasceria sem o guard e
      ninguém notaria. Guard opcional não é guard.
    · **Middleware** não sabe quem é o portador sem reimplementar a resolução de
      sessão (o middleware de tenant já teve de importar `usuario_do_authorization`
      exatamente por isso, e é a parte mais frágil do `main.py`).
    · **`get_current_user`** é o funil por onde TODA rota autenticada passa, porque
      `require_role` depende dele. O guard fica fail-CLOSED por construção: a única
      forma de escapar dele é a rota não exigir autenticação nenhuma — e isso é uma
      decisão visível na assinatura, não um esquecimento.

    A senha provisória vale para um acesso: entrar, ver quem você é e trocar. `403` (e
    não `401`) porque a credencial É válida — o que falta é uma senha própria.
    """
    if not usuario.senha_expirada:
        return usuario
    if request.url.path in ROTAS_SEM_SENHA_VALIDA:
        return usuario
    raise HTTPException(
        status_code=403,
        detail=(
            "Senha provisória: troque a senha antes de usar a plataforma "
            "(POST /api/v1/auth/trocar-senha)."
        ),
        # A SPA já descobre o estado por `GET /api/v1/auth/eu` (`senha_expirada`); este
        # cabeçalho é o sinal legível por máquina para uma SPA em cache que tentou uma
        # rota comum antes de perguntar.
        headers={CABECALHO_CODIGO_ERRO: CODIGO_SENHA_EXPIRADA},
    )


def _portador_de_sessao(request: Request) -> Usuario | None:
    """Cookie → conta viva, ou `None` (sem sessão, expirada, revogada ou desativada)."""
    token = request.cookies.get(nome_cookie_sessao())
    if not token:
        return None
    conta = servico_identidade(request).resolver_sessao(token)
    return usuario_do_request(conta) if conta is not None else None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Usuario:
    """Portador autenticado da rota: SESSÃO (cookie) OU Bearer de dev."""
    usuario = _portador_de_sessao(request)
    if usuario is None:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not tokens_dev_ativos()
            or credentials.credentials not in DEV_TOKENS
        ):
            raise _erro_401()
        usuario = DEV_TOKENS[credentials.credentials]
    return _barrar_se_senha_expirada(request, _casar_tenant(request, usuario))


async def get_portador(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Usuario:
    """Portador do pedido (§8-M3): SESSÃO, token de PORTAL ou credencial plena de dev.

    O token de portal NÃO passa em `get_current_user`/`require_role` — vale apenas nas
    rotas de intake que declaram esta dependência (portal sem login pleno). Quem está
    logado passa aqui também: uma sessão plena é no mínimo tão forte quanto o link.
    """
    usuario = _portador_de_sessao(request)
    if usuario is None and credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
        if tokens_dev_ativos():
            usuario = PORTAL_TOKENS.get(token) or DEV_TOKENS.get(token)
    if usuario is None:
        raise HTTPException(
            status_code=401,
            detail="Credencial ausente ou inválida (sessão, token de portal ou login pleno).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _barrar_se_senha_expirada(request, _casar_tenant(request, usuario))


def require_role(*papeis: str) -> Callable[..., Awaitable[Usuario]]:
    """RBAC — uso: `user: Usuario = Depends(require_role("analista", "lider"))`.

    `admin` sempre passa. Papel fora do request → 403. Inalterado pela emenda G01: o
    RBAC sempre esteve certo; o que mudou foi de onde vêm os papéis (agora da conta
    persistida, antes de um dicionário de tokens no código).
    """
    invalidos = set(papeis) - set(PAPEIS)
    if invalidos:
        raise ValueError(f"Papéis desconhecidos (§8-M0): {sorted(invalidos)}")

    async def _dep(user: Usuario = Depends(get_current_user)) -> Usuario:
        if "admin" in user.papeis or set(papeis) & set(user.papeis):
            return user
        raise HTTPException(
            status_code=403,
            detail=f"Ação requer papel: {', '.join(papeis)}.",
        )

    return _dep


def com_papeis(usuario: Usuario, papeis: tuple[str, ...]) -> Usuario:
    """Helper de teste/seed: cópia do portador com outros papéis (dataclass é frozen)."""
    return replace(usuario, papeis=papeis)
