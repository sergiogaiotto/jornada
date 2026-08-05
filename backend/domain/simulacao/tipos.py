"""Protocolo estrutural do gerador aleatório usado pelo motor (§6 — reprodutível).

Fica no domínio (tipagem estrutural, zero I/O) para que `motor.py`/`personas.py`
permaneçam puros; a PORTA (`RngPort`, §2.1: "relógio e RNG ficam atrás de portas")
vive em `application/ports/rng.py` e referencia este Protocol.
"""

from typing import Protocol


class GeradorAleatorio(Protocol):
    """Sequência aleatória determinística por seed (mesma seed ⇒ mesma sequência)."""

    def uniforme(self) -> float:
        """U[0,1)."""
        ...

    def normal(self, media: float, desvio: float) -> float:
        """Normal(media, desvio)."""
        ...

    def binomial(self, n: int, p: float) -> int:
        """Binomial(n, p) — inteiro em [0, n]."""
        ...
