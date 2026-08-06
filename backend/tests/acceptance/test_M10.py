"""Aceites do módulo M10 · Torre de Lançamento T12 (parte 1) + telemetria dupla e
Monitor T13 (parte 2) — SDD §8-M10, §4.1 `launch`/`telemetry_event`/`incidente`;
IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker e SEM REDE (§1.3.5): mock-sfmc IN-PROCESS (padrão
M9) para chegar ao APPLY OK que o armar exige; telemetria entra pelo webhook ENS com
ASSINATURA HMAC verificada; as 7 listas vêm da fixture `mocks/seeds/
lista_supressao.json` (§11.4). ZERO LLM em todo o caminho (§10.6): o hub é DERRUBADO
(`LLMFake(disponivel=False)`) antes do fluxo e tudo — simulação, apply, rampa,
breakers, kill, retomada — completa mesmo assim (NFR §10.6: forced_off completa
M9/M10).

Fluxo: OS → jornada simulada → previsto congelado → snapshot → aprovação + certificado
→ plan → apply (homolog) → armar → rampa 1% → 10% → 100% com portões automáticos.
"""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.fontes.extracts import ExtractsFixtures
from adapters.fontes.lista_supressao import SupressaoFixtures
from adapters.llm.fake import LLMFake
from adapters.sfmc.cliente import SfmcHttp
from api.v1.compilador import _relogio
from app.config import Settings, get_settings
from app.errors import PROBLEM_CONTENT_TYPE
from application.services.lancamento_service import ServicoLancamento
from domain.agentes.modelos import agente_uuid
from domain.audiencia.modelos import CertificadoElegibilidade, Segmento
from domain.governanca.modelos import Snapshot
from domain.jornada.canonico import hash_jgc
from domain.jornada.modelos import JornadaVersao
from tests.unit.util_mock_sfmc import carregar_mock_sfmc

modulo_mock = carregar_mock_sfmc()

TENANT = "torre-movel"
VOLUME_LIQUIDO = 50_000
PARAMS = {"seed": 42, "runs": 80, "n_personas": 500}
AMBIENTE = "homolog"

FIXTURE_SUPRESSAO = Path(__file__).resolve().parents[3] / "mocks" / "seeds" / "lista_supressao.json"

SQL_CONFORME = (
    "select contato_hash from base_clientes where opt_in_email = true "
    "and contato_hash not in (select contato_hash from lista_supressao where lista in "
    "('blacklist','fraude','nao_perturbe','optout','procon','inadimplente',"
    "'reprovado_credito'))"
)


def _h(token: str = "dev-analista") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _hash_ok(i: int) -> str:
    """contato_hash SINTÉTICO fora das listas (sha256 hex — nunca PII §10.2)."""
    return hashlib.sha256(f"contato-ok-{i:05d}".encode()).hexdigest()


def _hash_suprimido() -> str:
    """Amostra da lista `optout` da fixture (§8-M10-A2)."""
    dados = json.loads(FIXTURE_SUPRESSAO.read_text(encoding="utf-8"))
    return str(dados["listas"]["optout"]["amostras"][0])


def _grafo(os_codigo: str) -> dict[str, Any]:
    """JGC §5 válido (mesmo shape do M8/M9): entrada → split 90/10 → wait → e-mail
    → goal; braço holdout → exit."""
    return {
        "jgcVersion": "1.0",
        "meta": {
            "osCodigo": os_codigo,
            "tenant": TENANT,
            "reentrada": "nao",
            "quietHours": {"inicio": "20:00", "fim": "08:00"},
        },
        "nodes": [
            {
                "id": "n1",
                "type": "entrySource",
                "data": {"deRef": "DE_entrada", "modo": "fire_once", "reentrada": "nao"},
            },
            {
                "id": "n2",
                "type": "randomSplit",
                "data": {"braços": [{"id": "tratado", "pct": 90}, {"id": "holdout", "pct": 10}]},
            },
            {"id": "n3", "type": "wait", "data": {"duracao": "PT4H"}},
            {
                "id": "n4",
                "type": "channel.email",
                "data": {"assetRef": "asset-email-1", "optIn": True, "throttlePorHora": 25_000},
            },
            {"id": "n5", "type": "goal", "data": {"metrica": "conversion", "deRef": "DE_conv"}},
            {"id": "n6", "type": "exit", "data": {"motivo": "holdout"}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "n2", "cond": None},
            {"id": "e2", "from": "n2", "to": "n3", "cond": "tratado"},
            {"id": "e3", "from": "n2", "to": "n6", "cond": "holdout"},
            {"id": "e4", "from": "n3", "to": "n4", "cond": None},
            {"id": "e5", "from": "n4", "to": "n5", "cond": None},
        ],
    }


@pytest.fixture()
def mock_sfmc():  # type: ignore[no-untyped-def]
    return modulo_mock.create_app()


@pytest.fixture()
def app_sfmc(app: FastAPI, mock_sfmc) -> FastAPI:  # type: ignore[no-untyped-def]
    settings = Settings(
        _env_file=None,
        sfmc_auth_url="http://mock-sfmc/v2/token",
        sfmc_rest_url="http://mock-sfmc/rest",
        sfmc_soap_url="http://mock-sfmc/soap",
    )
    app.state.sfmc_port = SfmcHttp(settings, transport=httpx.ASGITransport(app=mock_sfmc))
    return app


