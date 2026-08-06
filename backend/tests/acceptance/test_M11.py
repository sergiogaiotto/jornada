"""Aceites do módulo M11 · Otimização/Retro/Calibração T15 (SDD §8-M11, §4.1
`experimento`/`calibracao_prior` + tabelas auxiliares `proposta_otimizacao`/
`aprendizado` — migração 0009) — IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker e SEM REDE (§1.3.5): o optimize usa LLMFake com
resposta enlatada (o hub real jamais é chamado); apuração, aprovação, rejeição,
clone e calibração são 100% determinísticos — ZERO LLM (§10.6). Telemetria é
semeada direto no repositório em memória (`app.state.repositorio_os`, padrão M8/M10)
com hashes sha256 SINTÉTICOS — nunca PII (§10.2).

Fluxo: OS → jornada simulada (+previsto/snapshot) → telemetria → apurar (anti-peeking
425 → lift IC95) → propostas do optimize (diff+impacto pré-simulado, ranking) →
aprovar/rejeitar → calibração (backtest obrigatório) → clone com aprendizados.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.llm.fake import LLMFake
from app.errors import PROBLEM_CONTENT_TYPE
from domain.audiencia.modelos import Segmento
from domain.experimento.modelos import Experimento
from domain.jornada.canonico import hash_jgc
from domain.jornada.modelos import JornadaVersao
from domain.lancamento.modelos import TelemetryEvent

TENANT = "torre-movel"
VOLUME_LIQUIDO = 50_000
PARAMS = {"seed": 42, "runs": 80, "n_personas": 500}
EXPERIMENTO_14D = {"holdout_pct": 10.0, "n_minimo": 100, "mde_pp": 5.0, "janela_dias": 14}


def _h(token: str = "dev-analista") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _hash(i: int) -> str:
    """contato_hash SINTÉTICO (sha256 hex — nunca PII §10.2)."""
    return hashlib.sha256(f"contato-m11-{i:05d}".encode()).hexdigest()


def _grafo(os_codigo: str) -> dict[str, Any]:
    """JGC §5 válido (mesmo shape do M8/M10): entrada → split 90/10 (holdout) → wait
    → e-mail → goal; braço holdout → exit."""
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


def _semear_jornada(
    client: TestClient, app: FastAPI, *, experimento: dict[str, Any] | None = None
) -> tuple[uuid.UUID, uuid.UUID]:
    """OS via API + segmento recontado/jornada (e experimento TRAVADO §4.1) direto no
    repositório em memória (padrão M8)."""
    resposta = client.post(
        "/api/v1/os", json={"nome": "Upgrade Pós-Pago 5G", "tshirt": "G"}, headers=_h()
    )
    assert resposta.status_code == 201, resposta.text
    os_ = resposta.json()
    os_id = uuid.UUID(os_["id"])
    repo = app.state.repositorio_os
    repo.adicionar_segmento(
        Segmento(
            id=uuid.uuid4(),
            os_id=os_id,
            origem="estudio_sql",
            contagem_bruta=61_000,
            contagem_liquida=VOLUME_LIQUIDO,
            volume_abordagem={"email": {"n": VOLUME_LIQUIDO, "pct": 100.0}},
        )
    )
    if experimento is not None:
        repo.adicionar_experimento(
            Experimento(
                id=uuid.uuid4(),
                os_id=os_id,
                metricas={"primaria": "conversao"},
                travado_em=datetime.now(UTC),
                **experimento,
            )
        )
    jgc = _grafo(os_["codigo"])
    jornada = JornadaVersao(
        id=uuid.uuid4(),
        os_id=os_id,
        versao=repo.proxima_versao(os_id),
        grafo=jgc,
        hash=hash_jgc(jgc),
    )
    repo.adicionar_jornada(jornada)
    return jornada.id, os_id


def _semear_telemetria(
    app: FastAPI,
    os_id: uuid.UUID,
    *,
    n_sents: int,
    conv_tratado: int,
    conv_holdout: int,
    inicio: datetime,
) -> None:
    """Telemetria ENS sintética (§4.1): `sent` distintos + `conversion` por grupo
    (payload.grupo — mesmo recorte do monitor M10/motor §6)."""
    repo = app.state.repositorio_os
    for i in range(n_sents):
        repo.adicionar_telemetria(
            TelemetryEvent(
                tenant_id=TENANT,
                os_id=os_id,
                no_jgc="n4",
                canal="email",
                tipo="sent",
                contato_hash=_hash(i),
                fonte="ens",
                ts=inicio + timedelta(minutes=i % 240),
            )
        )
    for i in range(conv_tratado):
        repo.adicionar_telemetria(
            TelemetryEvent(
                tenant_id=TENANT,
                os_id=os_id,
                no_jgc="n5",
                canal="email",
                tipo="conversion",
                contato_hash=_hash(i),
                fonte="ens",
                ts=inicio + timedelta(hours=6),
                payload={"grupo": "tratado"},
            )
        )
    for i in range(conv_holdout):
        repo.adicionar_telemetria(
            TelemetryEvent(
                tenant_id=TENANT,
                os_id=os_id,
                no_jgc=None,
                canal=None,
                tipo="conversion",
                contato_hash=_hash(10_000 + i),
                fonte="ens",
                ts=inicio + timedelta(hours=7),
                payload={"grupo": "holdout"},
            )
        )


def _resposta_optimize(os_codigo: str) -> str:
    """Resposta enlatada do optimize (§7.2): 2 grafos candidatos VÁLIDOS (§5.3) com
    mudanças pequenas — espera menor (n3) e throttle menor (n4)."""
    espera = _grafo(os_codigo)
    next(n for n in espera["nodes"] if n["id"] == "n3")["data"]["duracao"] = "PT2H"
    throttle = _grafo(os_codigo)
    next(n for n in throttle["nodes"] if n["id"] == "n4")["data"]["throttlePorHora"] = 20_000
    return json.dumps(
        {
            "propostas": [
                {
                    "titulo": "Reduzir espera para 2h",
                    "motivacao": "Oferta mais quente na janela de intenção",
                    "grafo": espera,
                },
                {
                    "titulo": "Reduzir throttle do e-mail",
                    "motivacao": "Menos pressão por hora, mesma cobertura",
                    "grafo": throttle,
                },
            ],
            "resumo": "Duas otimizações de cadência com baixo esforço.",
        },
        ensure_ascii=False,
    )


def _simular_e_congelar(client: TestClient, jornada_id: uuid.UUID) -> None:
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h()).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/congelar-previsto", headers=_h()).status_code
        == 200
    )


# --------------------------------------------------------------------- Aceites §8-M11


class _RelogioFixo:
    """Dublê do ClockPort (§2.1) — o anti-peeking é função do RELÓGIO injetado,
    nunca do wall time; o teste avança o tempo manipulando a porta."""

    def __init__(self, instante: datetime) -> None:
        self._instante = instante

    def agora(self) -> datetime:
        return self._instante


def test_M11_A1(client: TestClient, app: FastAPI) -> None:
    """A1: apuração antes da janela → 425 Too Early (anti-peeking: NENHUM lift é
    calculado; a janela começa na primeira exposição e dura `janela_dias`).
    Prova pelo ClockPort: com a MESMA telemetria, avançar o relógio injetado para
    além do fim da janela vira 425 → 200."""
    _, os_id = _semear_jornada(client, app, experimento=EXPERIMENTO_14D)
    repo = app.state.repositorio_os
    experimento = repo.experimento_da_os(os_id)

    # sem NENHUMA exposição: janela nem começou → 425
    sem_exposicao = client.post(f"/api/v1/experimentos/{experimento.id}/apurar", headers=_h())
    assert sem_exposicao.status_code == 425, sem_exposicao.text
    assert sem_exposicao.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert experimento.estado == "pre_registrado"  # peeking não mutila o pré-registro

    # exposição RECENTE: janela de 14 dias ainda correndo → 425 com fim_janela
    _semear_telemetria(
        app,
        os_id,
        n_sents=50,
        conv_tratado=5,
        conv_holdout=0,
        inicio=datetime.now(UTC) - timedelta(hours=2),
    )
    cedo = client.post(f"/api/v1/experimentos/{experimento.id}/apurar", headers=_h())
    assert cedo.status_code == 425, cedo.text
    corpo = cedo.json()
    assert corpo["title"] == "Too Early"
    assert corpo["fim_janela"]  # anti-peeking informa QUANDO poderá apurar
    assert "425" not in (experimento.resultado or {})  # nada foi calculado/persistido
    assert experimento.resultado is None
    assert experimento.estado == "em_apuracao"  # janela correndo (§4.1)

    # manipulação do CLOCK PORT (§2.1): mesma telemetria, relógio 1s além do fim da
    # janela informado no 425 → apuração liberada (o portão é o relógio, não o dado)
    fim_janela = datetime.fromisoformat(corpo["fim_janela"])
    app.state.relogio = _RelogioFixo(fim_janela - timedelta(seconds=1))
    ainda_cedo = client.post(f"/api/v1/experimentos/{experimento.id}/apurar", headers=_h())
    assert ainda_cedo.status_code == 425  # 1s ANTES do fim: segue bloqueado
    app.state.relogio = _RelogioFixo(fim_janela + timedelta(seconds=1))
    liberada = client.post(f"/api/v1/experimentos/{experimento.id}/apurar", headers=_h())
    assert liberada.status_code == 200, liberada.text
    assert experimento.estado == "apurado"
    assert experimento.resultado is not None  # agora sim: lift calculado e persistido


def test_M11_A2(client: TestClient, app: FastAPI) -> None:
    """A2: `significativo=true` SÓ com IC95 excluindo zero; lift em pp com IC e
    resultado imutável (`{lift, ic95, significativo, roas}` §4.1)."""
    inicio = datetime.now(UTC) - timedelta(days=20)  # janela de 14d já encerrada

    # sinal FORTE: 40/400 no tratado × 0 no holdout → IC exclui zero
    _, os_a = _semear_jornada(client, app, experimento=EXPERIMENTO_14D)
    repo = app.state.repositorio_os
    experimento_a = repo.experimento_da_os(os_a)
    _semear_telemetria(app, os_a, n_sents=400, conv_tratado=40, conv_holdout=0, inicio=inicio)
    forte = client.post(f"/api/v1/experimentos/{experimento_a.id}/apurar", headers=_h())
    assert forte.status_code == 200, forte.text
    resultado = forte.json()["resultado"]
    assert set(resultado) >= {"lift", "ic95", "significativo", "roas"}  # forma §4.1
    assert resultado["significativo"] is True
    assert resultado["ic95"][0] > 0  # IC INTEIRO acima de zero
    assert resultado["lift"] > 0
    assert resultado["roas"] and resultado["roas"] > 0  # 40 × ticket ÷ (400 × tarifa)
    assert experimento_a.estado == "apurado"

    # apuração é ÚNICA (anti-p-hacking): re-apurar → 409
    de_novo = client.post(f"/api/v1/experimentos/{experimento_a.id}/apurar", headers=_h())
    assert de_novo.status_code == 409
    assert de_novo.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    # sinal FRACO: 4/400 × 1 no holdout (~2,3%) → IC contém zero ⇒ significativo=false
    _, os_b = _semear_jornada(client, app, experimento=EXPERIMENTO_14D)
    experimento_b = repo.experimento_da_os(os_b)
    _semear_telemetria(app, os_b, n_sents=400, conv_tratado=4, conv_holdout=1, inicio=inicio)
    fraco = client.post(f"/api/v1/experimentos/{experimento_b.id}/apurar", headers=_h())
    assert fraco.status_code == 200, fraco.text
    resultado_b = fraco.json()["resultado"]
    assert resultado_b["significativo"] is False
    assert resultado_b["ic95"][0] < 0 < resultado_b["ic95"][1]  # IC contém zero


def test_M11_A3(client: TestClient, app: FastAPI) -> None:
    """A3: clone herda aprendizados ACEITOS (aprovação) e PROMOVIDOS (experimento
    significativo — que também entram na base RAG `resultados`, stub de ingestão) +
    priors NOVOS (calibração publicada com backtest); o SINAL (rejeição) não é
    herdado."""
    jornada_id, os_id = _semear_jornada(client, app, experimento=EXPERIMENTO_14D)
    repo = app.state.repositorio_os
    codigo_origem = client.get(f"/api/v1/os/{os_id}", headers=_h()).json()["codigo"]
    _simular_e_congelar(client, jornada_id)
    snapshot = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=_h())
    assert snapshot.status_code == 201, snapshot.text  # Previsto congelado p/ calibração

    # ------- experimento apurado (após a janela) e SIGNIFICATIVO → promovido + RAG
    _semear_telemetria(
        app,
        os_id,
        n_sents=400,
        conv_tratado=40,
        conv_holdout=0,
        inicio=datetime.now(UTC) - timedelta(days=20),
    )
    experimento = repo.experimento_da_os(os_id)
    apurado = client.post(f"/api/v1/experimentos/{experimento.id}/apurar", headers=_h())
    assert apurado.status_code == 200, apurado.text
    assert apurado.json()["aprendizado"]["status"] == "promovido"
    evidencias = repo.listar_evidencias(TENANT, "resultados")  # A3: base RAG `resultados`
    assert len(evidencias) == 1
    assert "lift" in evidencias[0].chunk and evidencias[0].ref.startswith("aprendizado:")
    # A11: ingestão REAL — a promoção embeda melhor-esforço via EmbeddingPort (fake
    # em teste §1.3.5); vetor na dimensão do DDL §4.1 (EMBED_DIM=1024).
    assert evidencias[0].embedding is not None and len(evidencias[0].embedding) == 1024

    # ------- propostas do optimize: diff + impacto pré-simulado + ranking (§8-M11)
    app.state.llm = LLMFake(resposta=_resposta_optimize(codigo_origem))
    propostas = client.get(f"/api/v1/os/{os_id}/propostas", headers=_h())
    assert propostas.status_code == 200, propostas.text
    corpo = propostas.json()
    assert corpo["geradas_agora"] is True
    assert len(corpo["propostas"]) == 2
    scores = [p["score"] for p in corpo["propostas"]]
    assert scores == sorted(scores, reverse=True)  # ranqueadas lift×esforço×risco
    for proposta in corpo["propostas"]:
        assert proposta["diff"]["nodes"]["alterados"]  # diff JGC (§8-M11)
        assert set(proposta["impacto"]) >= {"base", "proposto", "deltas", "semaforo_proposto"}
        assert proposta["esforco"] >= 1 and proposta["risco"] >= 1.0
        assert proposta["estado"] == "proposta" and proposta["via_ai"] is True

    # ------- aprovar a 1ª: NOVA jornada_versao + mini-ciclo (aprovação EXPRESSA)
    primeira, segunda = corpo["propostas"][0], corpo["propostas"][1]
    aprovada = client.post(f"/api/v1/propostas/{primeira['id']}/aprovar", headers=_h())
    assert aprovada.status_code == 200, aprovada.text
    corpo_aprovada = aprovada.json()
    nova_versao = corpo_aprovada["jornada"]
    assert nova_versao["versao"] == 2 and nova_versao["estado"] == "rascunho"
    assert corpo_aprovada["mini_ciclo"]["aprovacao_expressa_necessaria"] is True
    jornada_nova = repo.obter_jornada(uuid.UUID(nova_versao["id"]))
    assert jornada_nova.simulacao is None and jornada_nova.previsto is None  # mini-ciclo M8
    assert jornada_nova.hash != repo.obter_jornada(jornada_id).hash  # snapshot novo obrigatório

    # ------- rejeitar a 2ª: motivo vira SINAL (não herdado no clone)
    rejeitada = client.post(
        f"/api/v1/propostas/{segunda['id']}/rejeitar",
        json={"motivo": "Custo por conversão piora no cenário proposto"},
        headers=_h(),
    )
    assert rejeitada.status_code == 200, rejeitada.text
    assert repo.listar_aprendizados(os_id=os_id, status="sinal")

    # ------- calibração: previsto congelado × realizado, backtest OBRIGATÓRIO
    # UAT5 achado 4: o realizado do experimento (40 conversões) é ordens de grandeza
    # menor que o Previsto congelado (P50 1625) — essa é a forma EXATA do bug da VPS e
    # agora REPROVA no piso de score (test_uat5_calibracao). Para exercitar o caminho
    # feliz da calibração, o realizado precisa ser plausível: 1260 conversões ENS a
    # mais (só `conversion`, nenhum `sent` novo — a apuração acima já é imutável).
    _semear_telemetria(
        app,
        os_id,
        n_sents=0,
        conv_tratado=1260,
        conv_holdout=0,
        inicio=datetime.now(UTC) - timedelta(days=20),
    )
    publicada = client.post("/api/v1/calibracao/publicar", headers=_h("dev-lider"))
    assert publicada.status_code == 201, publicada.text
    calibracao = publicada.json()
    assert calibracao["versao"] == 2  # v1 = PRIORS_DEFAULT em código (priors.py)
    assert calibracao["backtest"]["melhora"] is True
    assert calibracao["backtest"]["mape_novo"] <= calibracao["backtest"]["mape_antigo"]
    assert calibracao["priors"]["versao"] == 2
    assert calibracao["publicada_em"]

    # ------- clone: herda aceitos+promovidos + priors NOVOS (§8-M11-A3)
    clone = client.post(f"/api/v1/os/{os_id}/clonar-com-aprendizados", headers=_h())
    assert clone.status_code == 201, clone.text
    corpo_clone = clone.json()
    assert corpo_clone["os"]["codigo"] != codigo_origem
    assert corpo_clone["os"]["fase"] == "pensada"
    herdados = corpo_clone["herdados"]["aprendizados"]
    assert {a["status"] for a in herdados} == {"aceito", "promovido"}  # sinal NÃO herda
    assert {a["origem"] for a in herdados} == {"proposta_aprovada", "experimento"}
    assert corpo_clone["herdados"]["priors"]["versao"] == 2  # priors vigentes (novos)
    nova_os_id = uuid.UUID(corpo_clone["os"]["id"])
    copiados = repo.listar_aprendizados(os_id=nova_os_id)
    assert len(copiados) == len(herdados)
    assert all(a.herdado_de == os_id for a in copiados)  # lineage do clone
    assert repo.listar_eventos(os_id=nova_os_id, tipo="os.clonada_com_aprendizados")


# ------------------------------------------------- Contrato das demais rotas §8-M11


def test_M11_propostas_contratos(client: TestClient, app: FastAPI) -> None:
    """Propor exige régua simulada (409); hub fora degrada a LEITURA (nunca 503 num
    GET — §10.6); pendentes não regeneram; decisão é de uso único; motivo obrigatório."""
    jornada_id, os_id = _semear_jornada(client, app, experimento=EXPERIMENTO_14D)

    sem_simulacao = client.get(f"/api/v1/os/{os_id}/propostas", headers=_h())
    assert sem_simulacao.status_code == 409  # sem Ensaio Geral não há régua (§8-M11)
    assert sem_simulacao.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    _simular_e_congelar(client, jornada_id)

    app.state.llm = LLMFake(disponivel=False)  # hub fora: GET degrada, não quebra
    degradado = client.get(f"/api/v1/os/{os_id}/propostas", headers=_h())
    assert degradado.status_code == 200, degradado.text
    assert degradado.json()["degradado"] is True
    assert degradado.json()["propostas"] == []

    codigo = client.get(f"/api/v1/os/{os_id}", headers=_h()).json()["codigo"]
    fake = LLMFake(resposta=_resposta_optimize(codigo))
    app.state.llm = fake
    geradas = client.get(f"/api/v1/os/{os_id}/propostas", headers=_h())
    assert geradas.status_code == 200 and geradas.json()["geradas_agora"] is True

    # pendentes NÃO regeneram (decidir é humano §1.1.3): mesma lista, zero chamada nova
    repetida = client.get(f"/api/v1/os/{os_id}/propostas", headers=_h())
    assert repetida.json()["geradas_agora"] is False
    assert len(repetida.json()["propostas"]) == 2
    assert len(fake.chamadas) == 1

    primeira = geradas.json()["propostas"][0]["id"]
    assert client.post(f"/api/v1/propostas/{primeira}/aprovar", headers=_h()).status_code == 200
    de_novo = client.post(f"/api/v1/propostas/{primeira}/aprovar", headers=_h())
    assert de_novo.status_code == 409  # decisão de uso único
    assert de_novo.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    segunda = geradas.json()["propostas"][1]["id"]
    sem_motivo = client.post(
        f"/api/v1/propostas/{segunda}/rejeitar", json={"motivo": "   "}, headers=_h()
    )
    assert sem_motivo.status_code == 422  # motivo vira sinal — obrigatório (§8-M11)
    assert sem_motivo.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)


def test_M11_calibracao_exige_dados_e_experimento_inexistente_404(
    client: TestClient, app: FastAPI
) -> None:
    """Calibrar sem previsto×realizado no tenant → 409 (backtest não tem insumo);
    apurar experimento inexistente → 404 sem vazar existência.

    Publicar priors exige `lider` desde o UAT5 achado 4 (priors são do TENANT inteiro)."""
    sem_dados = client.post("/api/v1/calibracao/publicar", headers=_h("dev-lider"))
    assert sem_dados.status_code == 409
    assert sem_dados.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    fantasma = client.post(f"/api/v1/experimentos/{uuid.uuid4()}/apurar", headers=_h())
    assert fantasma.status_code == 404
