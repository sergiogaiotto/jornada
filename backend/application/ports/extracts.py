"""Porta dos data extracts de telemetria (§2.1 "adapters de fontes ... telemetria
ENS/extracts"; §8-M10 "job extracts loader").

O extract é a SEGUNDA fonte da telemetria dupla (batch D-1 do SFMC) — o loader diário
persiste `telemetry_event` com `fonte='extract'` (§4.1) e a reconciliação ENS×extract
(A3) mede a divergência entre as fontes. Dev/teste usa o adapter de fixture CSV
(adapters/fontes/extracts.py); o adapter real (tracking extracts do SFMC) entra sem
tocar domínio/serviço (hexagonal §2.1).
"""

from typing import Any, Protocol


class ExtractsPort(Protocol):
    def listar_eventos(self) -> list[dict[str, Any]]:
        """Linhas do extract normalizadas: {os_codigo, no_jgc, canal, tipo,
        contato_hash, ts (iso), payload?} — contato SEMPRE hash sha256 (§10.2)."""
        ...
