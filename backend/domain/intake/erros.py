"""Erros do domínio intake — especializam a hierarquia de domain/campanha/erros.py.

Herdam de classes já mapeadas para HTTP no router (api/v1/os_governanca.py), portanto
nenhum mapa novo é necessário: ConversaoIncompleta/PedidoJaConvertido/PedidoArquivado→409
(EstadoInvalido) · CampoBriefingDesconhecido→404 (NaoEncontrado).
"""

from domain.campanha.erros import ErroDominio, EstadoInvalido, NaoEncontrado


class CampoBriefingInvalido(ErroDominio):
    """PATCH de campo do briefing com valor mal formado (J04 — janela_inicio/fim fora do
    ISO YYYY-MM-DD) → 422. Valor presente-mas-inválido enganaria o usuário: gravado e
    exibido como se governasse, com a regra do §5.3 inerte em silêncio. Melhor 422 na
    fronteira do que um limite que não vale."""


class ConversaoIncompleta(EstadoInvalido):
    """§8-M3-A2: converter exige completude=100 (409, com os faltantes no motivo)."""

    def __init__(self, motivo: str, faltantes: list[str]) -> None:
        super().__init__(motivo)
        self.faltantes = faltantes


class PedidoJaConvertido(EstadoInvalido):
    """Pedido `convertido` é terminal: nova conversão/conversa → 409."""


class PedidoArquivado(EstadoInvalido):
    """Pedido `arquivado` (soft — §8-M3 CRUD) não conversa, não edita, não converte (409)."""


class CampoBriefingDesconhecido(NaoEncontrado):
    """PATCH /os/{id}/briefing/{campo} sem valor para campo inexistente (404)."""
