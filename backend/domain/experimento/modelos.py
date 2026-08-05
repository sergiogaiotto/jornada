"""Entidades do contexto experimento — espelham 1:1 a tabela `experimento` §4.1.

No M7 a jornada só precisa SABER se há experimento pré-registrado e TRAVADO para a OS
(validação §5.3: holdout obrigatório; `reentrada != nao` quebra o experimento — A3).
O pré-registro pleno (`POST /experimentos`, poder/MDE) chega com o M8.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ESTADOS_EXPERIMENTO: tuple[str, ...] = ("pre_registrado", "em_apuracao", "apurado")


@dataclass
class Experimento:
    """Tabela `experimento` §4.1 — pré-registro do teste (holdout/poder/janela)."""

    id: uuid.UUID
    os_id: uuid.UUID
    holdout_pct: float
    n_minimo: int
    mde_pp: float
    janela_dias: int
    metricas: dict[str, Any] = field(default_factory=dict)
    travado_em: datetime | None = None
    estado: str = "pre_registrado"  # ESTADOS_EXPERIMENTO
    resultado: dict[str, Any] | None = None


def experimento_travado(experimento: Experimento | None) -> bool:
    """True ⇔ experimento pré-registrado E travado (`travado_em` preenchido) — o
    contrato que a validação §5.3 do JGC protege (holdout presente, reentrada=nao)."""
    return (
        experimento is not None
        and experimento.estado == "pre_registrado"
        and experimento.travado_em is not None
    )
