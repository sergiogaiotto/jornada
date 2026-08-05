"""Regras puras da matriz canal×variante (§8-M6) — sem I/O.

- `obter_celula` — endereço canal×variante (CelulaInexistente → 404).
- `aprovar_celula` — SÓ usuário humano analista+ (A3): `por=None` (agente) →
  AprovacaoRequerHumano; re-aprovação → EstadoInvalido.
- `pedir_revisao` — devolve a célula ao estado `revisar` com observação.
- `editar_kv_master` — A2: TODA célula da matriz deriva do KV master; a edição marca
  todas `adaptado_revisar` (aprovações anteriores caem — precisam de novo olhar humano).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from domain.campanha.erros import EstadoInvalido
from domain.criativo.erros import AprovacaoRequerHumano, CelulaInexistente
from domain.criativo.modelos import CelulaCriativo, Criativo


def obter_celula(criativo: Criativo, canal: str, variante: str) -> CelulaCriativo:
    for celula in criativo.celulas:
        if celula.canal == canal and celula.variante == variante:
            return celula
    raise CelulaInexistente(
        f"Célula {canal}/{variante} não existe na matriz do criativo {criativo.id}."
    )


def aprovar_celula(
    criativo: Criativo,
    canal: str,
    variante: str,
    *,
    por: uuid.UUID | None,
    agora: datetime,
    observacao: str | None = None,
) -> CelulaCriativo:
    """A3: aprovação é ato HUMANO (analista+ — RBAC na rota); agente nunca aprova."""
    if por is None:
        raise AprovacaoRequerHumano(
            "Nenhuma célula vai a `aprovado` via agente — só usuário analista+ (§8-M6-A3)."
        )
    celula = obter_celula(criativo, canal, variante)
    if celula.estado == "aprovado":
        raise EstadoInvalido(f"Célula {canal}/{variante} já está aprovada.")
    celula.estado = "aprovado"
    celula.aprovada_por = por
    celula.aprovada_em = agora
    celula.observacao = observacao
    criativo.updated_at = agora
    return celula


def pedir_revisao(
    criativo: Criativo,
    canal: str,
    variante: str,
    *,
    agora: datetime,
    observacao: str | None = None,
) -> CelulaCriativo:
    """Analista devolve a célula para revisão (estado `revisar`); aprovação cai."""
    celula = obter_celula(criativo, canal, variante)
    celula.estado = "revisar"
    celula.aprovada_por = None
    celula.aprovada_em = None
    celula.observacao = observacao
    criativo.updated_at = agora
    return celula


def editar_kv_master(
    criativo: Criativo, novo_kv: dict[str, Any], *, agora: datetime
) -> list[CelulaCriativo]:
    """A2: edição do KV master marca TODAS as células derivadas `adaptado_revisar`."""
    criativo.kv_master = dict(novo_kv)
    marcadas: list[CelulaCriativo] = []
    for celula in criativo.celulas:
        celula.estado = "adaptado_revisar"
        celula.aprovada_por = None
        celula.aprovada_em = None
        marcadas.append(celula)
    criativo.updated_at = agora
    return marcadas
