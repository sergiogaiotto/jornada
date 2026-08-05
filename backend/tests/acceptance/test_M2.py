"""Aceites do módulo M2 · Esteira de Produção ex-Hike (SDD §8-M2) — IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker (repositório em memória). Fixture obrigatória do §11.4:
mocks/seeds/hike_export.json (3 cards → 3 OSs). LLM: nenhuma rota do M2 invoca LLM;
o hub real jamais é chamado (§1.3.5).
"""

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import PROBLEM_CONTENT_TYPE
from domain.esteira.modelos import (
    CHECKPOINTS_ACOMPANHAMENTO,
    ETAPAS,
    SUBTAREFAS_CRIATIVOS,
)

TENANT = "torre-movel"
FIXTURE_HIKE = Path(__file__).resolve().parents[3] / "mocks" / "seeds" / "hike_export.json"


def _h(token: str) -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _criar_os(client: TestClient) -> dict[str, Any]:
    resposta = client.post(
        "/api/v1/os",
        json={"nome": "Upgrade Pós-Pago 5G", "tshirt": "M"},
        headers=_h("dev-analista"),
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _workflow(client: TestClient, os_id: str) -> list[dict[str, Any]]:
    resposta = client.get(f"/api/v1/os/{os_id}/workflow", headers=_h("dev-analista"))
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["os_id"] == os_id
    return corpo["etapas"]


def _etapa(etapas: list[dict[str, Any]], nome: str) -> dict[str, Any]:
    return next(e for e in etapas if e["nome"] == nome)


def test_M2_A1(client: TestClient) -> None:
    """A1: etapa Criativos criada com 4 subtarefas padrão (checklist §4.1); workflow nasce
    com as 7 etapas canônicas, ordem 1..7 e dependência linear; Acompanhamento nasce com
    os checkpoints D+1/D+7/D+15."""
    os_ = _criar_os(client)
    etapas = _workflow(client, os_["id"])

    assert [e["nome"] for e in etapas] == list(ETAPAS)
    assert [e["ordem"] for e in etapas] == list(range(1, 8))
    assert all(e["estado"] == "pendente" for e in etapas)

    criativos = _etapa(etapas, "criativos")
    assert len(criativos["checklist"]) == 4
    assert [i["item"] for i in criativos["checklist"]] == list(SUBTAREFAS_CRIATIVOS)
    assert all(i["feito"] is False and i["por"] is None for i in criativos["checklist"])

    acompanhamento = _etapa(etapas, "acompanhamento")
    assert [i["item"] for i in acompanhamento["checklist"]] == list(CHECKPOINTS_ACOMPANHAMENTO)

    # dependência linear da esteira: etapa N depende da N-1
    assert _etapa(etapas, "briefing")["dependencias"] == []
    assert _etapa(etapas, "criativos")["dependencias"] == ["audiencia"]


def test_M2_A2(client: TestClient) -> None:
    """A2: etapa com dependência insatisfeita não vai a `em_andamento` → 409 problem+json;
    satisfeita a dependência, a transição passa."""
    os_ = _criar_os(client)

    negado = client.patch(
        f"/api/v1/os/{os_['id']}/workflow",
        json={"etapa": "audiencia", "estado": "em_andamento"},
        headers=_h("dev-analista"),
    )
    assert negado.status_code == 409, negado.text
    assert negado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    corpo = negado.json()
    assert corpo["status"] == 409
    assert "discovery" in corpo["detail"]  # motivo aponta a dependência não concluída

    # e a etapa de fato não mudou de estado
    assert _etapa(_workflow(client, os_["id"]), "audiencia")["estado"] == "pendente"

    # satisfazendo a cadeia: briefing → discovery concluídas, audiencia inicia
    for nome in ("briefing", "discovery"):
        for estado in ("em_andamento", "concluida"):
            ok = client.patch(
                f"/api/v1/os/{os_['id']}/workflow",
                json={"etapa": nome, "estado": estado},
                headers=_h("dev-analista"),
            )
            assert ok.status_code == 200, ok.text
    agora_ok = client.patch(
        f"/api/v1/os/{os_['id']}/workflow",
        json={"etapa": "audiencia", "estado": "em_andamento"},
        headers=_h("dev-analista"),
    )
    assert agora_ok.status_code == 200
    assert _etapa(agora_ok.json()["etapas"], "audiencia")["estado"] == "em_andamento"


def test_M2_A3(client: TestClient, app: FastAPI) -> None:
    """A3: import da fixture mocks/seeds/hike_export.json cria 3 OSs com histórico
    preservado (checklist com por/em originais; outbox `hike.card_imported` com o
    histórico do card; `hike_ref` nas etapas; log em hike_import_log)."""
    export = json.loads(FIXTURE_HIKE.read_text(encoding="utf-8"))
    assert len(export["cards"]) == 3  # fixture do §11.4

    resposta = client.post("/api/v1/admin/hike/import", json=export, headers=_h("dev-admin"))
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["importados"] == 3 and corpo["duplicados"] == 0
    assert all(r["status"] == "ok" for r in corpo["resultados"])

    por_card = {r["card_id"]: r for r in corpo["resultados"]}
    for card in export["cards"]:
        resultado = por_card[card["card_id"]]
        os_ = client.get(f"/api/v1/os/{resultado['os_id']}", headers=_h("dev-analista")).json()
        assert os_["nome"] == card["titulo"] and os_["tshirt"] == card["tshirt"]
        assert os_["codigo"] == resultado["codigo"]

        etapas = _workflow(client, resultado["os_id"])
        assert [e["nome"] for e in etapas] == list(ETAPAS)  # sempre as 7 canônicas
        for etapa in etapas:  # hike_ref em todas as etapas importadas (§4.1)
            assert etapa["hike_ref"]["card_id"] == card["card_id"]
            assert etapa["hike_ref"]["url_arquivada"] == card["url"]
            assert etapa["hike_ref"]["importado_em"]
        # estados/checklist vieram do Hike (histórico preservado)
        for etapa_hike in card["etapas"]:
            etapa = _etapa(etapas, etapa_hike["nome"])
            assert etapa["estado"] == etapa_hike["estado"]
            for item_hike in etapa_hike.get("checklist", []):
                item = next(i for i in etapa["checklist"] if i["item"] == item_hike["item"])
                assert item["feito"] == item_hike["feito"]
                assert item["por"] == item_hike["por"]

    # criativos importada sem dados no card nasce com as 4 subtarefas padrão (A1)
    etapas_1 = _workflow(client, por_card["HIKE-8842"]["os_id"])
    assert [i["item"] for i in _etapa(etapas_1, "criativos")["checklist"]] == list(
        SUBTAREFAS_CRIATIVOS
    )

    # outbox: um `hike.card_imported` por card, com o histórico original do Hike (§2.3)
    repo = app.state.repositorio_os
    eventos = repo.listar_eventos(tipo="hike.card_imported")
    assert len(eventos) == 3
    historicos = {e.payload["card_id"]: e.payload["historico"] for e in eventos}
    for card in export["cards"]:
        assert historicos[card["card_id"]] == card["historico"]

    # log em hike_import_log: 3 entradas ok (§8-M2)
    logs = repo.listar_hike_logs(TENANT)
    assert [(log.hike_card_id, log.status) for log in logs] == [
        ("HIKE-8842", "ok"),
        ("HIKE-8907", "ok"),
        ("HIKE-8951", "ok"),
    ]

    # re-import da mesma fixture é idempotente: nada criado, tudo logado como duplicado
    de_novo = client.post("/api/v1/admin/hike/import", json=export, headers=_h("dev-admin"))
    assert de_novo.status_code == 201
    assert de_novo.json()["importados"] == 0 and de_novo.json()["duplicados"] == 3
    todas = client.get("/api/v1/os", headers=_h("dev-analista")).json()
    assert len(todas) == 3

    # RBAC: /admin/hike/import é rota admin (analista → 403)
    negado = client.post("/api/v1/admin/hike/import", json=export, headers=_h("dev-analista"))
    assert negado.status_code == 403
