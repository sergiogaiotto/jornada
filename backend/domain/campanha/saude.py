"""Saúde da OS — SEMPRE derivada; nenhuma escrita (§4.1: "Saúde NUNCA é coluna").

Espelho fiel da view `os_saude` (§4.1): em_risco se (pendência aberta+bloqueante)
OU (sla_clock correndo com agora > prazo); senão normal. Breakers/incidentes entram
na derivação nos módulos que os introduzem (M10), sem mudar este contrato.
"""

from datetime import datetime

from domain.campanha.modelos import Pendencia, SlaClock


def derivar_saude(pendencias: list[Pendencia], clocks: list[SlaClock], agora: datetime) -> str:
    """'em_risco' | 'normal' — função pura, relógio injetado."""
    pendencia_bloqueante = any(p.status == "aberta" and p.bloqueante for p in pendencias)
    sla_estourado = any(c.estado == "correndo" and agora > c.prazo for c in clocks)
    return "em_risco" if pendencia_bloqueante or sla_estourado else "normal"