def _snapshot_aplicado(client: TestClient, app: FastAPI) -> tuple[uuid.UUID, dict]:
    """Caminho §8-M8→M9 (padrão do test_M9): snapshot aprovado + certificado +
    plan + APPLY OK em homolog — pré-condição do armar (§8-M10).

    Hub LLM DERRUBADO desde o início (§10.6: caminho crítico — simulador,
    compilador, breakers, kill, retomada — completa M9/M10 SEM LLM)."""
    app.state.llm = LLMFake(disponivel=False)
    resposta = client.post(
        "/api/v1/os",
        json={"nome": "Upgrade Pós-Pago 5G", "tshirt": "G", "codigo": "OS-2026-0457"},
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    os_id = uuid.UUID(resposta.json()["id"])
    repo = app.state.repositorio_os
    repo.adicionar_segmento(
        Segmento(
            id=uuid.uuid4(),
            os_id=os_id,
            origem="estudio_sql",
            sql_publico=SQL_CONFORME,
            contagem_bruta=61_000,
            contagem_liquida=VOLUME_LIQUIDO,
            volume_abordagem={"email": {"n": VOLUME_LIQUIDO, "pct": 100.0}},
        )
    )
    jgc = _grafo("OS-2026-0457")
    jornada = JornadaVersao(id=uuid.uuid4(), os_id=os_id, versao=1, grafo=jgc, hash=hash_jgc(jgc))
    repo.adicionar_jornada(jornada)

    assert (
        client.post(f"/api/v1/jornadas/{jornada.id}/simular", json=PARAMS, headers=_h()).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/jornadas/{jornada.id}/congelar-previsto", headers=_h()).status_code
        == 200
    )
    snapshot = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=_h())
    assert snapshot.status_code == 201, snapshot.text
    snapshot = snapshot.json()

    token = client.post(
        f"/api/v1/snapshots/{snapshot['id']}/link-magico",
        json={"aprovador_email": "aprovador@claro.com.br"},  # A6 §10.5: link endereçado
        headers=_h(),
    ).json()["token"]
    decidida = client.post(
        f"/api/v1/aprovacao/{token}/decidir",
        json={"decisao": "aprovado", "decidido_por": "aprovador@claro.com.br"},
        headers={"X-Tenant": TENANT, "User-Agent": "pytest-m10"},
    )
    assert decidida.status_code == 200, decidida.text
    agora = datetime.now(UTC)
    repo.adicionar_certificado(
        CertificadoElegibilidade(
            id=uuid.uuid4(),
            os_id=os_id,
            hash="d" * 64,
            suprimidos={"optout": 1_000},
            liquido=VOLUME_LIQUIDO,
            emitido_em=agora,
            valido_ate=agora + timedelta(days=7),
        )
    )
    base = f"/api/v1/snapshots/{snapshot['id']}"
    assert client.post(f"{base}/plan?ambiente={AMBIENTE}", headers=_h()).status_code == 201
    aplicado = client.post(f"{base}/apply?ambiente={AMBIENTE}", headers=_h())
    assert aplicado.status_code == 201 and aplicado.json()["estado"] == "ok"
    return os_id, snapshot


def _armar_em_rampa(client: TestClient, app: FastAPI) -> tuple[uuid.UUID, dict]:
    """Snapshot aplicado → armado → onda 1 (1%) em rampa."""
    os_id, snapshot = _snapshot_aplicado(client, app)
    armado = client.post(f"/api/v1/launch/{snapshot['id']}/armar", headers=_h())
    assert armado.status_code == 201, armado.text
    launch = armado.json()
    assert launch["estado"] == "armado" and launch["onda_atual"] == 0
    onda1 = client.post(f"/api/v1/launch/{launch['id']}/avancar-onda", headers=_h())
    assert onda1.status_code == 200, onda1.text
    corpo = onda1.json()
    assert corpo["estado"] == "em_rampa" and corpo["onda_atual"] == 1
    return os_id, corpo


def _post_ens(client: TestClient, eventos: list[dict[str, Any]], *, assinar: bool = True):  # type: ignore[no-untyped-def]
    """Webhook ENS (§8-M10): corpo bruto + HMAC-sha256 com APP_SECRET no header."""
    corpo = json.dumps({"eventos": eventos}).encode("utf-8")
    headers = {"X-Tenant": TENANT, "Content-Type": "application/json"}
    if assinar:
        headers["X-ENS-Signature"] = hmac.new(
            get_settings().app_secret.encode("utf-8"), corpo, hashlib.sha256
        ).hexdigest()
    return client.post("/api/v1/webhooks/ens", content=corpo, headers=headers)


def _telemetria_onda(
    os_id: uuid.UUID, *, sents: int, delivered: int, bounces: int, optouts: int
) -> list[dict[str, Any]]:
    ts = datetime.now(UTC).isoformat()
    eventos: list[dict[str, Any]] = []
    for i in range(sents):
        eventos.append(
            {
                "os_id": str(os_id),
                "no_jgc": "n4",
                "canal": "email",
                "tipo": "sent",
                "contato_hash": _hash_ok(i),
                "ts": ts,
            }
        )
    for i in range(delivered):
        eventos.append(
            {
                "os_id": str(os_id),
                "canal": "email",
                "tipo": "delivered",
                "contato_hash": _hash_ok(i),
                "ts": ts,
            }
        )
    for i in range(bounces):
        eventos.append(
            {
                "os_id": str(os_id),
                "canal": "email",
                "tipo": "bounce",
                "contato_hash": _hash_ok(i),
                "ts": ts,
            }
        )
    for i in range(optouts):
        eventos.append(
            {
                "os_id": str(os_id),
                "canal": "email",
                "tipo": "optout",
                "contato_hash": _hash_ok(i),
                "ts": ts,
            }
        )
    return eventos


