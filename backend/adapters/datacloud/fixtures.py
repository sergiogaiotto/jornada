"""Adapter de FIXTURES do DataCloudPort — dev/teste, nenhuma rede (§1.3.5/§11.2).

Lê `mocks/seeds/datacloud_segmentos.json` (4 segmentos), o MESMO arquivo servido pelo
mock-datacloud (compose) — uma única fonte de fixtures. Frescor relativo
(`republicado_ha_horas`/`atualizado_ha_horas`) mantém as contagens determinísticas.
"""

import json
from pathlib import Path
from typing import Any

FIXTURE_PADRAO = (
    Path(__file__).resolve().parents[3] / "mocks" / "seeds" / "datacloud_segmentos.json"
)


class DataCloudFixtures:
    """Implementa DataCloudPort sobre o JSON de fixtures (lazy, cache em memória)."""

    def __init__(self, caminho: Path = FIXTURE_PADRAO) -> None:
        self._caminho = caminho
        self._segmentos: list[dict[str, Any]] | None = None

    def _carregar(self) -> list[dict[str, Any]]:
        if self._segmentos is None:
            dados = json.loads(self._caminho.read_text(encoding="utf-8"))
            self._segmentos = list(dados.get("segmentos", []))
        return self._segmentos

    def segmentos(self) -> list[dict[str, Any]]:
        return [
            {chave: valor for chave, valor in segmento.items() if chave != "relatorio"}
            for segmento in self._carregar()
        ]

    def segmento(self, segmento_id: str) -> dict[str, Any] | None:
        for segmento in self._carregar():
            if segmento.get("id") == segmento_id:
                return {chave: valor for chave, valor in segmento.items() if chave != "relatorio"}
        return None

    def relatorio(self, segmento_id: str) -> dict[str, Any] | None:
        for segmento in self._carregar():
            if segmento.get("id") == segmento_id:
                relatorio = segmento.get("relatorio")
                return dict(relatorio) if relatorio is not None else None
        return None
