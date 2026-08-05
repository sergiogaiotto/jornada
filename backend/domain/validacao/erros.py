"""Erros do domínio validação — traduzidos para HTTP na camada de API (§8-M4).

`CampoForaDoBriefing` herda de classe já mapeada (NaoEncontrado→404). `GoBloqueado`
(409, A1) carrega as listas para o corpo problem+json: pendências bloqueantes abertas
E campos não decididos — traduzido por `api/v1/validacao.py::RotaValidacao`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain.campanha.erros import ErroDominio, NaoEncontrado

if TYPE_CHECKING:
    from domain.campanha.modelos import Pendencia


class CampoForaDoBriefing(NaoEncontrado):
    """Validação/pendência/thread ancorada em campo inexistente no briefing (404)."""


class GoBloqueado(ErroDominio):
    """§8-M4-A1: GO com campo não decidido ou pendência bloqueante → 409 listando-as."""

    def __init__(
        self, motivo: str, campos_nao_decididos: list[str], pendencias: list[Pendencia]
    ) -> None:
        super().__init__(motivo)
        self.campos_nao_decididos = campos_nao_decididos
        self.pendencias = pendencias
