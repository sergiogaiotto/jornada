"""Erros do contexto criativo — herdam a base do M1 para reusar o mapa RFC-7807.

Mapa (api/v1/criativo.py): CriativoInvalido/SaidaDoCriativoInvalida→422 (tratados no
route_class, `problemas` no corpo) · CelulaInexistente herda NaoEncontrado→404 ·
AprovacaoRequerHumano herda AcaoNaoPermitida→403 (mapa do M1).
"""

from __future__ import annotations

from domain.campanha.erros import AcaoNaoPermitida, ErroDominio, NaoEncontrado


class CriativoInvalido(ErroDominio):
    """Veredito dos validadores DETERMINÍSTICOS (§8-M6): SMS>160 (A1), template
    WhatsApp sem status aprovado, termo proibido de linguagem. Compliance é código,
    nunca LLM (§1.1.3) — o LLM apenas ACRESCENTA warnings não bloqueantes.

    Carrega `problemas` para o corpo do problem+json (422).
    """

    def __init__(self, motivo: str, problemas: list[str]) -> None:
        super().__init__(motivo)
        self.problemas = problemas


class SaidaDoCriativoInvalida(ErroDominio):
    """Saída do LLM sem matriz utilizável (JSON malformado ou nenhuma célula válida) —
    guarda-corpo determinístico dos agentes do T6 (§1.3.5): nada é inventado."""


class CelulaInexistente(NaoEncontrado):
    """Canal×variante fora da matriz do criativo."""


class AprovacaoRequerHumano(AcaoNaoPermitida):
    """§8-M6-A3: nenhuma célula vai a `aprovado` via agente — só usuário analista+."""