# --------------------------------------------------------------------- Aceites §8-M10


def test_M10_A1(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """A1: breaker (optout>0,6% da política congelada) DURANTE a onda → estado
    `pausado_breaker` AUTOMÁTICO (ingestão dispara a avaliação — zero humano, zero
    LLM); retomar exige humano (rota com alçada lider|aprovador)."""
    os_id, launch = _armar_em_rampa(client, app_sfmc)
    assert launch["breakers"]["optout_pct_max"] == 0.6  # política congelada (§4.1)

    # onda 1: 250 sents, 248 delivered (erro 0,8% ok), 1 bounce (0,4% ok),
    # 3 optouts = 1,2% > 0,6% ⇒ breaker
    ingestao = _post_ens(
        client, _telemetria_onda(os_id, sents=250, delivered=248, bounces=1, optouts=3)
    )
    assert ingestao.status_code == 202, ingestao.text
    avaliados = ingestao.json()["avaliados"]
    assert len(avaliados) == 1
    assert avaliados[0]["estado"] == "pausado_breaker"  # AUTOMÁTICO (A1)
    disparos = avaliados[0]["disparos"]
    assert [d["breaker"] for d in disparos] == ["optout"]
    assert disparos[0]["valor"] == 1.2 and disparos[0]["limite"] == 0.6

    repo = app_sfmc.state.repositorio_os
    persistido = repo.obter_launch(uuid.UUID(launch["id"]))
    assert persistido.estado == "pausado_breaker"
    assert repo.listar_eventos(os_id=os_id, tipo="launch.breaker_tripped")
    incidentes = repo.listar_incidentes(launch_id=persistido.id, estado="aberto")
    assert [(i.sev, i.tipo) for i in incidentes] == [("sev2", "optout")]  # tipado

    # pausado NÃO avança (409) e telemetria limpa NÃO retoma sozinha
    bloqueado = client.post(f"/api/v1/launch/{launch['id']}/avancar-onda", headers=_h())
    assert bloqueado.status_code == 409
    assert bloqueado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "humano" in bloqueado.json()["detail"]
    limpa = _post_ens(client, _telemetria_onda(os_id, sents=50, delivered=50, bounces=0, optouts=0))
    assert limpa.status_code == 202 and limpa.json()["avaliados"] == []  # não reavalia pausado
    assert repo.obter_launch(persistido.id).estado == "pausado_breaker"

    # retomar EXIGE humano com alçada: analista → 403; lider retoma (1 aprovação)
    assert client.post(f"/api/v1/launch/{launch['id']}/retomar", headers=_h()).status_code == 403
    retomada = client.post(f"/api/v1/launch/{launch['id']}/retomar", headers=_h("dev-lider"))
    assert retomada.status_code == 200, retomada.text
    corpo = retomada.json()
    assert corpo["retomado"] is True and corpo["exigidas"] == 1
    assert corpo["launch"]["estado"] == "em_rampa"
    assert repo.listar_incidentes(launch_id=persistido.id, estado="aberto") == []
    assert repo.listar_eventos(os_id=os_id, tipo="launch.retomado")

    # janela reiniciada na retomada: o portão automático deixa avançar para 10%
    onda2 = client.post(f"/api/v1/launch/{launch['id']}/avancar-onda", headers=_h())
    assert onda2.status_code == 200, onda2.text
    assert onda2.json()["onda_atual"] == 2 and onda2.json()["ondas"][1]["pct"] == 10


def test_M10_A2(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """A2: disparo (`sent`) para contato em lista de supressão (fixture §11.4) →
    incidente SEV1 TIPADO + KILL AUTOMÁTICO; retomada SEV1 exige 2 aprovadores
    DISTINTOS (repetir aprovador → 403)."""
    os_id, launch = _armar_em_rampa(client, app_sfmc)
    ts = datetime.now(UTC).isoformat()
    eventos = _telemetria_onda(os_id, sents=10, delivered=0, bounces=0, optouts=0)
    eventos.append(
        {
            "os_id": str(os_id),
            "no_jgc": "n4",
            "canal": "email",
            "tipo": "sent",
            "contato_hash": _hash_suprimido(),  # fixture: lista `optout`
            "ts": ts,
        }
    )
    ingestao = _post_ens(client, eventos)
    assert ingestao.status_code == 202, ingestao.text
    avaliado = ingestao.json()["avaliados"][0]
    assert avaliado["estado"] == "morto"  # KILL AUTOMÁTICO (A2)
    disparo = next(d for d in avaliado["disparos"] if d["breaker"] == "disparo_lista_supressao")
    assert disparo["sev"] == "sev1" and disparo["kill"] is True
    assert disparo["contatos_hash"] == [_hash_suprimido()]  # hash — nunca PII (§10.2)
    assert disparo["listas"] == ["optout"]

    repo = app_sfmc.state.repositorio_os
    launch_id = uuid.UUID(launch["id"])
    persistido = repo.obter_launch(launch_id)
    assert persistido.estado == "morto"
    assert any(e["tipo"] == "kill_automatico" for e in persistido.eventos)
    kills = repo.listar_eventos(os_id=os_id, tipo="launch.killed")
    assert len(kills) == 1 and kills[0].payload["automatico"] is True
    incidente = next(i for i in repo.listar_incidentes(launch_id=launch_id) if i.sev == "sev1")
    assert incidente.tipo == "disparo_lista_supressao" and incidente.estado == "aberto"

    # retomada SEV1: 1º aprovador registra; MESMO aprovador de novo → 403;
    # 2º aprovador DISTINTO conclui (§8-M10; segregação §10.5)
    primeira = client.post(f"/api/v1/launch/{launch['id']}/retomar", headers=_h("dev-lider"))
    assert primeira.status_code == 200, primeira.text
    corpo = primeira.json()
    assert corpo["retomado"] is False
    assert corpo["aprovacoes"] == 1 and corpo["exigidas"] == 2
    assert repo.obter_launch(launch_id).estado == "morto"  # segue morto

    repetido = client.post(f"/api/v1/launch/{launch['id']}/retomar", headers=_h("dev-lider"))
    assert repetido.status_code == 403
    assert "distintos" in repetido.json()["detail"].lower()

    segunda = client.post(f"/api/v1/launch/{launch['id']}/retomar", headers=_h("dev-aprovador"))
    assert segunda.status_code == 200, segunda.text
    corpo = segunda.json()
    assert corpo["retomado"] is True and corpo["aprovacoes"] == 2
    assert corpo["launch"]["estado"] == "em_rampa"
    incidente = next(i for i in repo.listar_incidentes(launch_id=launch_id) if i.sev == "sev1")
    assert incidente.estado == "resolvido"
    assert len(incidente.meta["retomada"]["aprovadores"]) == 2


# ------------------------------------------------- Contrato das demais regras §8-M10


def test_M10_armar_exige_apply_ok(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """§8-M10: armar sem APPLY OK → 409; com apply ok → 201 (breakers congelados);
    snapshot com launch ativo → re-armar 409."""
    os_id, snapshot = _snapshot_aplicado(client, app_sfmc)
    # snapshot v2 (sem apply): jornada nova → hash novo
    repo = app_sfmc.state.repositorio_os
    jgc2 = _grafo("OS-2026-0457")
    jgc2["nodes"][2]["data"]["duracao"] = "PT8H"
    jornada2 = JornadaVersao(
        id=uuid.uuid4(), os_id=os_id, versao=2, grafo=jgc2, hash=hash_jgc(jgc2)
    )
    repo.adicionar_jornada(jornada2)
    assert (
        client.post(
            f"/api/v1/jornadas/{jornada2.id}/simular", json=PARAMS, headers=_h()
        ).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/jornadas/{jornada2.id}/congelar-previsto", headers=_h()).status_code
        == 200
    )
    snapshot2 = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=_h()).json()

    sem_apply = client.post(f"/api/v1/launch/{snapshot2['id']}/armar", headers=_h())
    assert sem_apply.status_code == 409
    assert sem_apply.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "apply" in sem_apply.json()["detail"].lower()

    armado = client.post(f"/api/v1/launch/{snapshot['id']}/armar", headers=_h())
    assert armado.status_code == 201, armado.text
    assert set(armado.json()["breakers"]) == {
        "optout_pct_max",
        "bounce_pct_max",
        "erro_entrega_pct_max",
        "burn_rate_max",
    }
    de_novo = client.post(f"/api/v1/launch/{snapshot['id']}/armar", headers=_h())
    assert de_novo.status_code == 409  # launch ativo ocupa o snapshot


def test_M10_kill_2_etapas(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """§8-M10: kill em 2 ETAPAS — etapa 1 devolve token; confirmação errada → 409 e
    NÃO mata; token correto mata (incidente `kill_manual` + launch.killed); kill de
    launch morto → 409. Retomada de kill manual (sev2): 1 aprovação humana."""
    _, launch = _armar_em_rampa(client, app_sfmc)
    base = f"/api/v1/launch/{launch['id']}"

    etapa1 = client.post(f"{base}/kill", json={}, headers=_h())
    assert etapa1.status_code == 200, etapa1.text
    corpo1 = etapa1.json()
    assert corpo1["etapa"] == 1 and corpo1["confirmacao"]
    assert corpo1["launch"]["estado"] == "em_rampa"  # etapa 1 não mata

    errada = client.post(f"{base}/kill", json={"confirmacao": "nao-e-o-token"}, headers=_h())
    assert errada.status_code == 409
    repo = app_sfmc.state.repositorio_os
    assert repo.obter_launch(uuid.UUID(launch["id"])).estado == "em_rampa"

    etapa2 = client.post(f"{base}/kill", json={"confirmacao": corpo1["confirmacao"]}, headers=_h())
    assert etapa2.status_code == 200, etapa2.text
    assert etapa2.json()["etapa"] == 2
    assert etapa2.json()["launch"]["estado"] == "morto"
    incidentes = repo.listar_incidentes(launch_id=uuid.UUID(launch["id"]), estado="aberto")
    assert [(i.sev, i.tipo) for i in incidentes] == [("sev2", "kill_manual")]
    kills = repo.listar_eventos(tipo="launch.killed")
    assert kills and kills[-1].payload["automatico"] is False

    assert client.post(f"{base}/kill", json={}, headers=_h()).status_code == 409  # morto

    retomada = client.post(f"{base}/retomar", headers=_h("dev-aprovador"))
    assert retomada.status_code == 200 and retomada.json()["retomado"] is True
    assert retomada.json()["exigidas"] == 1  # sev2 — 1 humano basta (A1)
    assert retomada.json()["launch"]["estado"] == "em_rampa"


def test_M10_rampa_completa_e_concluido(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """§8-M10: rampa 1% → 10% → 100% com portão automático a cada avanço; após a
    última onda o launch CONCLUI; concluído não avança nem mata."""
    os_id, launch = _armar_em_rampa(client, app_sfmc)  # onda 1 (1%)
    base = f"/api/v1/launch/{launch['id']}"
    repo = app_sfmc.state.repositorio_os

    # telemetria saudável da onda 1 (limpa o portão para 10%)
    assert (
        _post_ens(
            client, _telemetria_onda(os_id, sents=100, delivered=100, bounces=0, optouts=0)
        ).status_code
        == 202
    )
    onda2 = client.post(f"{base}/avancar-onda", headers=_h()).json()
    assert (onda2["onda_atual"], onda2["ondas"][1]["pct"]) == (2, 10)
    onda3 = client.post(f"{base}/avancar-onda", headers=_h()).json()
    assert (onda3["onda_atual"], onda3["ondas"][2]["pct"]) == (3, 100)
    fim = client.post(f"{base}/avancar-onda", headers=_h()).json()
    assert fim["estado"] == "concluido"
    assert len(repo.listar_eventos(os_id=os_id, tipo="launch.wave_advanced")) == 3
    assert repo.listar_eventos(os_id=os_id, tipo="launch.concluido")
    assert client.post(f"{base}/avancar-onda", headers=_h()).status_code == 409
    assert client.post(f"{base}/kill", json={}, headers=_h()).status_code == 409


def test_M10_A3(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """A3: telemetria dupla — job extracts loader (fixture CSV §11) + reconciliação
    diária ENS×extract; divergência >2% no tipo `sent` (100 ENS × 96 extract = 4%) →
    ALERTA de reconciliação (incidente sev3 + evento, com dedupe); monitor traz par
    previsto×realizado em TODO KPI, sempre contra o Previsto CONGELADO do snapshot."""
    os_id, launch = _armar_em_rampa(client, app_sfmc)
    repo = app_sfmc.state.repositorio_os
    repo.obter_os(TENANT, os_id).briefing["metas"] = {"conversoes": 900, "roas": 12.0}

    # dia D (ENS, tempo real): 100 sents · 99 delivered · 1 bounce · 0 optout —
    # taxas todas DENTRO dos limites — + 8 conversões (6 tratado, 2 holdout)
    ts = datetime.now(UTC).isoformat()
    eventos = _telemetria_onda(os_id, sents=100, delivered=99, bounces=1, optouts=0)
    for i in range(6):
        eventos.append(
            {
                "os_id": str(os_id),
                "canal": "email",
                "tipo": "conversion",
                "contato_hash": _hash_ok(i),
                "ts": ts,
                "payload": {"grupo": "tratado"},
            }
        )
    for i in range(2):
        eventos.append(
            {
                "os_id": str(os_id),
                "canal": "email",
                "tipo": "conversion",
                "contato_hash": hashlib.sha256(f"contato-holdout-{i:05d}".encode()).hexdigest(),
                "ts": ts,
                "payload": {"grupo": "holdout"},
            }
        )
    ingestao = _post_ens(client, eventos)
    assert ingestao.status_code == 202, ingestao.text
    assert ingestao.json()["avaliados"][0]["estado"] == "em_rampa"  # nenhum breaker

    # D+1: job extracts loader + reconciliação — casos de uso SEM endpoint (§8-M10
    # define como job; padrão M9-drift), reusáveis pelo agendador
    servico = ServicoLancamento(repo, _relogio, SupressaoFixtures(), extracts=ExtractsFixtures())
    carga = servico.carregar_extracts(TENANT)
    assert carga["carregados"] == 204 and carga["ignorados"] == 0
    # extract NÃO soma nas taxas dos breakers (conciliação — não dobra contagem)
    assert repo.obter_launch(uuid.UUID(launch["id"])).estado == "em_rampa"

    resultado = servico.reconciliar(TENANT, os_id)
    assert resultado["divergente"] is True
    assert resultado["divergencias"] == ["sent"]  # só o tipo `sent` diverge (4% > 2%)
    assert resultado["por_tipo"]["sent"] == {
        "ens": 100,
        "extract": 96,
        "divergencia_pct": 4.0,
        "acima_limite": True,
    }
    assert resultado["por_tipo"]["delivered"]["acima_limite"] is False
    abertos = [
        i
        for i in repo.listar_incidentes(os_id=os_id, estado="aberto")
        if i.tipo == "reconciliacao_divergente"
    ]
    assert len(abertos) == 1 and abertos[0].sev == "sev3"  # ALERTA de reconciliação
    assert repo.listar_eventos(os_id=os_id, tipo="telemetry.reconciliacao_divergente")
    de_novo = servico.reconciliar(TENANT, os_id)  # job diário re-executa SEM duplicar
    assert de_novo["incidente_id"] == str(abertos[0].id)
    assert (
        len(
            [
                i
                for i in repo.listar_incidentes(os_id=os_id, estado="aberto")
                if i.tipo == "reconciliacao_divergente"
            ]
        )
        == 1
    )

    # monitor (T13): par previsto×realizado em TODO KPI, régua = snapshot congelado
    resposta = client.get(f"/api/v1/os/{os_id}/monitor", headers=_h())
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["kpis"] and corpo["canais"] and corpo["metas"]
    for nome, kpi in corpo["kpis"].items():
        assert set(kpi) == {"previsto", "realizado"}, f"KPI {nome} sem par (§8-M10)"
    for canal, pares in corpo["canais"].items():
        for nome, par in pares.items():
            assert set(par) == {"previsto", "realizado"}, f"{canal}.{nome} sem par"
    for nome, par in corpo["metas"].items():
        assert set(par) == {"previsto", "realizado"}, f"meta {nome} sem par"

    snapshot = repo.obter_snapshot(uuid.UUID(corpo["snapshot"]["id"]))
    assert corpo["kpis"]["conversoes"]["previsto"] == snapshot.previsto["conversoes"]
    assert corpo["snapshot"]["previsto_congelado_em"] == snapshot.previsto["congelado_em"]
    assert corpo["kpis"]["conversoes"]["realizado"] == 6  # tratado (recorte do motor §6)
    lift = corpo["kpis"]["lift_pp"]["realizado"]  # lift vs holdout COM IC95
    assert lift["valor_pp"] is not None and len(lift["ic95_pp"]) == 2
    assert lift["significativo"] is (lift["ic95_pp"][0] > 0 or lift["ic95_pp"][1] < 0)
    assert corpo["kpis"]["custo"]["realizado"] == pytest.approx(100 * 0.0018)  # custo REAL
    assert corpo["kpis"]["roas"]["realizado"] is not None
    assert corpo["metas"]["conversoes"] == {"previsto": 900, "realizado": 6}
    email = corpo["canais"]["email"]
    assert email["disparos"]["realizado"] == 100 and email["disparos"]["previsto"] > 0
    assert corpo["fontes"] == {"ens": 208, "extract": 204}
    assert corpo["launch"]["estado"] == "em_rampa"
    assert corpo["reconciliacao"]["divergente"] is True
    assert any(a["tipo"] == "reconciliacao_divergente" for a in corpo["reconciliacao"]["alertas"])


def test_M10_monitor_exige_previsto(client: TestClient, app: FastAPI) -> None:
    """§8-M10: monitor SEM snapshot com Previsto congelado → 409 (a régua §1.1.2 é
    obrigatória); OS inexistente → 404."""
    criada = client.post("/api/v1/os", json={"nome": "Sem previsto", "tshirt": "P"}, headers=_h())
    assert criada.status_code == 201
    sem_previsto = client.get(f"/api/v1/os/{criada.json()['id']}/monitor", headers=_h())
    assert sem_previsto.status_code == 409
    assert sem_previsto.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "previsto" in sem_previsto.json()["detail"].lower()
    assert client.get(f"/api/v1/os/{uuid.uuid4()}/monitor", headers=_h()).status_code == 404


def test_M10_webhook_assinatura_e_pii(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """§8-M10 (ingestão): assinatura ausente/errada → 401 e NADA é gravado; payload
    com PII (§10.2) → 422 e NADA é gravado; contato fora de sha256 → 422."""
    os_id, _ = _armar_em_rampa(client, app_sfmc)
    repo = app_sfmc.state.repositorio_os
    ts = datetime.now(UTC).isoformat()
    evento_ok = {
        "os_id": str(os_id),
        "canal": "email",
        "tipo": "sent",
        "contato_hash": _hash_ok(1),
        "ts": ts,
    }

    sem_assinatura = _post_ens(client, [evento_ok], assinar=False)
    assert sem_assinatura.status_code == 401
    assert sem_assinatura.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    corpo = json.dumps({"eventos": [evento_ok]}).encode()
    adulterada = client.post(
        "/api/v1/webhooks/ens",
        content=corpo,
        headers={
            "X-Tenant": TENANT,
            "Content-Type": "application/json",
            "X-ENS-Signature": "0" * 64,
        },
    )
    assert adulterada.status_code == 401
    assert repo.listar_telemetria(os_id) == []  # nada gravado

    com_pii = _post_ens(client, [{**evento_ok, "payload": {"email": "cliente@claro.com.br"}}])
    assert com_pii.status_code == 422
    assert "PII" in com_pii.json()["detail"] or "§10.2" in com_pii.json()["detail"]
    assert repo.listar_telemetria(os_id) == []

    contato_em_claro = _post_ens(client, [{**evento_ok, "contato_hash": "5511999998888"}])
    assert contato_em_claro.status_code == 422  # contrato §4.1: sha256 hex 64
    assert repo.listar_telemetria(os_id) == []


def test_M10_A4(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """A4: pergunta fora da camada semântica ("qual o CPF...") → RECUSA PADRÃO sem
    SQL executado (a pré-guarda de PII recusa SEM sequer chamar o LLM — §1.3.5);
    composição do LLM fora do dicionário (SQL livre / view desconhecida / parâmetro
    fora da whitelist) → recusa, zero execução; pergunta válida → resposta com a
    consulta nomeada `vw_metricas_*` ANEXADA (§8-M10: 'resposta inclui a query')."""
    os_id, _ = _armar_em_rampa(client, app_sfmc)
    repo = app_sfmc.state.repositorio_os
    repo.obter_os(TENANT, os_id).briefing["metas"] = {"conversoes": 900, "roas": 12.0}
    # telemetria mínima (mesmo shape do A3): 100 sents · 6 conversões tratado · 2 holdout
    ts = datetime.now(UTC).isoformat()
    eventos = _telemetria_onda(os_id, sents=100, delivered=100, bounces=0, optouts=0)
    for i in range(6):
        eventos.append(
            {
                "os_id": str(os_id),
                "canal": "email",
                "tipo": "conversion",
                "contato_hash": _hash_ok(i),
                "ts": ts,
                "payload": {"grupo": "tratado"},
            }
        )
    for i in range(2):
        eventos.append(
            {
                "os_id": str(os_id),
                "canal": "email",
                "tipo": "conversion",
                "contato_hash": hashlib.sha256(f"contato-holdout-{i:05d}".encode()).hexdigest(),
                "ts": ts,
                "payload": {"grupo": "holdout"},
            }
        )
    assert _post_ens(client, eventos).status_code == 202
    base = f"/api/v1/os/{os_id}/perguntar"

    # ---- fora da camada semântica: pedido de PII → recusa padrão SEM LLM (hub está
    # DERRUBADO desde _snapshot_aplicado — a recusa é 100% determinística) e SEM consulta
    recusada = client.post(
        base, json={"pergunta": "Qual o CPF do cliente que converteu ontem?"}, headers=_h()
    )
    assert recusada.status_code == 200, recusada.text
    corpo = recusada.json()
    assert corpo["recusado"] is True and corpo["consulta_executada"] is None  # zero SQL (A4)
    assert "cpf" in corpo["motivo_recusa"].lower()
    assert "camada semântica" in corpo["resposta"]  # recusa PADRÃO
    assert app_sfmc.state.llm.chamadas == []  # PII jamais chega a prompt (§1.3.5/§10.2)

    # ---- LLM tentando SQL LIVRE ou view fora do dicionário → recusa, zero execução (§7.2)
    for composicao_invalida in (
        {"consulta": "select contato_hash from telemetry_event", "parametros": {}},
        {"consulta": "vw_metricas_cpf", "parametros": {}},
        {"consulta": "vw_metricas_roas", "parametros": {"where_livre": "1=1"}},
    ):
        app_sfmc.state.llm = LLMFake(resposta=json.dumps(composicao_invalida))
        resposta = client.post(base, json={"pergunta": "Como está o desempenho?"}, headers=_h())
        assert resposta.status_code == 200, resposta.text
        corpo = resposta.json()
        assert corpo["recusado"] is True and corpo["consulta_executada"] is None
        assert len(app_sfmc.state.llm.chamadas) == 1  # LLM consultado; execução NEGADA

    # ---- pergunta VÁLIDA → resposta com a consulta executada anexada (§8-M10)
    app_sfmc.state.llm = LLMFake(
        resposta=json.dumps(
            {
                "consulta": "vw_metricas_roas",
                "parametros": {},
                "resposta": "O ROAS realizado está acima do previsto congelado.",
            }
        )
    )
    valida = client.post(base, json={"pergunta": "Qual o ROAS da campanha?"}, headers=_h())
    assert valida.status_code == 200, valida.text
    corpo = valida.json()
    assert corpo["recusado"] is False and corpo["via_ai"] is True
    executada = corpo["consulta_executada"]
    assert executada["nome"] == "vw_metricas_roas" and executada["metrica"] == "roas"
    assert "vw_metricas_roas" in executada["sql"]  # a query vai na resposta (§7.2)
    # régua = Previsto CONGELADO do snapshot do launch (mesma referência do monitor §1.1.2)
    snapshot_ref = next(s for s in repo.listar_snapshots(os_id) if repo.listar_launches(s.id))
    assert executada["resultado"]["roas"]["previsto"] == snapshot_ref.previsto["roas"]
    assert executada["resultado"]["custo"]["realizado"] == pytest.approx(100 * 0.0018)
    assert corpo["camada_semantica"]["consultas"] == [
        "vw_metricas_atingimento_meta",
        "vw_metricas_custo_por_pedido",
        "vw_metricas_lift",
        "vw_metricas_roas",
    ]

    # ---- consulta parametrizada (NL→consulta nomeada+PARÂMETROS — §8-M10 parte 3)
    app_sfmc.state.llm = LLMFake(
        resposta=json.dumps(
            {
                "consulta": "vw_metricas_atingimento_meta",
                "parametros": {"meta": "conversoes"},
                "resposta": "Atingimento da meta de conversões.",
            }
        )
    )
    meta = client.post(base, json={"pergunta": "Atingimos a meta de conversões?"}, headers=_h())
    assert meta.status_code == 200, meta.text
    executada = meta.json()["consulta_executada"]
    assert executada["parametros"] == {"meta": "conversoes"}
    assert executada["resultado"]["metas"] == [
        {"meta": "conversoes", "alvo": 900, "realizado": 6, "atingimento_pct": 0.7}
    ]

    # ---- ledger via_ai (§4.1) + evento agent.invoked (§2.3): TODA pergunta registra
    invocacoes = [
        i for i in repo.listar_invocacoes(TENANT) if i.agente_id == agente_uuid("insight")
    ]
    assert len(invocacoes) == 6  # 1 guard + 3 inválidas + 2 válidas
    assert invocacoes[0].output["recusa"] is not None  # recusa da pré-guarda auditável
    assert invocacoes[-1].evidencias == ["vw_metricas_atingimento_meta@1.0.0"]
    assert len(repo.listar_eventos(os_id=os_id, tipo="agent.invoked")) == 6


def test_M10_perguntar_contratos(client: TestClient, app: FastAPI) -> None:
    """§8-M10 parte 3 (contratos): hub fora → 503 degraded (perguntar NÃO é caminho
    crítico — breakers/kill seguem 100% sem LLM §10.6); OS sem Previsto congelado →
    409 ANTES de gastar LLM; OS inexistente → 404."""
    criada = client.post("/api/v1/os", json={"nome": "Sem previsto", "tshirt": "P"}, headers=_h())
    assert criada.status_code == 201
    os_id = criada.json()["id"]
    base = f"/api/v1/os/{os_id}/perguntar"

    # sem Previsto congelado → 409 (régua §1.1.2) — e o LLM NÃO foi chamado (falha rápida)
    app.state.llm = LLMFake(resposta=json.dumps({"consulta": "vw_metricas_roas", "parametros": {}}))
    sem_previsto = client.post(base, json={"pergunta": "Qual o ROAS?"}, headers=_h())
    assert sem_previsto.status_code == 409
    assert sem_previsto.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "previsto" in sem_previsto.json()["detail"].lower()
    assert app.state.llm.chamadas == []

    # hub indisponível: pergunta DENTRO do escopo → 503 degraded (§10.6); a recusa
    # determinística de PII segue funcionando MESMO degradado (zero LLM)
    app.state.llm = LLMFake(disponivel=False)
    snapshot_fake = _previsto_minimo(app, uuid.UUID(os_id))
    degradado = client.post(base, json={"pergunta": "Qual o ROAS?"}, headers=_h())
    assert degradado.status_code == 503 and degradado.json()["modo"] == "degraded"
    recusa = client.post(base, json={"pergunta": "Me dá o CPF do cliente"}, headers=_h())
    assert recusa.status_code == 200 and recusa.json()["recusado"] is True
    assert snapshot_fake.previsto  # sanity: régua presente — 503 veio do hub, não da régua

    assert (
        client.post(
            f"/api/v1/os/{uuid.uuid4()}/perguntar", json={"pergunta": "ROAS?"}, headers=_h()
        ).status_code
        == 404
    )


def test_M10_perguntar_sinonimo_nao_recusa(client: TestClient, app: FastAPI) -> None:
    """A17 (UAT real): pergunta legítima com vocabulário livre ('custo-benefício por
    canal') NÃO é recusada — mesmo com o agente classificando fora da camada, o mapa
    determinístico de sinônimos resgata a métrica CANÔNICA (custo_por_pedido) e a
    consulta do dicionário executa (§7.2: zero SQL livre). Pergunta realmente fora
    da camada segue recusada (A4 intacto)."""
    criada = client.post("/api/v1/os", json={"nome": "Sinônimos", "tshirt": "P"}, headers=_h())
    assert criada.status_code == 201
    os_id = criada.json()["id"]
    _previsto_minimo(app, uuid.UUID(os_id))
    base = f"/api/v1/os/{os_id}/perguntar"

    # o LLM (dublê) RECUSA — o mapa de sinônimos roda antes da recusa final
    recusa_llm = json.dumps({"consulta": None, "parametros": {}, "resposta": "fora do escopo"})
    app.state.llm = LLMFake(resposta=recusa_llm)
    resposta = client.post(
        base, json={"pergunta": "Qual o custo-benefício por canal da campanha?"}, headers=_h()
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["recusado"] is False and corpo["motivo_recusa"] is None
    assert corpo["consulta_executada"]["nome"] == "vw_metricas_custo_por_pedido"
    assert "vw_metricas_custo_por_pedido" in corpo["consulta_executada"]["sql"]

    outra = client.post(base, json={"pergunta": "Qual a conversão por real gasto?"}, headers=_h())
    assert outra.status_code == 200
    assert outra.json()["consulta_executada"]["nome"] == "vw_metricas_custo_por_pedido"

    # sem sinônimo mapeável, a recusa PADRÃO permanece (nada é executado)
    fora = client.post(base, json={"pergunta": "Como está o clima em Campinas?"}, headers=_h())
    assert fora.status_code == 200
    assert fora.json()["recusado"] is True and fora.json()["consulta_executada"] is None


def _previsto_minimo(app: FastAPI, os_id: uuid.UUID) -> Snapshot:
    """Snapshot com Previsto congelado mínimo (shape do motor §6) direto no repo."""
    snapshot = Snapshot(
        id=uuid.uuid4(),
        os_id=os_id,
        hash="e" * 64,
        conteudo={"componentes": {}},
        previsto={
            "conversoes": 100,
            "roas": 10.0,
            "custo": 90.0,
            "receita": 900.0,
            "lift_pp": 2.0,
            "parametros": {"ticket_medio": 9.0},
            "funil": {},
            "congelado_em": datetime.now(UTC).isoformat(),
        },
    )
    app.state.repositorio_os.adicionar_snapshot(snapshot)
    return snapshot
