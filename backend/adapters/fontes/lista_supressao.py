"""Adapter de FIXTURES da ListaSupressaoPort — 7 listas com contagens (§11.4).

Lê `mocks/seeds/lista_supressao.json`; nenhuma rede. As `amostras` são contato_hash
sha256 SINTÉTICOS (nunca PII — §10.2). O adapter Postgres real (tabela
`lista_supressao` §4.1) substitui este sem tocar domínio/serviço (hexagonal §2.1).
"""

import json
from pathlib import Path
from typing import Any

from domain.audiencia.modelos import SETE_LISTAS

FIXTURE_PADRAO = Path(__file__).resolve().parents[3] / "mocks" / "seeds" / "lista_supressao.json"


class SupressaoFixtures:
    """Implementa ListaSupressaoPort sobre o JSON de fixtures (lazy, cache em set)."""

    def __init__(self, caminho: Path = FIXTURE_PADRAO) -> None:
        self._caminho = caminho
        self._dados: dict[str, Any] | None = None
        self._amostras: dict[str, frozenset[str]] | None = None

    def _carregar(self) -> dict[str, Any]:
        if self._dados is None:
            self._dados = json.loads(self._caminho.read_text(encoding="utf-8"))
        return self._dados

    def _sets(self) -> dict[str, frozenset[str]]:
        if self._amostras is None:
            listas = self._carregar().get("listas", {})
            self._amostras = {
                lista: frozenset(listas.get(lista, {}).get("amostras", [])) for lista in SETE_LISTAS
            }
        return self._amostras

    def listas_do_contato(self, tenant_id: str, contato_hash: str) -> list[str]:
        """Listas que contêm o hash, na ordem de precedência (§4.1); [] = limpo.
        A fixture é do tenant demo — tenant divergente não encontra nada."""
        if tenant_id != self._carregar().get("tenant_id", tenant_id):
            return []
        return [lista for lista, amostras in self._sets().items() if contato_hash in amostras]

    def contagens(self) -> dict[str, int]:
        """{lista: contagem} do seed (§11.4) — insumo de telas/relatórios."""
        listas = self._carregar().get("listas", {})
        return {lista: int(listas.get(lista, {}).get("contagem", 0)) for lista in SETE_LISTAS}
