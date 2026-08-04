"""Auth dev (Bearer estático) + RBAC `require_role` — SDD §8 (convenções) e §8-M0.

Dev: um token estático por usuário seed ("dev-<papel>"), papéis:
solicitante | analista | lider | aprovador | dpo | admin.
Prod trocará por JWT (APP_SECRET) sem mudar as assinaturas das dependências.
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

_bearer = HTTPBearer(auto_error=False)


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
