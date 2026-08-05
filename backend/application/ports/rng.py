"""RngPort — RNG atrás de porta (§2.1: "relógio e RNG ficam atrás de portas
(RNG/clock injetáveis → simulador reprodutível por seed)").

O port é uma FÁBRICA: `gerador(seed)` devolve uma sequência determinística
(`GeradorAleatorio`, Protocol no domínio) — cada run de simulação cria a sua com a
seed do request (§6: "seed fixa por run"). Adapters: `adapters/aleatorio.py`
(numpy vetorizado quando instalado, stdlib puro senão — §6 NFR).
"""

from typing import Protocol

from domain.simulacao.tipos import GeradorAleatorio


class RngPort(Protocol):
    def gerador(self, seed: int) -> GeradorAleatorio:
        """Nova sequência determinística a partir da seed (mesma seed ⇒ mesma série)."""
        ...
