"""Aceites do módulo M5 · Audiência + Guard + Data Cloud (SDD §8-M5) — IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker e SEM REDE: LLM = adapter fake (`app.state.llm` —
§1.3.5), Data Cloud = adapter de fixtures (mocks/seeds/datacloud_segmentos.json §11.2),
read model = fixtures (mocks/seeds/read_model_audiencia.json §11), Langfuse no-op
(§10.8). O Guard é código puro (agents/guard — zero LLM): A1 exercita-o também como
unit com SQL adulterado.
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.llm.fake import LLMFake
from agents.guard import elegibilidade as guard
from app.errors import PROBLEM_CONTENT_TYPE
from domain.audiencia.erros import CertificadoExpirado, CertificadoReprovado
from domain.audiencia.modelos import SETE_LISTAS

TENANT = "torre-movel"

SQL_CONFORME = (
    "SELECT c.contato_hash FROM hybris_base_clientes c\n"
    "WHERE c.plano = 'pos_pago'\n"
    "  AND (c.opt_in_email OR c.opt_in_sms OR c.opt_in_push OR c.opt_in_whatsapp)\n"
    "  AND NOT EXISTS (SELECT 1 FROM lista_supressao s\n"
    "    WHERE s.contato_hash = c.contato_hash AND s.lista IN\n"
    "      ('blacklist','fraude','nao_perturbe','optout','procon',"
    "'inadimplente','reprovado_credito'))"
)
# SQL ADULTERADO (A1): alguém removeu procon e inadimplente do WHERE
SQL_ADULTERADO = SQL_CONFORME.replace("'procon',", "").replace("'inadimplente',", "")
# SQL QUE MIRA OS SUPRIMIDOS (UAT5 · achado 1): cita as 7 listas e o opt-in, mas com o
# filtro invertido — EXISTS no lugar de NOT EXISTS e `opt_in = 0`. Enquanto a varredura
# foi por substring, ISTO tirava certificado 201. Evasões em detalhe: tests/unit/
# test_guard_evasoes.py.
SQL_MIRA_SUPRIMIDOS = (
    "SELECT c.contato_hash FROM hybris_base_clientes c WHERE "
    + " AND ".join(
        f"EXISTS (SELECT 1 FROM lista_supressao s WHERE s.contato_hash = c.contato_hash "
        f"AND s.lista = '{lista}')"
        for lista in SETE_LISTAS
    )
    + " AND c.opt_in_email = 0"
)


def _h(token: str = "dev-analista") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _criar_os(client: TestClient) -> dict:
    resposta = client.post(
        "/api/v1/os",
        json={
            "nome": "Upgrade Pós-Pago 5G",
            "tshirt": "G",
            "briefing": {"publico": {"valor": "Pós-pago sem 5G", "inferido": False}},
        },
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _resposta_engineer(sql: str) -> str:
    """Saída enlatada do LLM no contrato JSON do SKILL.md do engineer (§7.1/§7.2)."""
    return json.dumps(
        {
            "sql": sql,
            "explicacao": [
                {
                    "clausula": "NOT EXISTS (... lista_supressao ...)",
                    "explicacao": "As 7 listas de exclusão são obrigatórias no WHERE.",
                }
            ],
            "evidencias": ["dicionario_dados: lista_supressao(lista, contato_hash) — §4.1"],
        },
        ensure_ascii=False,
    )


def _gerar_segmento(client: TestClient, app: FastAPI, sql: str) -> dict:
    app.state.llm = LLMFake(resposta=_resposta_engineer(sql))
    os_ = _criar_os(client)
    resposta = client.post(
        f"/api/v1/os/{os_['id']}/segmento/gerar-sql",
        json={"instrucoes": "Pós-pago elegível a upgrade 5G, todos os canais com opt-in."},
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_M5_A1(client: TestClient, app: FastAPI) -> None:
    """A1: SQL sem as 7 listas no WHERE → guard reprova a certificação (unit com SQL
    adulterado + caminho API). Guard é CÓDIGO PURO — zero LLM (§7.2/§10.6)."""
    # --- unit: o guard determinístico com SQL adulterado ---
    assert guard.listas_ausentes_no_where(SQL_CONFORME) == []
    assert guard.opt_in_ausente_no_where(SQL_CONFORME) is False
    assert guard.listas_ausentes_no_where(SQL_ADULTERADO) == ["procon", "inadimplente"]
    with pytest.raises(CertificadoReprovado) as exc:
        guard.validar_sql_de_segmentacao(SQL_ADULTERADO)
    assert exc.value.listas_faltantes == ["procon", "inadimplente"]
    # sem WHERE algum → todas as 7 faltam
    assert guard.listas_ausentes_no_where("SELECT contato_hash FROM base") == list(SETE_LISTAS)
    with pytest.raises(CertificadoReprovado):
        guard.validar_sql_de_segmentacao(None)

    # --- API: engineer gera SQL adulterado → certificação reprovada (422) ---
    gerado = _gerar_segmento(client, app, SQL_ADULTERADO)
    assert gerado["avisos"]  # pré-check do guard já avisa na prévia (§1.1.3)
    segmento_id = gerado["segmento"]["id"]
    reprovado = client.post(f"/api/v1/segmentos/{segmento_id}/certificar", headers=_h())
    assert reprovado.status_code == 422, reprovado.text
    assert reprovado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    corpo = reprovado.json()
    assert corpo["listas_faltantes"] == ["procon", "inadimplente"]
    assert any("procon" in p for p in corpo["problemas"])
    # outbox: gate.blocked do portão guard (§2.3)
    repo = app.state.repositorio_os
    bloqueios = repo.listar_eventos(tipo="gate.blocked")
    assert bloqueios and bloqueios[-1].payload["portao"] == "guard"

    # --- SQL conforme → certifica (201) e registra ledger via_ai do engineer ---
    gerado = _gerar_segmento(client, app, SQL_CONFORME)
    assert gerado["avisos"] == []
    assert gerado["via_ai"] is True and gerado["evidencias"]
    fake = app.state.llm
    assert [c["perfil"] for c in fake.chamadas] == ["120b"]  # roster §7.2: engineer é 120b
    prompt = json.dumps(fake.chamadas[0]["mensagens"], ensure_ascii=False)
    assert "contato_hash" not in prompt or "@" not in prompt  # nunca PII em prompt (§10.2)
    invocacoes = [i for i in repo.listar_invocacoes(TENANT) if i.skill_versao == "1.0"]
    assert invocacoes and invocacoes[-1].output["sql"] == SQL_CONFORME
    certificado = client.post(
        f"/api/v1/segmentos/{gerado['segmento']['id']}/certificar", headers=_h()
    )
    assert certificado.status_code == 201, certificado.text

    # RBAC (§8-M0): solicitante não gera SQL nem certifica
    negado = client.post(
        f"/api/v1/segmentos/{gerado['segmento']['id']}/certificar",
        headers=_h("dev-solicitante"),
    )
    assert negado.status_code == 403


def test_M5_A1_sql_que_mira_os_suprimidos_nao_certifica(client: TestClient, app: FastAPI) -> None:
    """A1 (UAT5 · achado 1): o Guard varre ESTRUTURA, não substring.

    O SQL cita as 7 listas e o opt-in — e mira exatamente blacklist/Procon/optout.
    Tem de reprovar (422), avisar já na prévia e registrar `gate.blocked`."""
    gerado = _gerar_segmento(client, app, SQL_MIRA_SUPRIMIDOS)
    assert gerado["avisos"]  # pré-check do guard já denuncia na prévia (§1.1.3)
    reprovado = client.post(
        f"/api/v1/segmentos/{gerado['segmento']['id']}/certificar", headers=_h()
    )
    assert reprovado.status_code == 422, reprovado.text
    corpo = reprovado.json()
    assert corpo["listas_faltantes"] == list(SETE_LISTAS)  # nenhuma lista suprime nada
    problemas = " ".join(corpo["problemas"]).lower()
    assert "exists" in problemas and "opt-in" in problemas
    bloqueios = app.state.repositorio_os.listar_eventos(tipo="gate.blocked")
    assert bloqueios and bloqueios[-1].payload["portao"] == "guard"


def test_M5_A2(client: TestClient, app: FastAPI) -> None:
    """A2: volume de abordagem — soma por canal ≤ líquido; percentuais SOBRE o líquido;
    colisões vêm do governor (read model/fixture). Vale para o Estúdio SQL (recontar)
    e para o relatório Data Cloud (T5a)."""
    # --- Estúdio SQL: dry-run no read model (fixtures §11) ---
    gerado = _gerar_segmento(client, app, SQL_CONFORME)
    recontado = client.post(f"/api/v1/segmentos/{gerado['segmento']['id']}/recontar", headers=_h())
    assert recontado.status_code == 200, recontado.text
    segmento = recontado.json()
    assert segmento["contagem_bruta"] == 1_203_450
    assert segmento["contagem_liquida"] == 888_620  # bruto - 7 listas - sem opt-in
    assert segmento["waterfall"][-1]["restante"] == segmento["contagem_liquida"]
    listas_no_waterfall = [e["etapa"] for e in segmento["waterfall"][:7]]
    assert listas_no_waterfall == list(SETE_LISTAS)
    liquido = segmento["contagem_liquida"]
    volume = segmento["volume_abordagem"]
    assert set(volume) == {"email", "sms", "push", "whatsapp"}
    for canal, dados in volume.items():
        assert 0 <= dados["n"] <= liquido, canal  # nunca acima do líquido
        assert dados["pct"] == round(100.0 * dados["n"] / liquido, 1), canal  # pct SOBRE líquido
    # governor (colisões) já descontado: email = 705000 - 22000 - 0 - 18400
    assert volume["email"]["n"] == 664_600

    # --- Data Cloud (T5a): relatório com funil, sobreposição e colisões do governor ---
    relatorio = client.get("/api/v1/datacloud/segmentos/DC-SEG-002/relatorio", headers=_h())
    assert relatorio.status_code == 200, relatorio.text
    corpo = relatorio.json()
    assert corpo["funil"] == {"bruto": 847_312, "elegivel": 812_400, "liquido": 590_880}
    assert corpo["waterfall"][0]["etapa"] == "criterios"  # bruto → elegível
    assert corpo["waterfall"][-1]["restante"] == corpo["funil"]["liquido"]
    assert corpo["sobreposicao"] == {"DC-SEG-001": 121_040, "DC-SEG-003": 38_900}
    liquido_dc = corpo["funil"]["liquido"]
    for canal, dados in corpo["volume_abordagem"].items():
        assert 0 <= dados["n"] <= liquido_dc, canal
        assert dados["pct"] == round(100.0 * dados["n"] / liquido_dc, 1), canal
    # A2: colisões vêm do governor (fixture do read model) — não são inventadas
    assert corpo["colisoes"] == {"email": 12_800, "sms": 4_100, "push": 7_300, "whatsapp": 1_700}

    # usar o segmento DC numa OS: vira `segmento` origem data_cloud com lineage
    os_ = _criar_os(client)
    usado = client.post(
        "/api/v1/datacloud/segmentos/DC-SEG-002/usar",
        json={"os_id": os_["id"]},
        headers=_h(),
    )
    assert usado.status_code == 201, usado.text
    segmento_dc = usado.json()
    assert segmento_dc["origem"] == "data_cloud"
    assert segmento_dc["dc_segment_id"] == "DC-SEG-002"
    assert segmento_dc["contagem_liquida"] == 590_880
    assert segmento_dc["volume_abordagem"]["email"]["n"] <= 590_880

    # holdout: abaixo do mínimo da política (10% — §11.4) → 422; válido → grava
    segmento_id = segmento_dc["id"]
    invalido = client.put(
        f"/api/v1/segmentos/{segmento_id}/holdout", json={"holdout_pct": 5.0}, headers=_h()
    )
    assert invalido.status_code == 422
    valido = client.put(
        f"/api/v1/segmentos/{segmento_id}/holdout", json={"holdout_pct": 15.0}, headers=_h()
    )
    assert valido.status_code == 200
    assert valido.json()["holdout_pct"] == 15.0

    # segmento inexistente no Data Cloud → 404 problem+json
    sumido = client.get("/api/v1/datacloud/segmentos/DC-SEG-999/relatorio", headers=_h())
    assert sumido.status_code == 404


def test_M5_A3(client: TestClient, app: FastAPI) -> None:
    """A3: certificado tem hash e validade; expirado → publish (M8) RECUSARÁ via o
    helper determinístico `exigir_certificado_vigente` (deixado pronto no guard)."""
    gerado = _gerar_segmento(client, app, SQL_CONFORME)
    resposta = client.post(f"/api/v1/segmentos/{gerado['segmento']['id']}/certificar", headers=_h())
    assert resposta.status_code == 201, resposta.text
    certificado = resposta.json()

    # hash sha256 hex (64) + suprimidos por lista (as 7) + líquido coerente
    assert len(certificado["hash"]) == 64 and int(certificado["hash"], 16) >= 0
    assert set(certificado["suprimidos"]) == set(SETE_LISTAS)
    assert certificado["liquido"] == 888_620
    emitido_em = datetime.fromisoformat(certificado["emitido_em"])
    valido_ate = datetime.fromisoformat(certificado["valido_ate"])
    assert valido_ate - emitido_em == timedelta(hours=guard.VALIDADE_HORAS_CERTIFICADO)
    assert certificado["last_mile"] is None  # re-varredura só no disparo (M9/M10)

    # persistido em `certificado_elegibilidade` (§4.1) + evento certificado.emitido
    repo = app.state.repositorio_os
    os_id = uuid.UUID(gerado["segmento"]["os_id"])
    assert [c.hash for c in repo.listar_certificados(os_id)] == [certificado["hash"]]
    assert repo.listar_eventos(os_id=os_id, tipo="certificado.emitido")

    # helper para o publish (M8/M9): certificado expirado é RECUSADO
    ontem = datetime(2026, 8, 3, 6, 0, tzinfo=UTC)
    expirado = guard.emitir_certificado(
        os_id=os_id,
        segmento_id=uuid.UUID(gerado["segmento"]["id"]),
        sql_publico=SQL_CONFORME,
        suprimidos={lista: 1 for lista in SETE_LISTAS},
        liquido=100,
        agora=ontem,
    )
    agora = ontem + timedelta(hours=guard.VALIDADE_HORAS_CERTIFICADO, minutes=1)
    assert guard.certificado_vigente(expirado, ontem + timedelta(hours=1)) is True
    assert guard.certificado_vigente(expirado, agora) is False
    with pytest.raises(CertificadoExpirado):
        guard.exigir_certificado_vigente(expirado, agora)


def test_M5_A4(client: TestClient, app: FastAPI) -> None:
    """A4: contagens exibem frescor POR FONTE — Hybris D-1 (24h) nas fixtures — na
    recontagem do Estúdio SQL, no relatório Data Cloud e no cache da listagem T5a."""
    gerado = _gerar_segmento(client, app, SQL_CONFORME)
    recontado = client.post(f"/api/v1/segmentos/{gerado['segmento']['id']}/recontar", headers=_h())
    assert recontado.status_code == 200
    frescor = recontado.json()["frescor"]
    assert set(frescor) >= {"hybris_base_clientes", "telemetria_ens"}
    agora = datetime.now(UTC)
    idade_hybris = agora - datetime.fromisoformat(frescor["hybris_base_clientes"])
    assert abs(idade_hybris - timedelta(hours=24)) < timedelta(minutes=5)  # Hybris D-1

    # relatório Data Cloud: frescor por fonte (data_cloud 12h; hybris D-1)
    relatorio = client.get("/api/v1/datacloud/segmentos/DC-SEG-002/relatorio", headers=_h())
    frescor_dc = relatorio.json()["frescor"]
    idade_dc = agora - datetime.fromisoformat(frescor_dc["data_cloud"])
    idade_hybris_dc = agora - datetime.fromisoformat(frescor_dc["hybris_base_clientes"])
    assert abs(idade_dc - timedelta(hours=12)) < timedelta(minutes=5)
    assert abs(idade_hybris_dc - timedelta(hours=24)) < timedelta(minutes=5)

    # listagem T5a: cache com frescor (republicado_em do DC + atualizado_em da consulta)
    listagem = client.get("/api/v1/datacloud/segmentos", headers=_h())
    assert listagem.status_code == 200
    segmentos = listagem.json()
    assert {s["id"] for s in segmentos} == {"DC-SEG-001", "DC-SEG-002", "DC-SEG-003", "DC-SEG-004"}
    for entrada in segmentos:
        assert entrada["republicado_em"] is not None and entrada["atualizado_em"] is not None
    # cache persistido em `dc_segment_cache` (§4.1 — consulta, não cópia)
    assert len(app.state.repositorio_os.listar_dc_cache(TENANT)) == 4


def test_M5_guard_nao_depende_de_llm(client: TestClient, app: FastAPI) -> None:
    """§10.6: caminho crítico (Guard) NUNCA depende de LLM — certificação funciona com o
    hub fora; já o engineer (gerar-sql) responde 503 degraded."""
    gerado = _gerar_segmento(client, app, SQL_CONFORME)  # LLM ainda disponível
    app.state.llm = LLMFake(disponivel=False)  # hub caiu (§10.6)

    os_ = _criar_os(client)
    degradado = client.post(
        f"/api/v1/os/{os_['id']}/segmento/gerar-sql",
        json={"instrucoes": "qualquer"},
        headers=_h(),
    )
    assert degradado.status_code == 503
    assert degradado.json()["modo"] == "degraded"

    certificado = client.post(
        f"/api/v1/segmentos/{gerado['segmento']['id']}/certificar", headers=_h()
    )
    assert certificado.status_code == 201, certificado.text  # guard é código puro (§7.2)
