"""Aceites do módulo M9 · Compilador plan/apply (fatia 1) + Pré-voo & Drift (fatia 2)
(SDD §5.4, §5.4.5, §8-M9) — IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker e SEM REDE (§1.3.5): o mock-sfmc (§11.1) é usado
IN-PROCESS — o adapter `SfmcHttp` recebe `httpx.ASGITransport(app=mock)` injetado em
`app.state.sfmc_port` (dependência `get_sfmc` do router M9); o chaos (`/chaos/drift`)
também é injetado in-process via TestClient do próprio mock. ZERO LLM em todo o
caminho (§5.4): compilação, plan/apply, pré-voo e drift são determinísticos.

Fluxo (§8-M8→M9): OS → jornada simulada → previsto congelado → snapshot → link mágico
aprovado + certificado válido → plan → [preflight] → apply. Golden files (A2) em
`tests/contract/golden/` — comparação BYTE A BYTE (util_golden.py).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.sfmc.cliente import SfmcHttp
from app.config import Settings
from app.errors import PROBLEM_CONTENT_TYPE
from domain.audiencia.modelos import CertificadoElegibilidade, Segmento
from domain.jornada.canonico import hash_jgc
from domain.jornada.modelos import JornadaVersao
from tests.contract.util_golden import GOLDEN_DIR, arquivos_golden, recursos_golden
from tests.unit.util_mock_sfmc import carregar_mock_sfmc

modulo_mock = carregar_mock_sfmc()

TENANT = "torre-movel"
VOLUME_LIQUIDO = 50_000
PARAMS = {"seed": 42, "runs": 80, "n_personas": 500}
AMBIENTE = "homolog"

# fire_once → 5 recursos: 2 DEs + 1 eventDefinition + 1 asset + 1 journey (§5.4.1)
RECURSOS_V1 = 5

# Itens da bateria do pré-voo (§8-M9), na ordem executada
ITENS_PREFLIGHT = [
    "des_schema",
    "frescor_hybris",
    "opt_in",
    "listas_last_mile",
    "lint_ampscript",
    "limites_sfmc",
    "drift_zero",
    "seed_dry_run",
]

# SQL público CONFORME (Guard §8-M5: 7 listas + opt-in no WHERE) p/ o last-mile
SQL_CONFORME = (
    "select contato_hash from base_clientes where opt_in_email = true "
    "and contato_hash not in (select contato_hash from lista_supressao where lista in "
    "('blacklist','fraude','nao_perturbe','optout','procon','inadimplente',"
    "'reprovado_credito'))"
)


def _h(token: str = "dev-analista") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _grafo(os_codigo: str) -> dict[str, Any]:
    """JGC §5 válido (§5.3), mesmo shape do M8: entrada → randomSplit 90/10 →
    wait → e-mail → goal; braço holdout → exit."""
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
    """App do mock-sfmc POR TESTE (estado limpo) — usado só in-process (§1.3.5)."""
    return modulo_mock.create_app()


@pytest.fixture()
def app_sfmc(app: FastAPI, mock_sfmc) -> FastAPI:  # type: ignore[no-untyped-def]
    """Injeta o SFMCPort do app apontando para o mock via transport ASGI."""
    settings = Settings(
        _env_file=None,
        sfmc_auth_url="http://mock-sfmc/v2/token",
        sfmc_rest_url="http://mock-sfmc/rest",
        sfmc_soap_url="http://mock-sfmc/soap",
    )
    app.state.sfmc_port = SfmcHttp(settings, transport=httpx.ASGITransport(app=mock_sfmc))
    return app


def _semear_jornada(client: TestClient, app: FastAPI) -> tuple[uuid.UUID, uuid.UUID]:
    """OS via API + segmento recontado/jornada direto no repositório (padrão M8)."""
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
            sql_publico=SQL_CONFORME,  # last-mile do pré-voo (fatia 2) varre este SQL
            contagem_bruta=61_000,
            contagem_liquida=VOLUME_LIQUIDO,
            volume_abordagem={"email": {"n": VOLUME_LIQUIDO, "pct": 100.0}},
        )
    )
    jgc = _grafo("OS-2026-0457")
    jornada = JornadaVersao(id=uuid.uuid4(), os_id=os_id, versao=1, grafo=jgc, hash=hash_jgc(jgc))
    repo.adicionar_jornada(jornada)
    return jornada.id, os_id


def _certificar(app: FastAPI, os_id: uuid.UUID, *, valido: bool = True) -> None:
    agora = datetime.now(UTC)
    app.state.repositorio_os.adicionar_certificado(
        CertificadoElegibilidade(
            id=uuid.uuid4(),
            os_id=os_id,
            hash=("d" if valido else "c") * 64,
            suprimidos={"optout": 1_000},
            liquido=VOLUME_LIQUIDO,
            emitido_em=agora if valido else agora - timedelta(days=8),
            valido_ate=agora + timedelta(days=7) if valido else agora - timedelta(days=1),
        )
    )


def _snapshot_da_jornada(client: TestClient, jornada_id: uuid.UUID, os_id: uuid.UUID) -> dict:
    """Simula → congela previsto → snapshot (pré-requisitos §8-M8)."""
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h()).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/congelar-previsto", headers=_h()).status_code
        == 200
    )
    snapshot = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=_h())
    assert snapshot.status_code == 201, snapshot.text
    return snapshot.json()


def _aprovar(client: TestClient, snapshot_id: str) -> None:
    token = client.post(f"/api/v1/snapshots/{snapshot_id}/link-magico", headers=_h()).json()[
        "token"
    ]
    decidida = client.post(
        f"/api/v1/aprovacao/{token}/decidir",
        json={"decisao": "aprovado", "decidido_por": "aprovador@claro.com.br"},
        headers={"X-Tenant": TENANT, "User-Agent": "pytest-m9"},
    )
    assert decidida.status_code == 200, decidida.text


def _preparar_snapshot_aprovado(client: TestClient, app: FastAPI) -> tuple[uuid.UUID, dict]:
    jornada_id, os_id = _semear_jornada(client, app)
    snapshot = _snapshot_da_jornada(client, jornada_id, os_id)
    _aprovar(client, snapshot["id"])
    _certificar(app, os_id)
    return os_id, snapshot


def _estado_mock(mock_sfmc) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    estado = mock_sfmc.state.sfmc
    return {
        colecao: dict(estado[colecao])
        for colecao in (
            "event_definitions",
            "interactions",
            "assets",
            "data_extensions",
            "automations",
        )
    }


# ---------------------------------------------------------------------- Aceites §8-M9


def test_M9_A1(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """A1: apply sem plan prévio → 409 problem+json; com plan, apply executa e o
    `sync_run` (plan e apply) fica consultável em GET /sync-runs/{id}."""
    os_id, snapshot = _preparar_snapshot_aprovado(client, app_sfmc)

    sem_plan = client.post(
        f"/api/v1/snapshots/{snapshot['id']}/apply?ambiente={AMBIENTE}", headers=_h()
    )
    assert sem_plan.status_code == 409, sem_plan.text
    assert sem_plan.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "plan" in sem_plan.json()["detail"]

    plan = client.post(f"/api/v1/snapshots/{snapshot['id']}/plan?ambiente={AMBIENTE}", headers=_h())
    assert plan.status_code == 201, plan.text
    corpo_plan = plan.json()
    assert corpo_plan["fase"] == "plan" and corpo_plan["estado"] == "ok"
    assert [i["acao"] for i in corpo_plan["plano"]] == ["criar"] * RECURSOS_V1
    # ordem de dependência §5.4.1: DEs → EventDef → Asset → Journey
    assert [i["tipo_sfmc"] for i in corpo_plan["plano"]] == [
        "dataExtension",
        "dataExtension",
        "eventDefinition",
        "asset",
        "journey",
    ]

    apply_ = client.post(
        f"/api/v1/snapshots/{snapshot['id']}/apply?ambiente={AMBIENTE}", headers=_h()
    )
    assert apply_.status_code == 201, apply_.text
    corpo_apply = apply_.json()
    assert corpo_apply["fase"] == "apply" and corpo_apply["estado"] == "ok"
    assert corpo_apply["resultado"]["mutacoes"] == RECURSOS_V1
    assert corpo_apply["api_calls"] > 0

    # GET /sync-runs/{id} (§8-M9) — escopo do tenant; e evento sync.applied (§2.3)
    for run in (corpo_plan, corpo_apply):
        lido = client.get(f"/api/v1/sync-runs/{run['id']}", headers=_h())
        assert lido.status_code == 200, lido.text
        assert lido.json()["fase"] == run["fase"]
    repo = app_sfmc.state.repositorio_os
    assert repo.listar_eventos(os_id=os_id, tipo="sync.applied")
    # registry (§4.1): 5 recursos vinculados ao snapshot aplicado
    registros = repo.listar_registros(TENANT, AMBIENTE)
    assert len(registros) == RECURSOS_V1
    assert {r.snapshot_hash for r in registros} == {snapshot["hash"]}
    # apply ok publica a versão do twin (§4.1 jornada_versao.estado)
    assert repo.listar_jornadas(os_id)[-1].estado == "publicado"


async def test_M9_A2(mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """A2: payloads REST (JSON) e SOAP (XML) gerados pelo compilador batem BYTE A
    BYTE com tests/contract/golden/*; o mock-sfmc valida o schema de todos eles."""
    gerados = arquivos_golden()
    assert set(gerados) == {p.name for p in GOLDEN_DIR.iterdir()}
    for nome, conteudo in sorted(gerados.items()):
        assert (GOLDEN_DIR / nome).read_bytes() == conteudo, f"golden divergente: {nome}"

    # mock-sfmc valida o schema (§11.1): todo payload é aceito na criação
    settings = Settings(
        _env_file=None,
        sfmc_auth_url="http://mock-sfmc/v2/token",
        sfmc_rest_url="http://mock-sfmc/rest",
        sfmc_soap_url="http://mock-sfmc/soap",
    )
    adapter = SfmcHttp(settings, transport=httpx.ASGITransport(app=mock_sfmc))
    criadores = {
        "dataExtension": adapter.criar_data_extension,
        "eventDefinition": adapter.criar_event_definition,
        "asset": adapter.criar_asset,
        "journey": adapter.criar_interaction,
        "automation": adapter.criar_automation,
    }

    for item in recursos_golden():
        await criadores[str(item["tipo_sfmc"])](item["payload"])
    estado = _estado_mock(mock_sfmc)
    assert len(estado["data_extensions"]) == 2
    assert len(estado["event_definitions"]) == 1
    assert len(estado["assets"]) == 1
    assert len(estado["interactions"]) == 1
    assert len(estado["automations"]) == 1


def test_M9_A3(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """A3: re-execução do apply com o MESMO hash → 0 mutações (idempotência por
    externalKey §5.4.1) — nem sem re-plan (estado real reconferido), nem com
    re-plan (que marca tudo `manter`)."""
    _, snapshot = _preparar_snapshot_aprovado(client, app_sfmc)
    base = f"/api/v1/snapshots/{snapshot['id']}"
    assert client.post(f"{base}/plan?ambiente={AMBIENTE}", headers=_h()).status_code == 201
    primeiro = client.post(f"{base}/apply?ambiente={AMBIENTE}", headers=_h()).json()
    assert primeiro["resultado"]["mutacoes"] == RECURSOS_V1
    estado_apos_primeiro = _estado_mock(mock_sfmc)
    # `seq` = contador de CRIAÇÕES do mock (incrementa em todo create REST/SOAP):
    # congelá-lo pega inclusive mutação transitória (criar+destruir) que a
    # comparação de coleções não veria.
    seq_apos_primeiro = mock_sfmc.state.sfmc["seq"]

    # re-apply SEM re-plan: o executor reconfere o estado real → tudo `mantido`
    segundo = client.post(f"{base}/apply?ambiente={AMBIENTE}", headers=_h()).json()
    assert segundo["estado"] == "ok"
    assert segundo["resultado"]["mutacoes"] == 0
    assert {r["acao_executada"] for r in segundo["resultado"]["recursos"]} == {"mantido"}
    assert _estado_mock(mock_sfmc) == estado_apos_primeiro  # 0 mutações no SFMC
    assert mock_sfmc.state.sfmc["seq"] == seq_apos_primeiro  # contador do mock: 0 criações

    # re-plan do MESMO hash: plano inteiro `manter` (nada a criar/alterar/destruir)
    replan = client.post(f"{base}/plan?ambiente={AMBIENTE}", headers=_h()).json()
    assert [i["acao"] for i in replan["plano"]] == ["manter"] * RECURSOS_V1
    terceiro = client.post(f"{base}/apply?ambiente={AMBIENTE}", headers=_h()).json()
    assert terceiro["resultado"]["mutacoes"] == 0
    assert _estado_mock(mock_sfmc) == estado_apos_primeiro
    assert mock_sfmc.state.sfmc["seq"] == seq_apos_primeiro


# ------------------------------------------------- Contrato das demais regras §5.4


def test_M9_apply_exige_aprovacao_e_certificado(
    client: TestClient, app_sfmc: FastAPI, mock_sfmc
) -> None:  # type: ignore[no-untyped-def]
    """§5.4.4: apply sem aprovação → 409; certificado ausente/EXPIRADO → 409
    (M5-A3: publish recusa certificado expirado); com ambos → executa."""
    jornada_id, os_id = _semear_jornada(client, app_sfmc)
    snapshot = _snapshot_da_jornada(client, jornada_id, os_id)
    base = f"/api/v1/snapshots/{snapshot['id']}"
    assert client.post(f"{base}/plan?ambiente={AMBIENTE}", headers=_h()).status_code == 201

    sem_aprovacao = client.post(f"{base}/apply?ambiente={AMBIENTE}", headers=_h())
    assert sem_aprovacao.status_code == 409
    assert "aprova" in sem_aprovacao.json()["detail"].lower()

    _aprovar(client, snapshot["id"])
    sem_certificado = client.post(f"{base}/apply?ambiente={AMBIENTE}", headers=_h())
    assert sem_certificado.status_code == 409
    assert "certificado" in sem_certificado.json()["detail"].lower()

    _certificar(app_sfmc, os_id, valido=False)  # expirado → recusa (M5-A3)
    expirado = client.post(f"{base}/apply?ambiente={AMBIENTE}", headers=_h())
    assert expirado.status_code == 409
    assert "expirado" in expirado.json()["detail"].lower()

    _certificar(app_sfmc, os_id, valido=True)
    ok = client.post(f"{base}/apply?ambiente={AMBIENTE}", headers=_h())
    assert ok.status_code == 201 and ok.json()["estado"] == "ok"


def test_M9_orcamento_estourado_faz_rollback(
    client: TestClient, app_sfmc: FastAPI, mock_sfmc
) -> None:  # type: ignore[no-untyped-def]
    """§5.4.2: orçamento SFMC_API_BUDGET_PER_APPLY excedido → rollback compensatório
    (destrói o que ESTA run criou, em ordem inversa) e estado `revertido`."""
    _, snapshot = _preparar_snapshot_aprovado(client, app_sfmc)
    base = f"/api/v1/snapshots/{snapshot['id']}"
    assert client.post(f"{base}/plan?ambiente={AMBIENTE}", headers=_h()).status_code == 201

    app_sfmc.state.sfmc_api_budget = 3  # obter DE1 + criar DE1 + obter DE2 → estoura
    revertido = client.post(f"{base}/apply?ambiente={AMBIENTE}", headers=_h())
    assert revertido.status_code == 201, revertido.text
    corpo = revertido.json()
    assert corpo["estado"] == "revertido"
    assert "orçamento" in corpo["resultado"]["erro"].lower()
    assert corpo["resultado"]["revertidos"] == ["DE_entrada"]
    estado = _estado_mock(mock_sfmc)
    assert all(len(colecao) == 0 for colecao in estado.values())  # compensado
    assert app_sfmc.state.repositorio_os.listar_registros(TENANT, AMBIENTE) == []

    # com orçamento normal, o MESMO plano aplica limpo (recuperação idempotente)
    del app_sfmc.state.sfmc_api_budget
    ok = client.post(f"{base}/apply?ambiente={AMBIENTE}", headers=_h()).json()
    assert ok["estado"] == "ok" and ok["resultado"]["mutacoes"] == RECURSOS_V1


def test_M9_plan_novo_hash_avisos_destrutivos(
    client: TestClient, app_sfmc: FastAPI, mock_sfmc
) -> None:  # type: ignore[no-untyped-def]
    """§5.4.3: novo snapshot (hash novo) → plan marca os recursos do hash anterior
    como `destruir` com AVISO destrutivo obrigatório (Event Source: 'reinicia
    contatos em espera'); DEs (referenciadas por deRef) permanecem `manter`."""
    os_id, snapshot1 = _preparar_snapshot_aprovado(client, app_sfmc)
    base1 = f"/api/v1/snapshots/{snapshot1['id']}"
    assert client.post(f"{base1}/plan?ambiente={AMBIENTE}", headers=_h()).status_code == 201
    assert client.post(f"{base1}/apply?ambiente={AMBIENTE}", headers=_h()).status_code == 201

    # v2 do twin: wait maior → JGC novo → hash novo → snapshot novo (§1.1.1)
    repo = app_sfmc.state.repositorio_os
    jgc2 = _grafo("OS-2026-0457")
    jgc2["nodes"][2]["data"]["duracao"] = "PT8H"
    jornada2 = JornadaVersao(
        id=uuid.uuid4(), os_id=os_id, versao=2, grafo=jgc2, hash=hash_jgc(jgc2)
    )
    repo.adicionar_jornada(jornada2)
    snapshot2 = _snapshot_da_jornada(client, jornada2.id, os_id)
    assert snapshot2["hash"] != snapshot1["hash"]

    plano = client.post(
        f"/api/v1/snapshots/{snapshot2['id']}/plan?ambiente={AMBIENTE}", headers=_h()
    ).json()["plano"]
    acoes = {(i["tipo_sfmc"], i["acao"]) for i in plano}
    assert ("dataExtension", "manter") in acoes  # DEs sobrevivem (deRef estável)
    assert ("eventDefinition", "criar") in acoes and ("journey", "criar") in acoes
    destruir = [i for i in plano if i["acao"] == "destruir"]
    assert {i["tipo_sfmc"] for i in destruir} == {"eventDefinition", "asset", "journey"}
    assert all(i["aviso"] for i in destruir)  # aviso destrutivo OBRIGATÓRIO (§5.4.3)
    aviso_entrada = next(i["aviso"] for i in destruir if i["tipo_sfmc"] == "eventDefinition")
    assert "reinicia" in aviso_entrada and "espera" in aviso_entrada


# ---------------------------------------------------- Fatia 2 · Pré-voo & Drift (§8-M9)


def _aplicar_em_prod(client: TestClient, app: FastAPI, mock_sfmc) -> tuple[uuid.UUID, dict]:  # type: ignore[no-untyped-def]
    """Caminho §5.4.4: aprovado + certificado + plan prod + pré-voo (sem fail) + apply."""
    os_id, snapshot = _preparar_snapshot_aprovado(client, app)
    base = f"/api/v1/snapshots/{snapshot['id']}"
    assert client.post(f"{base}/plan?ambiente=prod", headers=_h()).status_code == 201
    prevoo = client.post(f"/api/v1/preflight/{snapshot['id']}?ambiente=prod", headers=_h())
    assert prevoo.status_code == 201, prevoo.text
    assert prevoo.json()["resultado"] in ("verde", "amarelo")  # warns não bloqueiam
    aplicado = client.post(f"{base}/apply?ambiente=prod", headers=_h())
    assert aplicado.status_code == 201 and aplicado.json()["estado"] == "ok"
    return os_id, snapshot


def _injetar_drift(mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """A4: drift injetado no mock VIA /chaos/drift (§11.1) — in-process, sem rede."""
    with TestClient(mock_sfmc) as chaos:
        assert chaos.post("/chaos/drift").json()["chaos"]["drift"] is True


def test_M9_A4(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """A4: drift injetado no mock em PROD → `drift_check` (retrieve → decompila →
    compara hash/campos) e pendência AUTOMÁTICA BLOQUEANTE na OS (dedupe em re-runs);
    o avanço de fase fica travado (§8-M1-A1) até resolução."""
    os_id, _ = _aplicar_em_prod(client, app_sfmc, mock_sfmc)
    _injetar_drift(mock_sfmc)

    checks = client.get("/api/v1/drift?ambiente=prod", headers=_h())
    assert checks.status_code == 200, checks.text
    corpo = checks.json()
    assert len(corpo) == RECURSOS_V1
    assert {c["estado"] for c in corpo} == {"drift_sfmc"}
    for check in corpo:  # comparação por hash/campos com evidência (§5.4.5)
        assert check["diff"]["ambiente"] == "prod"
        assert check["diff"]["hash_twin"] != check["diff"]["hash_sfmc"]
        assert "name" in check["diff"]["campos"]
        assert "editado fora do twin" in check["diff"]["campos"]["name"]["sfmc"]

    repo = app_sfmc.state.repositorio_os
    pendencias = [p for p in repo.listar_pendencias(os_id) if p.origem == "drift:prod"]
    assert len(pendencias) == 1
    automatica = pendencias[0]
    assert automatica.status == "aberta" and automatica.bloqueante and not automatica.via_ai
    assert repo.listar_eventos(os_id=os_id, tipo="drift.detected")

    # pendência bloqueante trava o avanço de fase (gate §8-M1-A1)
    avanco = client.post(f"/api/v1/os/{os_id}/fase", json={"fase": "discutida"}, headers=_h())
    assert avanco.status_code == 409
    assert avanco.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    # re-run do job (on-demand) NÃO duplica a pendência automática (dedupe)
    assert client.get("/api/v1/drift?ambiente=prod", headers=_h()).status_code == 200
    assert len([p for p in repo.listar_pendencias(os_id) if p.origem == "drift:prod"]) == 1


def test_M9_drift_resolver(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """§8-M9: resolver adopt/enforce/excecao — excecao EXIGE prazo (422); resolver
    todos os drifts do ambiente resolve a pendência automática; re-resolver → 409."""
    os_id, _ = _aplicar_em_prod(client, app_sfmc, mock_sfmc)
    _injetar_drift(mock_sfmc)
    checks = client.get("/api/v1/drift?ambiente=prod", headers=_h()).json()
    assert len(checks) == RECURSOS_V1

    sem_prazo = client.post(
        f"/api/v1/drift/{checks[0]['id']}/resolver",
        json={"resolucao": "excecao"},
        headers=_h(),
    )
    assert sem_prazo.status_code == 422  # excecao com prazo (§8-M9)
    assert "prazo" in sem_prazo.json()["detail"].lower()

    resolucoes = ["adopt", "enforce", "excecao", "excecao", "adopt"]
    for check, resolucao in zip(checks, resolucoes, strict=True):
        corpo = {"resolucao": resolucao, "justificativa": "ajuste combinado no War Room"}
        if resolucao == "excecao":
            corpo["prazo_ate"] = "2026-08-11T12:00:00+00:00"
        resolvido = client.post(f"/api/v1/drift/{check['id']}/resolver", json=corpo, headers=_h())
        assert resolvido.status_code == 200, resolvido.text
        assert resolvido.json()["resolucao"] == resolucao
        assert resolvido.json()["diff"]["resolucao_meta"]["por"]

    repo = app_sfmc.state.repositorio_os
    automatica = next(p for p in repo.listar_pendencias(os_id) if p.origem == "drift:prod")
    assert automatica.status == "resolvida"  # sem drift pendente ⇒ resolvida
    assert repo.listar_eventos(os_id=os_id, tipo="drift.resolved")

    de_novo = client.post(
        f"/api/v1/drift/{checks[0]['id']}/resolver", json={"resolucao": "adopt"}, headers=_h()
    )
    assert de_novo.status_code == 409  # já resolvido


def test_M9_preflight_fail_bloqueia_apply(client: TestClient, app_sfmc: FastAPI, mock_sfmc) -> None:  # type: ignore[no-untyped-def]
    """§8-M9: pré-voo com FAIL (`vermelho`) bloqueia o apply (aqui: last-mile do Guard
    reprova SQL sem 'procon'); corrigido o SQL, novo pré-voo libera. Apply em PROD sem
    pré-voo prévio → 409 (§5.4.4)."""
    os_id, snapshot = _preparar_snapshot_aprovado(client, app_sfmc)
    base = f"/api/v1/snapshots/{snapshot['id']}"
    repo = app_sfmc.state.repositorio_os
    segmento = repo.listar_segmentos(os_id)[-1]
    segmento.sql_publico = SQL_CONFORME.replace("'procon',", "")  # adultera: perde 1 lista

    # prod sem pré-voo executado → 409 (§5.4.4: "apply em prod exige ... pre-flight verde")
    assert client.post(f"{base}/plan?ambiente=prod", headers=_h()).status_code == 201
    sem_prevoo = client.post(f"{base}/apply?ambiente=prod", headers=_h())
    assert sem_prevoo.status_code == 409
    assert "pré-voo" in sem_prevoo.json()["detail"]

    vermelho = client.post(f"/api/v1/preflight/{snapshot['id']}?ambiente=prod", headers=_h())
    assert vermelho.status_code == 201, vermelho.text
    corpo = vermelho.json()
    assert corpo["resultado"] == "vermelho"
    last_mile = next(i for i in corpo["itens"] if i["item"] == "listas_last_mile")
    assert last_mile["status"] == "fail"
    assert last_mile["evidencia"]["listas_faltantes"] == ["procon"]
    assert repo.listar_eventos(os_id=os_id, tipo="gate.blocked")

    bloqueado = client.post(f"{base}/apply?ambiente=prod", headers=_h())
    assert bloqueado.status_code == 409  # fail bloqueia apply (§8-M9)
    assert bloqueado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "vermelho" in bloqueado.json()["detail"].lower()

    segmento.sql_publico = SQL_CONFORME  # corrige → re-varredura passa
    verde = client.post(f"/api/v1/preflight/{snapshot['id']}?ambiente=prod", headers=_h())
    assert verde.json()["resultado"] in ("verde", "amarelo")
    liberado = client.post(f"{base}/apply?ambiente=prod", headers=_h())
    assert liberado.status_code == 201 and liberado.json()["estado"] == "ok"


def test_M9_preflight_bateria_com_evidencia(
    client: TestClient, app_sfmc: FastAPI, mock_sfmc
) -> None:  # type: ignore[no-untyped-def]
    """§8-M9: a bateria cobre os 8 itens com evidência. Antes do apply: DEs/seed
    dry-run ⇒ warn (apply criará as DEs) e amarelo NÃO bloqueia; depois do apply tudo
    materializado ⇒ verde; last-mile fica gravado no certificado (§4.1 `last_mile`)."""
    os_id, snapshot = _preparar_snapshot_aprovado(client, app_sfmc)
    base = f"/api/v1/snapshots/{snapshot['id']}"
    assert client.post(f"{base}/plan?ambiente={AMBIENTE}", headers=_h()).status_code == 201

    antes = client.post(
        f"/api/v1/preflight/{snapshot['id']}?ambiente={AMBIENTE}", headers=_h()
    ).json()
    assert [i["item"] for i in antes["itens"]] == ITENS_PREFLIGHT
    por_item = {i["item"]: i for i in antes["itens"]}
    assert antes["resultado"] == "amarelo"
    assert por_item["des_schema"]["status"] == "warn"  # DEs ainda não materializadas
    assert por_item["seed_dry_run"]["status"] == "warn"
    assert por_item["frescor_hybris"]["status"] == "pass"  # Hybris D-1 (fixture 24h)
    assert por_item["frescor_hybris"]["evidencia"]["atualizado_ha_horas"] == 24
    assert por_item["opt_in"]["status"] == "pass"
    assert por_item["listas_last_mile"]["status"] == "pass"
    assert por_item["lint_ampscript"]["status"] == "pass"
    assert por_item["limites_sfmc"]["status"] == "pass"
    # C04: nada aplicado ⇒ NADA a comparar — `n/a` com detalhe, jamais `pass`
    assert por_item["drift_zero"]["status"] == "n/a"
    assert por_item["drift_zero"]["evidencia"]["verificados"] == 0
    assert "não há estado real para comparar" in por_item["drift_zero"]["evidencia"]["detalhe"]

    # last-mile registrado no certificado (§4.1: re-varredura no disparo)
    repo = app_sfmc.state.repositorio_os
    certificado = repo.listar_certificados(os_id)[-1]
    assert certificado.last_mile is not None
    assert certificado.last_mile["status"] == "pass"

    # amarelo NÃO bloqueia (fail bloqueia): apply em homolog segue
    assert client.post(f"{base}/apply?ambiente={AMBIENTE}", headers=_h()).status_code == 201

    depois = client.post(
        f"/api/v1/preflight/{snapshot['id']}?ambiente={AMBIENTE}", headers=_h()
    ).json()
    assert depois["resultado"] == "verde"
    por_item = {i["item"]: i for i in depois["itens"]}
    assert por_item["des_schema"]["status"] == "pass"
    assert por_item["seed_dry_run"]["status"] == "pass"
    assert por_item["drift_zero"]["status"] == "pass"
    assert por_item["drift_zero"]["evidencia"]["verificados"] == RECURSOS_V1
    seed = por_item["seed_dry_run"]["evidencia"]["entradas"][0]["seed"]
    assert seed["SubscriberKey"].startswith("seed-jrn-")  # sintética — nunca PII (§10.2)

    # C04 (UAT #3): a MESMA bateria em prod, onde nada desta OS foi publicado. Todo o
    # resto passa (as DEs existem no mock), mas não há recurso para comparar: drift vira
    # `n/a` com detalhe — e um item não verificado NÃO deixa a bateria verde sozinho.
    prod = client.post(f"/api/v1/preflight/{snapshot['id']}?ambiente=prod", headers=_h()).json()
    por_item = {i["item"]: i for i in prod["itens"]}
    assert por_item["drift_zero"]["status"] == "n/a"
    assert por_item["drift_zero"]["evidencia"] == {
        "ambiente": "prod",
        "verificados": 0,
        "com_drift": [],
        "detalhe": por_item["drift_zero"]["evidencia"]["detalhe"],
    }
    assert "não há estado real para comparar" in por_item["drift_zero"]["evidencia"]["detalhe"]
    assert {i["status"] for i in prod["itens"]} == {"pass", "n/a"}  # zero warn, zero fail
    assert prod["resultado"] == "amarelo"  # n/a não é aprovação (antes: verde)
    # `n/a` NÃO bloqueia — quem bloqueia é `fail`/vermelho (§5.4.4)
    assert client.post(f"{base}/plan?ambiente=prod", headers=_h()).status_code == 201
    assert client.post(f"{base}/apply?ambiente=prod", headers=_h()).status_code == 201
