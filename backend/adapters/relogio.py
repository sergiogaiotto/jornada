"""Adapter de relógio de sistema — implementa ClockPort (§2.1)."""

from datetime import UTC, datetime


class RelogioSistema:
    def agora(self) -> datetime:
        return datetime.now(UTC)
