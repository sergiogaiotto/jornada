"""FonteValidacaoPort — consulta de fonte para a validação campo-a-campo (§8-M4).

Porta = Protocol (§2.1). Em dev/teste o adapter lê as fixtures de fonte
(mocks/seeds/fontes_validacao.json — §11); os conectores reais (Data Cloud, Hybris)
entram no M5 sem tocar domínio/serviço.
"""

from typing import Any, Protocol


class FonteValidacaoPort(Protocol):
    def consultar(self, campo: str) -> dict[str, Any] | None:
        """Dados da fonte do campo — {fonte, contagem, schema, atualizado_ha_horas,
        sla_frescor_horas} — ou None quando não há fonte configurada."""
        ...
