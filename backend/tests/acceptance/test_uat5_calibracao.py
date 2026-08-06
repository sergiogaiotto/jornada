"""Aceites do achado 4 da caçada UAT5 (docs/UAT5-2026-08-06-cacada.md) — calibração
de priors §8-M11 / §4.1 `calibracao_prior`.

O que estava quebrado na VPS: `POST /calibracao/publicar` com corpo VAZIO escalava os
priors VIGENTES pela razão (clamp 0,25) mas recalculava a razão sobre o P50 CONGELADO
— imune aos priors novos. Três cliques levaram `email.conversao` de 0,032 a 0,000125
e o backtest "obrigatório" aprovou as três (score 0.0, MAPE novo 1804%). Não havia
GET nem rollback, e o papel era `analista`.

Cobre: (1) régua = a MESMA do monitor (snapshot do LAUNCH), (2) publicar 2× o mesmo
dado NÃO compõe (409 idempotente), (3) previsão absurda REPROVA no piso de score,
(4) `GET /calibracao` lista da v1 à vigente, (5)
`POST /calibracao/{versao}/rollback` restaura priors dict a dict — inclusive a v1
`PRIORS_DEFAULT` com N versões publicadas por cima, (6) papel `lider`,
(7) Previsto SEM `priors_versao` (legado) não entra na rodada — a re-previsão sobre
base chutada fazia a razão OSCILAR e publicar versão nova a cada clique, para sempre.

Sem docker e SEM REDE (§1.3.5): calibração é 100% determinística, ZERO LLM (§10.6).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import PROBLEM_CONTENT_TYPE
from application.services.otimizacao_service import priors_vigentes
from domain.governanca.modelos import Snapshot
from domain.lancamento.modelos import Launch
from domain.otimizacao.calibracao import taxas_de_conversao
from domain.simulacao.priors import PRIORS_DEFAULT
from tests.acceptance.test_M11 import (
    TENANT,
    _h,
    _semear_jornada,
    _semear_telemetria,
    _simular_e_congelar,
)

LIDER = "dev-lider"
# A jornada semeada pelo M11 congela P50 = 1625 conversões (seed 42, §6 determinístico).
P50_SEMEADO = 1625.0
REALIZADO_PLAUSIVEL = 1300  # razão 0,8 — calibração legítima (previsto 25% otimista)
REALIZADO_ABSURDO = 40  # razão 0,025 → clamp 0,25: a forma exata do achado na VPS


def _semear_caso(
    client: TestClient, app: FastAPI, *, conv_tratado: int
) -> tuple[uuid.UUID, uuid.UUID]:
    """OS com Previsto congelado + snapshot + telemetria ENS — o insumo mínimo do
    CalibrateService (previsto congelado × realizado)."""
    jornada_id, os_id = _semear_jornada(client, app)
    _simular_e_congelar(client, jornada_id)
    snapshot = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=_h())
    assert snapshot.status_code == 201, snapshot.text
    _semear_telemetria(
        app,
        os_id,
        n_sents=400,
        conv_tratado=conv_tratado,
        conv_holdout=0,
        inicio=datetime.now(UTC) - timedelta(days=20),
    )
    return jornada_id, os_id


# ------------------------------------------------ achado 4 · o portão que não reprovava


def test_uat5_04_publicar_duas_vezes_nao_compoe(client: TestClient, app: FastAPI) -> None:
    """A 2ª publicação do MESMO dado é 409 — a razão foi recalculada sobre o previsto
    RE-PREVISTO com os priors já calibrados, dá 1,0 e reproduz a régua vigente.

    Antes do fix as duas passavam e a razão COMPUNHA (0,8 × 0,8): era assim que a VPS
    chegava a `email.conversao` 256× abaixo do default em três cliques.
    """
    _semear_caso(client, app, conv_tratado=REALIZADO_PLAUSIVEL)

    primeira = client.post("/api/v1/calibracao/publicar", headers=_h(LIDER))
    assert primeira.status_code == 201, primeira.text
    corpo = primeira.json()
    assert corpo["versao"] == 2 and corpo["backtest"]["melhora"] is True
    assert corpo["backtest"]["razao"] == 0.8  # 1300 ÷ 1625, sem clamp
    taxas_v2 = taxas_de_conversao(corpo["priors"])
    assert taxas_v2["canal:email"] == 0.0256  # 0,032 × 0,8

    segunda = client.post("/api/v1/calibracao/publicar", headers=_h(LIDER))
    assert segunda.status_code == 409, segunda.text
    assert segunda.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "idempotente" in segunda.json()["detail"]

    # nada foi publicado: a régua vigente continua sendo a v2 da primeira chamada
    lista = client.get("/api/v1/calibracao", headers=_h()).json()
    assert lista["vigente"] == 2
    assert taxas_de_conversao(lista["versoes"][-1]["priors"]) == taxas_v2


def test_uat5_04_previsao_absurda_reprova_no_piso_de_score(
    client: TestClient, app: FastAPI
) -> None:
    """Previsto ≫ realizado (1625 × 40): a razão bate no clamp 0,25 e, mesmo
    calibrado, o erro segue absurdo (MAPE 916%). Backtest REPROVA — priors intactos.

    É o caso que a VPS publicou três vezes com `score 0.0` e `melhora: true`, porque o
    backtest comparava `|previsto_cru − realizado|` contra `|previsto_cru × 0,25 −
    realizado|`: com previsto ≫ realizado, "melhora" é aritmeticamente garantida.
    """
    _semear_caso(client, app, conv_tratado=REALIZADO_ABSURDO)

    reprovada = client.post("/api/v1/calibracao/publicar", headers=_h(LIDER))
    assert reprovada.status_code == 409, reprovada.text
    assert reprovada.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "score" in reprovada.json()["detail"]

    # priors do tenant NÃO foram tocados: continua valendo a v1 default (§6)
    lista = client.get("/api/v1/calibracao", headers=_h()).json()
    assert lista["vigente"] == 1 and [v["versao"] for v in lista["versoes"]] == [1]
    assert taxas_de_conversao(priors_vigentes(app.state.repositorio_os, TENANT)) == (
        taxas_de_conversao(PRIORS_DEFAULT)
    )


def test_uat5_04_regua_e_a_mesma_do_monitor(client: TestClient, app: FastAPI) -> None:
    """A calibração usa o snapshot do LAUNCH, como o monitor M10 — não o último
    snapshot com previsto.

    Cenário do bônus do achado: depois do launch nasce um snapshot NOVO (proposta
    aprovada, re-simulada) com previsto muito maior. Antes do fix a calibração pegava
    esse P50 novo contra o realizado do launch e derivava uma razão absurda — para a
    MESMA OS, no mesmo instante, o monitor dizia 248×271 e a calibração 20644×271.
    """
    _, os_id = _semear_caso(client, app, conv_tratado=REALIZADO_PLAUSIVEL)
    repo = app.state.repositorio_os
    lancado = repo.listar_snapshots(os_id)[-1]
    assert lancado.previsto["conversoes"]["p50"] == P50_SEMEADO
    repo.adicionar_launch(Launch(id=uuid.uuid4(), snapshot_id=lancado.id, estado="concluido"))
    repo.adicionar_snapshot(  # snapshot POSTERIOR, nunca lançado (a régua errada)
        Snapshot(
            id=uuid.uuid4(),
            os_id=os_id,
            hash="f" * 64,
            conteudo={},
            previsto={"conversoes": {"p50": P50_SEMEADO * 100}},
            created_at=datetime.now(UTC),
        )
    )

    publicada = client.post("/api/v1/calibracao/publicar", headers=_h(LIDER))
    assert publicada.status_code == 201, publicada.text
    caso = publicada.json()["backtest"]["casos"][0]
    assert caso["previsto_congelado"] == P50_SEMEADO  # régua do launch, não a do último
    assert caso["realizado"] == float(REALIZADO_PLAUSIVEL)
    assert publicada.json()["backtest"]["razao"] == 0.8


def test_uat5_04_previsto_sem_carimbo_nao_oscila(client: TestClient, app: FastAPI) -> None:
    """Previsto congelado SEM `parametros.priors_versao` fica FORA da rodada quando o
    tenant já tem calibração publicada — a base da re-previsão é desconhecida.

    Variação do achado 4 que o primeiro fix deixou passar: chutando `PRIORS_DEFAULT`
    como base, um P50 congelado SOB priors já calibrados era escalado de novo, a razão
    oscilava (0,8 → 1,25 → 0,8 …) e CADA clique publicava uma versão nova, sem fim —
    a mesma classe do achado, só que lenta. Aqui a 2ª rodada tem de parar.
    """
    _, os_id = _semear_caso(client, app, conv_tratado=REALIZADO_PLAUSIVEL)
    repo = app.state.repositorio_os
    repo.adicionar_launch(
        Launch(id=uuid.uuid4(), snapshot_id=repo.listar_snapshots(os_id)[-1].id, estado="lancado")
    )
    primeira = client.post("/api/v1/calibracao/publicar", headers=_h(LIDER))
    assert primeira.status_code == 201, primeira.text  # razão 0,8 sobre o P50 carimbado

    # a OS é re-simulada sob a v2 e relançada, mas o Previsto sai SEM carimbo (legado)
    legado = Snapshot(
        id=uuid.uuid4(),
        os_id=os_id,
        hash="a" * 64,
        conteudo={},
        previsto={"conversoes": {"p50": P50_SEMEADO * 0.8}},  # já reflete a v2
        created_at=datetime.now(UTC),
    )
    repo.adicionar_snapshot(legado)
    repo.adicionar_launch(Launch(id=uuid.uuid4(), snapshot_id=legado.id, estado="lancado"))

    segunda = client.post("/api/v1/calibracao/publicar", headers=_h(LIDER))
    assert segunda.status_code == 409, segunda.text
    assert segunda.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "priors_versao" in segunda.json()["detail"]  # 409 diz POR QUE ficou de fora
    assert [c.versao for c in repo.listar_calibracoes(TENANT)] == [2]  # nada novo


# --------------------------------------------------- achado 4 · GET, rollback e papel


def test_uat5_04_get_calibracao_lista_da_v1_a_vigente(client: TestClient, app: FastAPI) -> None:
    """GET /calibracao: ordem CRESCENTE de versão, v1 `PRIORS_DEFAULT` sintética
    primeiro (mora em código, não na tabela), `vigente` só na última."""
    vazio = client.get("/api/v1/calibracao", headers=_h()).json()
    assert [v["versao"] for v in vazio["versoes"]] == [1]
    assert vazio["versoes"][0]["origem"] == "default" and vazio["versoes"][0]["vigente"] is True
    assert taxas_de_conversao(vazio["versoes"][0]["priors"]) == taxas_de_conversao(PRIORS_DEFAULT)

    _semear_caso(client, app, conv_tratado=REALIZADO_PLAUSIVEL)
    assert client.post("/api/v1/calibracao/publicar", headers=_h(LIDER)).status_code == 201
    assert client.post("/api/v1/calibracao/1/rollback", headers=_h(LIDER)).status_code == 201

    lista = client.get("/api/v1/calibracao", headers=_h()).json()
    assert [v["versao"] for v in lista["versoes"]] == [1, 2, 3]
    assert [v["origem"] for v in lista["versoes"]] == ["default", "calibracao", "rollback"]
    assert [v["vigente"] for v in lista["versoes"]] == [False, False, True]
    assert lista["vigente"] == 3
    assert lista["versoes"][1]["publicada_em"] and lista["versoes"][1]["casos"] == 1
    assert lista["versoes"][1]["razao_aplicada"] == 0.8
    assert lista["versoes"][2]["score"] is None  # rollback não pontua


def test_uat5_04_rollback_restaura_priors_da_versao_alvo(client: TestClient, app: FastAPI) -> None:
    """Rollback republica os priors EXATOS da versão alvo (dict a dict) — inclusive a
    v1 `PRIORS_DEFAULT` com várias versões publicadas por cima. É o botão que conserta
    um tenant já estragado (UAT5 achado 4: na VPS não existia)."""
    _semear_caso(client, app, conv_tratado=REALIZADO_PLAUSIVEL)
    versao_2 = client.post("/api/v1/calibracao/publicar", headers=_h(LIDER))
    assert versao_2.status_code == 201, versao_2.text
    taxas_v2: dict[str, Any] = taxas_de_conversao(versao_2.json()["priors"])
    assert taxas_v2 != taxas_de_conversao(PRIORS_DEFAULT)  # a calibração mexeu na régua

    # empilha 4 rollbacks para a v2 (v3..v6): voltar não é "desfazer a última"
    for _ in range(4):
        assert client.post("/api/v1/calibracao/2/rollback", headers=_h(LIDER)).status_code == 201

    volta = client.post("/api/v1/calibracao/1/rollback", headers=_h(LIDER))
    assert volta.status_code == 201, volta.text
    corpo = volta.json()
    assert corpo["versao"] == 7 and corpo["priors"]["rollback_de"] == 1
    assert corpo["priors"]["origem"] == "rollback"
    assert corpo["score"] is None  # rollback não pontua: não há hipótese sendo testada
    assert "razao_aplicada" not in corpo["priors"]
    assert taxas_de_conversao(corpo["priors"]) == taxas_de_conversao(PRIORS_DEFAULT)
    for chave in ("engajamento", "classes_frequencia", "mult_classe", "ticket_medio"):
        assert corpo["priors"][chave] == PRIORS_DEFAULT[chave]  # dict a dict, não só taxas

    # o simulador (§6) já usa a régua restaurada e o histórico ficou (append-only §4.1)
    repo = app.state.repositorio_os
    assert taxas_de_conversao(priors_vigentes(repo, TENANT)) == taxas_de_conversao(PRIORS_DEFAULT)
    assert [c.versao for c in repo.listar_calibracoes(TENANT)] == [2, 3, 4, 5, 6, 7]

    fantasma = client.post("/api/v1/calibracao/99/rollback", headers=_h(LIDER))
    assert fantasma.status_code == 404
    assert fantasma.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)


def test_uat5_04_papel_lider_para_publicar_e_rollback(client: TestClient, app: FastAPI) -> None:
    """Priors valem para o TENANT INTEIRO: `analista` lê, mas não publica nem faz
    rollback (§8-M0 — mesmo papel de publicar política/criativo)."""
    _semear_caso(client, app, conv_tratado=REALIZADO_PLAUSIVEL)

    negado = client.post("/api/v1/calibracao/publicar", headers=_h("dev-analista"))
    assert negado.status_code == 403, negado.text
    rollback_negado = client.post("/api/v1/calibracao/1/rollback", headers=_h("dev-analista"))
    assert rollback_negado.status_code == 403, rollback_negado.text
    assert client.get("/api/v1/calibracao", headers=_h("dev-analista")).status_code == 200
    assert not app.state.repositorio_os.listar_calibracoes(TENANT)  # nada publicado

    assert client.post("/api/v1/calibracao/publicar", headers=_h("dev-admin")).status_code == 201
