"""Routers /api/v1 — um router por módulo do §8; nomes = tags OpenAPI.

M0 não define endpoints de negócio; os routers dos módulos M1+ são incluídos aqui.
"""

from fastapi import APIRouter

api_router = APIRouter()

# M1+: api_router.include_router(os_router, prefix="/os", tags=["os"])  etc. (§8)
