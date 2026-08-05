"""Adapters de RNG — implementam RngPort (§2.1; §6: reprodutível por seed).

`RngNumpy` (numpy instalado): binomial/normal exatos e vetorizados em C — caminho
recomendado do NFR §6/§10.1 (10k personas < 60s). `RngPadrao` (stdlib pura): fallback
sem dependência — binomial exato para n pequeno e aproximação normal (arredondada e
truncada a [0, n]) para n grande; determinístico por seed em ambos os casos.
Nota: as duas implementações são reprodutíveis por seed, mas NÃO geram a mesma série
entre si — o aceite M8-A1 (mesma seed ⇒ mesmos P50s) vale dentro de uma instalação.
"""

import math
import random

from domain.simulacao.tipos import GeradorAleatorio

try:  # numpy é opcional (§6: "vetorizar com numpy" quando disponível)
    import numpy as _np
except ImportError:  # pragma: no cover - depende do ambiente
    _np = None


class _GeradorPadrao:
    """stdlib `random.Random(seed)` — puro, determinístico."""

    _LIMIAR_EXATO = 64  # abaixo disso, binomial exata (soma de Bernoullis)

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def uniforme(self) -> float:
        return self._rng.random()

    def normal(self, media: float, desvio: float) -> float:
        return self._rng.gauss(media, desvio)

    def binomial(self, n: int, p: float) -> int:
        if n <= 0 or p <= 0.0:
            return 0
        if p >= 1.0:
            return n
        if n <= self._LIMIAR_EXATO:
            rng = self._rng
            return sum(1 for _ in range(n) if rng.random() < p)
        media = n * p
        desvio = math.sqrt(n * p * (1.0 - p))
        return max(0, min(n, round(self._rng.gauss(media, desvio))))


class RngPadrao:
    """RngPort — fallback stdlib puro (sem numpy)."""

    def gerador(self, seed: int) -> GeradorAleatorio:
        return _GeradorPadrao(seed)


class _GeradorNumpy:  # pragma: no cover - exercido só com numpy instalado
    """`numpy.random.default_rng(seed)` — binomial exata vetorizada em C."""

    def __init__(self, seed: int) -> None:
        self._rng = _np.random.default_rng(seed)

    def uniforme(self) -> float:
        return float(self._rng.random())

    def normal(self, media: float, desvio: float) -> float:
        return float(self._rng.normal(media, desvio))

    def binomial(self, n: int, p: float) -> int:
        if n <= 0 or p <= 0.0:
            return 0
        return int(self._rng.binomial(n, min(p, 1.0)))


class RngNumpy:  # pragma: no cover - exercido só com numpy instalado
    """RngPort — caminho vetorizado (numpy presente)."""

    def gerador(self, seed: int) -> GeradorAleatorio:
        return _GeradorNumpy(seed)


def rng_disponivel() -> RngPadrao | RngNumpy:
    """Melhor implementação do ambiente: numpy quando instalado, stdlib senão (§6)."""
    return RngNumpy() if _np is not None else RngPadrao()
