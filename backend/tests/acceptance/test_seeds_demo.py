"""Aceites das seeds DEMO_MODE (SDD §11.4): OS-2026-0457 ponta a ponta.

`create_app(demo=True)` deve entregar o front demo FUNCIONANDO sem passo manual:
briefing 14 campos, segmento 847.312, JGC, Previsto congelado, telemetria 20 dias
com lift +24,1pp / ROAS 18,5x (monitor T13), propostas pendentes (T15 — sem LLM) e
apuração liberada (janela de 15 dias fechada — anti-peeking §8-M11-A1 respeitado).
Rodam via TestClient, sem docker, ZERO LLM (§1.3.5: LLMFake nem chega a ser chamado
— pendentes existem; o caminho do monitor é §10.6 determinístico).
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.atelie_seeds import semear_atelie
from adapters.demo_seeds import semear_demo
from adapters.embedding.fake import EmbeddingFake
from adapters.llm.fake import LLMFake
from adapters.observabilidade.langfuse import TracerLangfuse
from adapters.persistence.memoria import RepositorioOsMemoria
from app.config import Settings
from app.main import create_app, ping_db

TENANT = "torre-movel"
HEADERS = {"X-Tenant": TENANT, "Authorization": "Bearer dev-analista"}


@pytest.fixture()
def app_demo() -> FastAPI:
    # A11: embedding fake INJETADO no create_app — a seed RAG do demo roda no boot
    # e o hub real jamais é tocado em teste (§1.3.5).
    application = create_app(demo=True, embedding=EmbeddingFake())
    application.dependency_overrides[ping_db] = lambda: "ok"
    application.state.llm = LLMFake()  # §1.3.5 — hub real jamais em teste
    application.state.tracer = TracerLangfuse(Settings(_env_file=None, langfuse_enabled=False))
    return application


@pytest.fixture()
def client(app_demo: FastAPI) -> Iterator[TestClient]:
    with TestClient(app_demo, raise_server_exceptions=False) as test_client:
        yield test_client


def _os_demo(client: TestClient) -> dict:
    resposta = client.get("/api/v1/os?limit=100", headers=HEADERS)
    assert resposta.status_code == 200, resposta.text
    demo = [o for o in resposta.json() if o["codigo"] == "OS-2026-0457"]
    assert demo, "seed §11.4 ausente: OS-2026-0457 não listada"
    return demo[0]


def test_seeds_demo_os_completa(client: TestClient, app_demo: FastAPI) -> None:
    """OS demo em fase monitorada, briefing com 14 campos e segmento 847.312."""
    os_ = _os_demo(client)
    assert os_["fase"] == "monitorada"
    assert len(os_["briefing"]) == 14  # §8-M3: 14 campos
    repo = app_demo.state.repositorio_os
    os_id = uuid.UUID(os_["id"])
    segmentos = repo.listar_segmentos(os_id)
    assert segmentos and segmentos[-1].contagem_liquida == 847_312  # §11.4
    jornadas = repo.listar_jornadas(os_id)
    assert jornadas and jornadas[-1].previsto  # JGC + Previsto congelado


def test_seeds_demo_monitor_lift_e_roas(client: TestClient) -> None:
    """T13 (§8-M10): pares previsto×realizado com lift +24,1pp SIGNIFICATIVO e
    ROAS 18,5x; reconciliação ENS×extract dentro do limite (sem alerta A3)."""
    os_ = _os_demo(client)
    monitor = client.get(f"/api/v1/os/{os_['id']}/monitor", headers=HEADERS)
    assert monitor.status_code == 200, monitor.text
    corpo = monitor.json()

    lift = corpo["kpis"]["lift_pp"]["realizado"]
    assert round(lift["valor_pp"], 1) == 24.1  # §11.4: lift +24,1
    assert lift["significativo"] is True  # IC exclui zero (§8-M11-A2)
    assert round(corpo["kpis"]["roas"]["realizado"], 1) == 18.5  # §11.4: ROAS 18,5x
    assert corpo["kpis"]["conversoes"]["realizado"] == 271
    assert corpo["kpis"]["conversoes"]["previsto"]["p50"] == 248  # régua congelada
    assert corpo["reconciliacao"]["divergente"] is False  # A3: espelho < 2%
    assert corpo["launch"]["estado"] == "em_rampa"
    assert set(corpo["canais"]) == {"email", "push", "sms", "whatsapp"}


def test_seeds_demo_jornada_publicada_no_canvas(client: TestClient) -> None:
    """A14: `GET /os/{id}/jornada` (emenda §8-M7) devolve a versão PUBLICADA da demo
    com a paleta realista do §5.2 — o canvas T7 nunca abre vazio."""
    os_ = _os_demo(client)
    resposta = client.get(f"/api/v1/os/{os_['id']}/jornada", headers=HEADERS)
    assert resposta.status_code == 200, resposta.text
    jornada = resposta.json()
    assert jornada["estado"] == "publicado" and jornada["versao"] == 1
    tipos = {n["type"] for n in jornada["grafo"]["nodes"]}
    assert {
        "entrySource",
        "randomSplit",
        "sto",
        "decisionSplit",
        "wait",
        "channel.email",
        "channel.sms",
        "channel.whatsapp",
        "goal",
        "exit",
    } <= tipos  # paleta do mock T7 (§5.2)
    bracos = next(n for n in jornada["grafo"]["nodes"] if n["type"] == "randomSplit")
    assert {b["id"] for b in bracos["data"]["braços"]} == {"tratado", "holdout"}
    assert all("from" in a and "to" in a for a in jornada["grafo"]["edges"])  # contrato §5.1


def test_seeds_ids_deterministicos_entre_restarts() -> None:
    """A15: 2 execuções das seeds (restart simulado) geram os MESMOS ids — links do
    front (OS/jornada/snapshot/experimento/propostas/agentes) nunca quebram."""
    agora = datetime.now(UTC)

    def _ids(repositorio: RepositorioOsMemoria) -> dict[str, object]:
        os_ = repositorio.obter_os_por_codigo("OS-2026-0457")
        return {
            "os": os_.id,
            "jornadas": [j.id for j in repositorio.listar_jornadas(os_.id)],
            "segmentos": [s.id for s in repositorio.listar_segmentos(os_.id)],
            "snapshots": [s.id for s in repositorio.listar_snapshots(os_.id)],
            "experimento": repositorio.experimento_da_os(os_.id).id,
            "propostas": [p.id for p in repositorio.listar_propostas(os_.id)],
            "agentes": [a.id for a in repositorio.listar_agentes(TENANT)],
        }

    execucoes = []
    for _ in range(2):  # dois "boots" com relógios DIFERENTES — ids idênticos
        repositorio = RepositorioOsMemoria()
        semear_demo(repositorio, tenant_id=TENANT, agora=agora)
        semear_atelie(repositorio, tenant_id=TENANT, agora=agora)
        execucoes.append(_ids(repositorio))
        agora = agora + timedelta(hours=7)
    assert execucoes[0] == execucoes[1]
    assert execucoes[0]["jornadas"] and execucoes[0]["propostas"] and execucoes[0]["agentes"]


def test_seeds_demo_retro_propostas_e_apuracao(client: TestClient) -> None:
    """T15 (§8-M11): 2 propostas PENDENTES (sem invocar o optimize) e apuração
    liberada (janela fechada) com resultado significativo."""
    os_ = _os_demo(client)
    propostas = client.get(f"/api/v1/os/{os_['id']}/propostas", headers=HEADERS)
    assert propostas.status_code == 200, propostas.text
    corpo = propostas.json()
    assert corpo["geradas_agora"] is False and len(corpo["propostas"]) == 2
    assert all(p["estado"] == "proposta" for p in corpo["propostas"])

    portoes = client.get(f"/api/v1/os/{os_['id']}/portoes", headers=HEADERS)
    assert portoes.status_code == 200, portoes.text
    experimento_id = portoes.json()["portoes"]["experimento"]["id"]  # T15: alvo do apurar

    apurado = client.post(f"/api/v1/experimentos/{experimento_id}/apurar", headers=HEADERS)
    assert apurado.status_code == 200, apurado.text
    resultado = apurado.json()["resultado"]
    assert resultado["significativo"] is True
    assert round(resultado["lift"], 1) == 24.1
