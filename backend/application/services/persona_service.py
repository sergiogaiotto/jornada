"""PersonaService (§6) — personas sintéticas amostradas de AGREGADOS do read model.

Camada fina sobre `domain/simulacao/personas.py` (código puro): entrega as coortes
agregadas ao simulador com a MESMA sequência aleatória do run (seed fixa — §6/M8-A1).
Jamais registros individuais em prompt/log (LGPD §6/§10.2) — só contagens/percentuais.
"""

from typing import Any

from domain.simulacao.personas import gerar_personas
from domain.simulacao.tipos import GeradorAleatorio


class ServicoPersona:
    def gerar(
        self,
        *,
        n: int,
        priors: dict[str, Any],
        ger: GeradorAleatorio,
        volume_abordagem: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Coortes agregadas (classes do governor + horários) determinísticas por seed."""
        return gerar_personas(n=n, priors=priors, ger=ger, volume_abordagem=volume_abordagem)
