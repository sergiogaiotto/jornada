"""Regras da Esteira de Produção ex-Hike (SDD §8-M2, tabela `etapa_workflow` §4.1).

- 7 etapas canônicas com ordem 1..7 e dependência linear (etapa N depende da N-1
  concluída — semântica da esteira ex-Hike; ver CHANGELOG-SDD.md M2).
- Checklist com subtarefas: Criativos nasce com as 4 padrão (A1); Acompanhamento
  com os checkpoints D+1/D+7/D+15.
- Estados (§4.1): pendente|em_andamento|concluida|bloqueada. Ciclo:
  pendente → em_andamento → concluida; bloqueio/desbloqueio manual à parte.
  `em_andamento` exige TODAS as dependências concluídas (A2 → 409).
"""

import uuid
from datetime import datetime
from typing import Any

from domain.esteira.erros import (
    ChecklistItemDesconhecido,
    DependenciaInsatisfeita,
    TransicaoEtapaIlegal,
)
from domain.esteira.modelos import (
    CHECKPOINTS_ACOMPANHAMENTO,
    ETAPAS,
    SUBTAREFAS_CRIATIVOS,
    EtapaWorkflow,
)

_TRANSICOES: dict[str, frozenset[str]] = {
    "pendente": frozenset({"em_andamento", "bloqueada"}),
    "em_andamento": frozenset({"concluida", "bloqueada"}),
    "bloqueada": frozenset({"pendente", "em_andamento"}),
    "concluida": frozenset(),
}


def checklist_padrao(nome: str) -> list[dict[str, Any]]:
    """Subtarefas com que a etapa nasce: Criativos = 4 padrão; Acompanhamento = D+1/7/15."""
    itens: tuple[str, ...] = ()
    if nome == "criativos":
        itens = SUBTAREFAS_CRIATIVOS
    elif nome == "acompanhamento":
        itens = CHECKPOINTS_ACOMPANHAMENTO
    return [{"item": item, "feito": False, "por": None, "em": None} for item in itens]


def dependencias_padrao(nome: str) -> list[str]:
    """Dependência linear da esteira: etapa N depende da N-1 (briefing não depende)."""
    indice = ETAPAS.index(nome)
    return [] if indice == 0 else [ETAPAS[indice - 1]]


def etapas_padrao(os_id: uuid.UUID) -> list[EtapaWorkflow]:
    """As 7 etapas canônicas com que toda OS nasce na esteira (T4a)."""
    return [
        EtapaWorkflow(
            id=uuid.uuid4(),
            os_id=os_id,
            ordem=ordem,
            nome=nome,
            responsavel=None,
            sla_dias=None,
            estado="pendente",
            checklist=checklist_padrao(nome),
            dependencias=dependencias_padrao(nome),
            hike_ref=None,
        )
        for ordem, nome in enumerate(ETAPAS, start=1)
    ]


def dependencias_insatisfeitas(etapa: EtapaWorkflow, etapas: list[EtapaWorkflow]) -> list[str]:
    """Nomes das dependências ainda não `concluida` (dependência ausente conta)."""
    por_nome = {e.nome: e for e in etapas}
    return [
        dep
        for dep in etapa.dependencias
        if dep not in por_nome or por_nome[dep].estado != "concluida"
    ]


def validar_mudanca_estado(etapa: EtapaWorkflow, destino: str, etapas: list[EtapaWorkflow]) -> None:
    """Valida a transição de estado da etapa (levanta erros 409 — ver erros.py)."""
    if destino == etapa.estado:
        return  # no-op idempotente
    if destino not in _TRANSICOES[etapa.estado]:
        raise TransicaoEtapaIlegal(
            f"Etapa {etapa.nome!r} não admite {etapa.estado!r} → {destino!r} "
            f"(ciclo §4.1: pendente → em_andamento → concluida; bloqueio à parte)."
        )
    if destino == "em_andamento":
        faltantes = dependencias_insatisfeitas(etapa, etapas)
        if faltantes:
            raise DependenciaInsatisfeita(
                f"Etapa {etapa.nome!r} não pode ir a 'em_andamento': dependência(s) "
                f"não concluída(s): {', '.join(faltantes)} (§8-M2-A2)."
            )


def marcar_item(etapa: EtapaWorkflow, item: str, feito: bool, por: str, em: datetime) -> None:
    """Marca/desmarca subtarefa do checklist gravando `{item, feito, por, em}` (§4.1)."""
    for entrada in etapa.checklist:
        if entrada.get("item") == item:
            entrada["feito"] = feito
            entrada["por"] = por if feito else None
            entrada["em"] = em.isoformat() if feito else None
            return
    raise ChecklistItemDesconhecido(
        f"Subtarefa {item!r} não existe no checklist da etapa {etapa.nome!r}."
    )
