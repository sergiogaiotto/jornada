"""Adapter de FIXTURE da ExtractsPort — CSV `mocks/seeds/extracts_tracking.csv`
(§8-M10 "job extracts loader"; §11 fixtures obrigatórias, nenhuma rede).

O CSV espelha o tracking extract D-1 do SFMC para a OS demo (§11.4): colunas
`os_codigo,no_jgc,canal,tipo,contato_hash,ts,grupo` — `contato_hash` sha256 SINTÉTICO
(NUNCA PII §10.2); `grupo` (tratado|holdout) vira `payload.grupo` nos eventos de
conversão (atribuição do experimento). O adapter real (download de extracts) substitui
este sem tocar domínio/serviço (hexagonal §2.1).
"""

import csv
from pathlib import Path
from typing import Any

FIXTURE_PADRAO = Path(__file__).resolve().parents[3] / "mocks" / "seeds" / "extracts_tracking.csv"


class ExtractsFixtures:
    """Implementa ExtractsPort sobre o CSV de fixtures (lazy, cache em lista)."""

    def __init__(self, caminho: Path = FIXTURE_PADRAO) -> None:
        self._caminho = caminho
        self._eventos: list[dict[str, Any]] | None = None

    def listar_eventos(self) -> list[dict[str, Any]]:
        if self._eventos is None:
            with self._caminho.open(newline="", encoding="utf-8") as arquivo:
                self._eventos = [self._normalizar(linha) for linha in csv.DictReader(arquivo)]
        return [dict(e) for e in self._eventos]  # cópia rasa — chamador não muta o cache

    @staticmethod
    def _normalizar(linha: dict[str, str]) -> dict[str, Any]:
        grupo = (linha.get("grupo") or "").strip()
        return {
            "os_codigo": linha["os_codigo"].strip(),
            "no_jgc": (linha.get("no_jgc") or "").strip() or None,
            "canal": (linha.get("canal") or "").strip() or None,
            "tipo": linha["tipo"].strip(),
            "contato_hash": (linha.get("contato_hash") or "").strip() or None,
            "ts": linha["ts"].strip(),
            "payload": {"grupo": grupo} if grupo else None,
        }
