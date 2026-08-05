"""ClockPort — relógio atrás de porta (§2.1: clock/RNG injetáveis)."""

from datetime import datetime
from typing import Protocol


class ClockPort(Protocol):
    def agora(self) -> datetime:
        """Instante atual timezone-aware (UTC)."""
        ...
