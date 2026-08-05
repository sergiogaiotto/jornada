"""Erros do domínio intake — especializam a hierarquia de domain/campanha/erros.py.

Herdam de classes já mapeadas para HTTP no router (api/v1/os_governanca.py), portanto
nenhum mapa novo é necessário: ConversaoIncompleta/PedidoJaConvertido→409 (EstadoInvalido)
· CampoBriefingDesconhecido→404 (NaoEncontrado).
"""

from domain.campanha.erros import EstadoInvalido, NaoEncontrado


class ConversaoIncompleta(EstadoInvalido):
    """§8-M3-A2: converter exige completude=100 (409, com os faltantes no motivo)."""

    def __init__(self, motivo: str, faltantes: list[str]) -> None:
        super().__init__(motivo)
        self.faltantes = faltantes


class PedidoJaConvertido(EstadoInvalido):
    """Pedido `convertido` é terminal: nova conversão/conversa → 409."""


class CampoBriefingDesconhecido(NaoEncontrado):
    """PATCH /os/{id}/briefing/{campo} sem valor para campo inexistente (404)."""
