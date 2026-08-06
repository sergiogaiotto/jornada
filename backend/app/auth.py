"""Auth dev (Bearer estático) + RBAC `require_role` — SDD §8 (convenções) e §8-M0.

Dev: um token estático por usuário seed ("dev-<papel>"), papéis:
solicitante | analista | lider | aprovador | dpo | admin.
Portal do Solicitante (§8-M3): token de portal ("portal via link com token, sem login
pleno") — dev usa o token estático `portal-dev`; prod trocará por link mágico assinado
com APP_SECRET sem mudar as assinaturas das dependências.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

PAPEIS: tuple[str, ...] = ("solicitante", "analista", "lider", "aprovador", "dpo", "admin")


@dataclass(frozen=True)
class Usuario:
    """Espelho mínimo da tabela `usuario` (§4.1) para o contexto de request."""

    id: uuid.UUID
    tenant_id: str
    nome: str
    email: str
    papeis: tuple[str, ...]


def _dev_user(papel: str) -> Usuario:
    return Usuario(
        id=uuid.uuid5(uuid.NAMESPACE_URL, f"jornada/dev/{papel}"),
        tenant_id="torre-movel",
        nome=f"Dev {papel.capitalize()}",
        email=f"{papel}@dev.jornada.local",
        papeis=(papel,),
    )


# Tokens estáticos de dev (usuários seed) — ex.: `Authorization: Bearer dev-admin`
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

_bearer = HTTPBearer(auto_error=False)


def usuario_do_authorization(authorization: str | None) -> Usuario | None:
    """Portador do header `Authorization` (login pleno OU portal) — SEM levantar 401.

    Serve o middleware de tenant (`app/main.py`, achado 5/UAT5): ele só precisa saber
    QUAL é o escopo real do portador para conferir o `X-Tenant` anunciado; quem decide
    acesso continua sendo a dependência da rota (`get_current_user`/`get_portador`/
    `require_role`). Credencial ausente, de esquema errado ou desconhecida → `None`
    (a rota responde 401 — o middleware não vira um oráculo de tokens válidos).
    """
    if not authorization:
        return None
    esquema, _, token = authorization.partition(" ")
    if esquema.lower() != "bearer":
        return None
    token = token.strip()
    return DEV_TOKENS.get(token) or PORTAL_TOKENS.get(token)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Usuario:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or credentials.credentials not in DEV_TOKENS
    ):
        raise HTTPException(
            status_code=401,
            detail="Credencial Bearer ausente ou inválida.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return DEV_TOKENS[credentials.credentials]


async def get_portador(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Usuario:
    """Portador do pedido (§8-M3): token de PORTAL ou credencial plena de dev.

    O token de portal NÃO passa em `get_current_user`/`require_role` — vale apenas nas
    rotas de intake que declaram esta dependência (portal sem login pleno).
    """
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
        if token in PORTAL_TOKENS:
            return PORTAL_TOKENS[token]
        if token in DEV_TOKENS:
            return DEV_TOKENS[token]
    raise HTTPException(
        status_code=401,
        detail="Credencial Bearer ausente ou inválida (token de portal ou login pleno).",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(*papeis: str) -> Callable[..., Awaitable[Usuario]]:
    """RBAC — uso: `user: Usuario = Depends(require_role("analista", "lider"))`.

    `admin` sempre passa. Papel fora do request → 403.
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
