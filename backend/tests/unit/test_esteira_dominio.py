"""Unit do domínio esteira (M2): etapas padrão, transições de estado, checklist."""

import uuid
from datetime import UTC, datetime

import pytest

from domain.esteira import workflow
from domain.esteira.erros import (
    ChecklistItemDesconhecido,
    DependenciaInsatisfeita,
    TransicaoEtapaIlegal,
)
from domain.esteira.modelos import ETAPAS, EtapaWorkflow

AGORA = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _etapas() -> list[EtapaWorkflow]:
    return workflow.etapas_padrao(uuid.uuid4())


def _por_nome(etapas: list[EtapaWorkflow], nome: str) -> EtapaWorkflow:
    return next(e for e in etapas if e.nome == nome)


def test_etapas_padrao_sao_as_7_canonicas_com_dependencia_linear() -> None:
    etapas = _etapas()
    assert [e.nome for e in etapas] == list(ETAPAS)
    assert [e.ordem for e in etapas] == list(range(1, 8))
    assert _por_nome(etapas, "briefing").dependencias == []
    assert _por_nome(etapas, "disparo").dependencias == ["configuracao"]
    assert all(e.estado == "pendente" and e.hike_ref is None for e in etapas)


def test_checklist_padrao_criativos_4_e_acompanhamento_d1_d7_d15() -> None:
    etapas = _etapas()
    criativos = _por_nome(etapas, "criativos")
    assert len(criativos.checklist) == 4
    assert [i["item"] for i in _por_nome(etapas, "acompanhamento").checklist] == [
        "Checkpoint D+1",
        "Checkpoint D+7",
        "Checkpoint D+15",
    ]
    assert _por_nome(etapas, "briefing").checklist == []  # só Criativos/Acompanhamento nascem com


def test_em_andamento_exige_dependencias_concluidas() -> None:
    etapas = _etapas()
    with pytest.raises(DependenciaInsatisfeita, match="discovery"):
        workflow.validar_mudanca_estado(_por_nome(etapas, "audiencia"), "em_andamento", etapas)
    _por_nome(etapas, "briefing").estado = "concluida"
    _por_nome(etapas, "discovery").estado = "concluida"
    workflow.validar_mudanca_estado(_por_nome(etapas, "audiencia"), "em_andamento", etapas)


def test_ciclo_de_estados_e_bloqueio() -> None:
    etapas = _etapas()
    briefing = _por_nome(etapas, "briefing")
    with pytest.raises(TransicaoEtapaIlegal):  # pendente → concluida sem iniciar
        workflow.validar_mudanca_estado(briefing, "concluida", etapas)
    workflow.validar_mudanca_estado(briefing, "em_andamento", etapas)
    briefing.estado = "em_andamento"
    workflow.validar_mudanca_estado(briefing, "bloqueada", etapas)
    briefing.estado = "bloqueada"
    workflow.validar_mudanca_estado(briefing, "pendente", etapas)  # desbloqueio manual
    briefing.estado = "concluida"
    with pytest.raises(TransicaoEtapaIlegal):  # concluída é terminal
        workflow.validar_mudanca_estado(briefing, "em_andamento", etapas)
    workflow.validar_mudanca_estado(briefing, "concluida", etapas)  # mesmo estado = no-op


def test_marcar_item_grava_por_em_e_desmarcar_limpa() -> None:
    etapas = _etapas()
    criativos = _por_nome(etapas, "criativos")
    item = criativos.checklist[0]["item"]
    workflow.marcar_item(criativos, item, True, "analista@dev.jornada.local", AGORA)
    assert criativos.checklist[0] == {
        "item": item,
        "feito": True,
        "por": "analista@dev.jornada.local",
        "em": AGORA.isoformat(),
    }
    workflow.marcar_item(criativos, item, False, "analista@dev.jornada.local", AGORA)
    assert criativos.checklist[0] == {"item": item, "feito": False, "por": None, "em": None}
    with pytest.raises(ChecklistItemDesconhecido):
        workflow.marcar_item(criativos, "não existe", True, "x", AGORA)
