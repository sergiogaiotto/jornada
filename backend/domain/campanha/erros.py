"""Erros do domínio campanha — traduzidos para HTTP problem+json na camada de API (§8).

Mapa (api/v1/os_governanca.py): NaoEncontrado→404 · AcaoNaoPermitida→403 ·
JustificativaObrigatoria→422 · TransicaoIlegal/AvancoBloqueadoPorPendencia/
CodigoDuplicado/EstadoInvalido→409.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.campanha.modelos import Pendencia


class ErroDominio(Exception):
    """Base dos erros de domínio; `motivo` é a mensagem legível do problem+json."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


class NaoEncontrado(ErroDominio):
    """Entidade inexistente no tenant do request."""


class CodigoDuplicado(ErroDominio):
    """`os.codigo` é unique (§4.1)."""


class TransicaoIlegal(ErroDominio):
    """Fase destino fora da única transição legal (ciclo linear §1.1/§4.1)."""


class AvancoBloqueadoPorPendencia(ErroDominio):
    """Portão de pendências (§8-M1-A1): pendência aberta+bloqueante trava o avanço."""

    def __init__(self, motivo: str, pendencias: list[Pendencia]) -> None:
        super().__init__(motivo)
        self.pendencias = pendencias


class EstadoInvalido(ErroDominio):
    """Operação incompatível com o estado atual (pendência não-aberta, clock não-correndo...)."""


class JustificativaObrigatoria(ErroDominio):
    """Aceite de pendência sem justificativa (§8-M1-A2)."""


class AcaoNaoPermitida(ErroDominio):
    """Ação restrita ao accountable da pendência (§8-M1-A2; segregação §10.5)."""
