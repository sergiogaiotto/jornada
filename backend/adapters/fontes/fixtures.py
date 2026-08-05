"""Adapter de fonte por FIXTURES — evidência simulada da validação campo-a-campo (§8-M4).

Lê `mocks/seeds/fontes_validacao.json` (§11: mocks e seeds obrigatórios para dev/CI);
nenhuma rede. Frescor é relativo (`atualizado_ha_horas`) para manter as checagens
determinísticas independentemente do relógio (Hybris D-1 = 24h — §8-M5-A4).
Conectores reais (Data Cloud/Hybris) substituem este adapter no M5 sem tocar o domínio.
"""

import json
from pathlib import Path
from typing import Any

FIXTURE_PADRAO = Path(__file__).resolve().parents[3] / "mocks" / "seeds" / "fontes_validacao.json"


class FonteFixtures:
    """Implementa FonteValidacaoPort sobre o JSON de fixtures (lazy, cache em memória)."""

    def __init__(self, caminho: Path = FIXTURE_PADRAO) -> None:
        self._caminho = caminho
        self._fontes: dict[str, dict[str, Any]] | None = None

    def _carregar(self) -> dict[str, dict[str, Any]]:
        if self._fontes is None:
            dados = json.loads(self._caminho.read_text(encoding="utf-8"))
            self._fontes = dict(dados.get("fontes", {}))
        return self._fontes

    def consultar(self, campo: str) -> dict[str, Any] | None:
        fonte = self._carregar().get(campo)
        return dict(fonte) if fonte is not None else None
