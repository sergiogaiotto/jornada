"""Erros do contexto simulacao — herdam o mapa HTTP do M1 via `EstadoInvalido` (409):
simular exige segmento recontado; congelar/comparar exigem simulação persistida."""

from domain.campanha.erros import EstadoInvalido


class SegmentoAusente(EstadoInvalido):
    """§6: a entrada do simulador inclui segmento (waterfall/volume) — sem
    `contagem_liquida` não há volume de entrada para o ensaio (409)."""


class SimulacaoAusente(EstadoInvalido):
    """Congelar previsto/comparar cenários exige simulação persistida na versão (409)."""
