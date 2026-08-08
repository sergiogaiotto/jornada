"""Adapter de FIXTURES do ReadModelAudienciaPort — dry-run de recontagem (§8-M5).

Lê `mocks/seeds/read_model_audiencia.json` (§11); nenhuma rede. Frescor relativo por
fonte (Hybris D-1 = 24h — §8-M5-A4). O read model real (com TTL — §2.1 camada Data)
substitui este adapter sem tocar domínio/serviço.
"""

import json
from pathlib import Path
from typing import Any

FIXTURE_PADRAO = (
    Path(__file__).resolve().parents[3] / "mocks" / "seeds" / "read_model_audiencia.json"
)


class ReadModelFixtures:
    """Implementa ReadModelAudienciaPort sobre o JSON de fixtures (lazy, cache)."""

    def __init__(self, caminho: Path = FIXTURE_PADRAO) -> None:
        self._caminho = caminho
        self._dados: dict[str, Any] | None = None

    def _carregar(self) -> dict[str, Any]:
        if self._dados is None:
            self._dados = json.loads(self._caminho.read_text(encoding="utf-8"))
        return self._dados

    def contagens_segmentacao(self, sql_publico: str) -> dict[str, Any]:
        """Dry-run determinístico: as fixtures respondem pelo bloco `estudio_sql`
        independentemente do SQL (o Guard é quem valida o SQL — §8-M5-A1).

        `derivado_do_sql: False` é a confissão exigida pela porta (§8-M5-A5): este
        adapter IGNORA o `sql_publico`. Proibido "melhorar" isto olhando o texto do
        SQL — parecer derivado sem executar é exatamente o overclaim que o campo
        veio eliminar (e o contract test tem um alçapão para quem tentar).
        """
        return {**self._carregar().get("estudio_sql", {}), "derivado_do_sql": False}
