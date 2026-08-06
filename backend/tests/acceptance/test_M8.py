"""Aceites do módulo M8 · parte 1: Simulador T8 / Ensaio Geral (SDD §6, §8-M8) ·
parte 2: Portões T9 + Aprovação T10 (§8-M8, §4.1 snapshot/aprovacao/experimento) —
IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker e SEM REDE: o simulador é código determinístico
(zero LLM — §10.6/§1.1.2); RngPort/ClockPort ficam atrás de portas (§2.1) e a mesma
seed reproduz os mesmos P10/P50/P90 (A1). O twin (`jornada_versao`), o segmento
recontado e o experimento são semeados direto no repositório em memória
(`app.state.repositorio_os` — padrão documentado em os_governanca.get_repositorio_os);
as rotas do M7 chegam com o próprio M7.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import PROBLEM_CONTENT_TYPE
from domain.audiencia.modelos import CertificadoElegibilidade, Segmento
from domain.experimento.modelos import Experimento
from domain.experimento.poder import n_minimo_por_mde
from domain.jornada.canonico import hash_jgc
from domain.jornada.modelos import JornadaVersao

TENANT = "torre-movel"
VOLUME_LIQUIDO = 50_000

# Parâmetros pequenos p/ teste rápido (o NFR §6 de 10k<60s é assunto de perf, não daqui)
PARAMS = {"seed": 42, "runs": 80, "n_personas": 500}


def _h(token: str = "dev-analista") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _grafo(os_codigo: str) -> dict[str, Any]:
    """JGC §5 válido (§5.3): entrada → randomSplit 90/10 (holdout) → wait → e-mail
    (opt-in, throttle) → goal; braço holdout → exit. Quiet hours no meta (§5.1)."""
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


def _criar_os(client: TestClient) -> dict[str, Any]:
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


def _semear_jornada(
    client: TestClient,
    app: FastAPI,
    *,
    grafo: dict[str, Any] | None = None,
    experimento: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """OS via API + segmento recontado/jornada (e experimento §4.1) direto no repo."""
    os_ = _criar_os(client)
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
    jgc = grafo if grafo is not None else _grafo(os_["codigo"])
    jornada = JornadaVersao(
        id=uuid.uuid4(),
        os_id=os_id,
        versao=repo.proxima_versao(os_id),
        grafo=jgc,
        hash=hash_jgc(jgc),
    )
    repo.adicionar_jornada(jornada)
    return jornada.id, os_id


def _p50s(simulacao: dict[str, Any]) -> tuple[Any, ...]:
    return (
        simulacao["conversoes"]["p50"],
        simulacao["custo"]["p50"],
        simulacao["receita"]["p50"],
        simulacao["roas"]["p50"],
        simulacao["lift_pp"]["p50"],
        {no: p["p50"] for no, p in simulacao["funil"].items()},
    )


# ---------------------------------------------------------------------- Aceites §8-M8


def test_M8_A1(client: TestClient, app: FastAPI) -> None:
    """A1: simulação com seed fixa é reprodutível (mesmos P50s)."""
    jornada_id, _ = _semear_jornada(client, app)

    r1 = client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    assert r1.status_code == 200, r1.text
    corpo = r1.json()
    assert corpo["estado"] == "simulado"  # persistida em jornada_versao (§6)
    sim1 = corpo["simulacao"]
    # Saída §6: funil por nó, P10/P50/P90 de conversões/custo/receita/ROAS, lift+poder
    assert set(sim1["funil"]) == {"n1", "n2", "n3", "n4", "n5", "n6"}
    for bloco in ("conversoes", "custo", "receita", "roas", "lift_pp"):
        assert sim1[bloco]["p10"] <= sim1[bloco]["p50"] <= sim1[bloco]["p90"]
    assert sim1["funil"]["n1"]["p50"] == VOLUME_LIQUIDO  # entrada = líquido do segmento
    assert sim1["semaforo"] == "verde"  # ROAS>1, sem colisão, sem experimento (§6)
    assert sim1["parametros"]["seed"] == PARAMS["seed"]

    # mesma seed ⇒ mesmos P50s (na verdade a MESMA saída determinística inteira)
    r2 = client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    assert r2.status_code == 200, r2.text
    sim2 = r2.json()["simulacao"]
    assert _p50s(sim2) == _p50s(sim1)
    assert {k: v for k, v in sim2.items() if k != "executada_em"} == {
        k: v for k, v in sim1.items() if k != "executada_em"
    }

    # seed diferente ⇒ outra amostra Monte Carlo (outros P50s)
    r3 = client.post(
        f"/api/v1/jornadas/{jornada_id}/simular", json={**PARAMS, "seed": 7}, headers=_h()
    )
    assert r3.status_code == 200, r3.text
    assert _p50s(r3.json()["simulacao"]) != _p50s(sim1)


def test_M8_A2(client: TestClient, app: FastAPI) -> None:
    """A2: poder insuficiente (n<n_minimo) → portão experimento vermelho e simulação
    amarela (regra §6 emendada — CHANGELOG-SDD.md)."""
    jornada_id, os_id = _semear_jornada(
        client,
        app,
        experimento={
            "holdout_pct": 10.0,
            "n_minimo": 1_000_000,  # >> holdout (~5k) e tratado (~45k) disponíveis
            "mde_pp": 1.0,
            "janela_dias": 14,
        },
    )
    resposta = client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    assert resposta.status_code == 200, resposta.text
    simulacao = resposta.json()["simulacao"]

    poder = simulacao["poder"]
    assert poder["aplicavel"] is True
    assert poder["n_disponivel"] < poder["n_minimo"]
    assert poder["suficiente"] is False
    assert poder["portao"] == "vermelho"
    assert simulacao["portoes"]["experimento"] == "vermelho"
    assert simulacao["semaforo"] == "amarelo"
    assert any("poder" in m.lower() for m in simulacao["motivos_semaforo"])

    # amarelo NÃO bloqueia T9/T11 (só o vermelho emite gate.blocked — §6)
    repo = app.state.repositorio_os
    assert repo.listar_eventos(os_id=os_id, tipo="simulacao.executada")
    assert not repo.listar_eventos(os_id=os_id, tipo="gate.blocked")


# ------------------------------------------------- Contrato das demais rotas §8-M8


def test_M8_congelar_previsto(client: TestClient, app: FastAPI) -> None:
    """Congelar sem simulação → 409; após simular, `previsto` = simulação + carimbo."""
    jornada_id, _ = _semear_jornada(client, app)
    sem_simulacao = client.post(f"/api/v1/jornadas/{jornada_id}/congelar-previsto", headers=_h())
    assert sem_simulacao.status_code == 409
    assert sem_simulacao.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    congelada = client.post(f"/api/v1/jornadas/{jornada_id}/congelar-previsto", headers=_h())
    assert congelada.status_code == 200, congelada.text
    corpo = congelada.json()
    previsto = corpo["previsto"]
    assert previsto["congelado_em"] and previsto["congelado_por"]
    assert _p50s(previsto) == _p50s(corpo["simulacao"])  # régua = simulação corrente


def test_M8_comparar_cenarios(client: TestClient, app: FastAPI) -> None:
    """`POST /simulacoes/comparar`: P50s por cenário + deltas vs baseline (o 1º)."""
    jornada_a, _ = _semear_jornada(client, app)
    jornada_b, _ = _semear_jornada(client, app)
    client.post(f"/api/v1/jornadas/{jornada_a}/simular", json=PARAMS, headers=_h())
    client.post(f"/api/v1/jornadas/{jornada_b}/simular", json={**PARAMS, "seed": 7}, headers=_h())
    resposta = client.post(
        "/api/v1/simulacoes/comparar",
        json={"jornada_ids": [str(jornada_a), str(jornada_b)]},
        headers=_h(),
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["baseline"] == str(jornada_a)
    assert [c["jornada_id"] for c in corpo["cenarios"]] == [str(jornada_a), str(jornada_b)]
    assert all(v == 0 for v in corpo["cenarios"][0]["delta_vs_baseline"].values())
    assert any(v not in (0, None) for v in corpo["cenarios"][1]["delta_vs_baseline"].values())


def test_M8_grafo_invalido_422(client: TestClient, app: FastAPI) -> None:
    """Simular grafo que viola §5.3 (sem goal) → 422 problem+json com `erros[]`."""
    os_codigo = "OS-INVALIDA"
    grafo = _grafo(os_codigo)
    grafo["nodes"] = [n for n in grafo["nodes"] if n["id"] != "n5"]
    grafo["edges"] = [e for e in grafo["edges"] if e["to"] != "n5"]
    jornada_id, _ = _semear_jornada(client, app, grafo=grafo)
    resposta = client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    assert resposta.status_code == 422, resposta.text
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert any(e["regra"] == "sem_goal" for e in resposta.json()["erros"])


# ================================================= M8 parte 2 · Portões T9 + Aprovação T10
# Fluxo (§8-M8): simular → congelar previsto → snapshot (hash composto) → link mágico
# → decisão. As rotas de /aprovacao/* são STANDALONE (sem shell, §12) e dispensam
# `X-Tenant` (C03/A5) — mas, desde o E03 (§10.5), NÃO são anônimas: o token deixou de ser
# credencial e virou ponteiro para o pacote; quem lê e quem decide vem da SESSÃO.

# O aprovador designado dos aceites: usuário do sistema com o papel `aprovador`, que
# cobre a faixa de alçada deste snapshot (§11.4). Desde o E03 o destinatário do link
# PRECISA ter conta — sem conta não há sessão, e sem sessão não há decisão.
APROVADOR = "aprovador@dev.jornada.local"  # dono do Bearer `dev-aprovador`

# Sessão do aprovador COM o header do app (o caminho da SPA)…
_H_APROVADOR = {
    "X-Tenant": TENANT,
    "Authorization": "Bearer dev-aprovador",
    "User-Agent": "pytest-aprovador",
}
# …e SEM header nenhum além da credencial: o deep link aberto direto do chat/e-mail, que
# é o caso do C03/A5 e continua valendo — o escopo sai da sessão, não de um header.
_H_APROVADOR_SEM_TENANT = {
    "Authorization": "Bearer dev-aprovador",
    "User-Agent": "pytest-aprovador-externo",
}


def _preparar_snapshot(
    client: TestClient, app: FastAPI, *, token: str = "dev-analista"
) -> tuple[uuid.UUID, uuid.UUID, dict[str, Any]]:
    """Jornada simulada + previsto congelado + snapshot criado (pré-requisitos §8-M8).

    `token` escolhe QUEM monta o snapshot — é o que vira `criado_por` e, portanto, o lado
    esquerdo da segregação do A6 (§10.5). Default `dev-analista`, como sempre foi."""
    jornada_id, os_id = _semear_jornada(client, app)
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h()).status_code
        == 200
    )
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/congelar-previsto", headers=_h()).status_code
        == 200
    )
    resposta = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=_h(token))
    assert resposta.status_code == 201, resposta.text
    return jornada_id, os_id, resposta.json()


def _nova_versao_mais_cara(client: TestClient, app: FastAPI, os_id: uuid.UUID) -> uuid.UUID:
    """v2 do twin com segmento 60% maior → custo P50 sobe >10% (gatilho do A4)."""
    repo = app.state.repositorio_os
    volume = int(VOLUME_LIQUIDO * 1.6)
    repo.adicionar_segmento(
        Segmento(
            id=uuid.uuid4(),
            os_id=os_id,
            origem="estudio_sql",
            contagem_bruta=volume + 11_000,
            contagem_liquida=volume,
            volume_abordagem={"email": {"n": volume, "pct": 100.0}},
        )
    )
    codigo = client.get(f"/api/v1/os/{os_id}", headers=_h()).json()["codigo"]
    jgc = _grafo(codigo)
    jornada = JornadaVersao(
        id=uuid.uuid4(),
        os_id=os_id,
        versao=repo.proxima_versao(os_id),
        grafo=jgc,
        hash=hash_jgc(jgc),
    )
    repo.adicionar_jornada(jornada)
    assert (
        client.post(f"/api/v1/jornadas/{jornada.id}/simular", json=PARAMS, headers=_h()).status_code
        == 200
    )
    return jornada.id


def test_M8_A3(client: TestClient, app: FastAPI) -> None:
    """A3: token de uso único, expira e registra ip/device; ressalvas criam pendências
    automaticamente (bloqueantes, origem `aprovacao:{id}`)."""
    jornada_id, os_id, snap = _preparar_snapshot(client, app)
    assert len(snap["hash"]) == 64  # hash composto sha256 (§4.1)

    link = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": APROVADOR},  # A6: link nasce endereçado
        headers=_h(),
    )
    assert link.status_code == 201, link.text
    corpo_link = link.json()
    token = corpo_link["token"]
    assert token in corpo_link["url"] and "/aprovacao/" in corpo_link["url"]  # rota §12
    assert corpo_link["alcada"] == "lider"  # custo ~R$81 → faixa `ate` 100k (§11.4)

    # página standalone com a SESSÃO do aprovador (E03); hash + replay do previsto
    pagina = client.get(f"/api/v1/aprovacao/{token}", headers=_H_APROVADOR)
    assert pagina.status_code == 200, pagina.text
    assert pagina.json()["snapshot"]["hash"] == snap["hash"]
    assert pagina.json()["previsto"]["congelado_em"]
    assert pagina.json()["sessao"] == {  # E03: a UI sabe quem está decidindo
        "email": APROVADOR,
        "nome": "Dev Aprovador",
        "pode_decidir": True,
    }

    decisao = client.post(
        f"/api/v1/aprovacao/{token}/decidir",
        json={
            "decisao": "aprovado_ressalvas",
            "ressalvas": ["Ajustar copy do e-mail", "Confirmar verba com financeiro"],
            "decidido_por": APROVADOR,
        },
        headers=_H_APROVADOR,
    )
    assert decisao.status_code == 200, decisao.text
    corpo = decisao.json()
    assert corpo["decisao"] == "aprovado_ressalvas"
    assert corpo["decidido_meta"]["ip"]  # ip registrado (TestClient → "testclient")
    assert corpo["decidido_meta"]["device"] == "pytest-aprovador"  # device = user-agent
    # E03: a trilha guarda o e-mail AUTENTICADO da sessão, não só o congelado no link
    assert corpo["decidido_meta"]["sessao_email"] == APROVADOR
    assert len(corpo["pendencias_criadas"]) == 2

    # ressalvas viraram pendências bloqueantes na OS (origem aprovacao:{id})
    repo = app.state.repositorio_os
    pendencias = [
        p for p in repo.listar_pendencias(os_id) if (p.origem or "").startswith("aprovacao:")
    ]
    assert len(pendencias) == 2
    assert all(p.bloqueante and p.status == "aberta" for p in pendencias)
    # aprovado* marca a versão do twin (§4.1 `jornada_versao.estado`)
    assert repo.obter_jornada(jornada_id).estado == "aprovado"

    # uso ÚNICO: decidir de novo com o mesmo token → 409 problem+json
    repetida = client.post(
        f"/api/v1/aprovacao/{token}/decidir", json={"decisao": "aprovado"}, headers=_H_APROVADOR
    )
    assert repetida.status_code == 409
    assert repetida.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    # expiração: segundo link, vencido → 410 Gone no GET e no decidir
    link2 = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": APROVADOR},
        headers=_h(),
    ).json()
    aprovacao2 = next(
        a
        for a in repo.listar_aprovacoes(uuid.UUID(snap["id"]))
        if str(a.id) == link2["aprovacao_id"]
    )
    aprovacao2.expira_em = datetime.now(UTC) - timedelta(hours=1)
    repo.salvar_aprovacao(aprovacao2)
    assert (
        client.get(f"/api/v1/aprovacao/{link2['token']}", headers=_H_APROVADOR).status_code == 410
    )
    vencida = client.post(
        f"/api/v1/aprovacao/{link2['token']}/decidir",
        json={"decisao": "aprovado"},
        headers=_H_APROVADOR,
    )
    assert vencida.status_code == 410
    assert vencida.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    # token desconhecido não vaza existência → 404
    token_falso = "x" * 43
    assert client.get(f"/api/v1/aprovacao/{token_falso}", headers=_H_APROVADOR).status_code == 404


def test_M8_A4(client: TestClient, app: FastAPI) -> None:
    """A4: variação de custo >10% APÓS a aprovação invalida a aprovação — snapshot
    novo obrigatório (colunas `invalidada_*`, migração 0006)."""
    _, os_id, snap = _preparar_snapshot(client, app)
    token = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": APROVADOR},
        headers=_h(),
    ).json()["token"]
    assert (
        client.post(
            f"/api/v1/aprovacao/{token}/decidir", json={"decisao": "aprovado"}, headers=_H_APROVADOR
        ).status_code
        == 200
    )

    portoes = client.get(f"/api/v1/os/{os_id}/portoes", headers=_h()).json()
    assert portoes["aprovacao"]["estado"] == "verde"
    assert portoes["aprovacao"]["decisao"] == "aprovado"

    # novo ciclo: v2 com custo >10% acima do congelado no snapshot aprovado
    jornada2_id = _nova_versao_mais_cara(client, app, os_id)
    portoes = client.get(f"/api/v1/os/{os_id}/portoes", headers=_h()).json()
    assert portoes["aprovacao"]["estado"] == "vermelho"
    assert "10%" in portoes["aprovacao"]["motivo"]
    assert "snapshot" in portoes["aprovacao"]["motivo"]

    repo = app.state.repositorio_os
    aprovacao = repo.listar_aprovacoes(uuid.UUID(snap["id"]))[0]
    assert aprovacao.invalidada_em is not None  # persistida (migração 0006)
    assert repo.listar_eventos(os_id=os_id, tipo="aprovacao.invalidada")

    # snapshot novo obrigatório: v2 congelada gera OUTRO hash composto (custo mudou)
    assert (
        client.post(f"/api/v1/jornadas/{jornada2_id}/congelar-previsto", headers=_h()).status_code
        == 200
    )
    novo = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=_h())
    assert novo.status_code == 201, novo.text
    assert novo.json()["hash"] != snap["hash"]


def test_M8_A5_link_magico_sem_x_tenant(client: TestClient, app: FastAPI) -> None:
    """A5 (C03 — UAT #3 adversarial), revisto pelo E03: o link mágico é STANDALONE de
    verdade, e standalone NÃO quer dizer anônimo.

    O que o C03 provou e continua valendo: o deep link é aberto direto (chat, e-mail,
    barra do navegador) e nenhum header do app viaja junto — o fluxo inteiro (ver o
    pacote → decidir → uso único) roda SEM `X-Tenant`. O que muda com o E03 é a FONTE do
    escopo: antes derivado do token, agora do portador autenticado — porque o token
    deixou de ser credencial. O resto da API v1 segue exigindo o header (§8-M0-A2)."""
    jornada_id, os_id, snap = _preparar_snapshot(client, app)
    token = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": APROVADOR},
        headers=_h(),
    ).json()["token"]

    # 1) página SEM X-Tenant, só com a sessão
    pagina = client.get(f"/api/v1/aprovacao/{token}", headers=_H_APROVADOR_SEM_TENANT)
    assert pagina.status_code == 200, pagina.text
    assert pagina.json()["snapshot"]["hash"] == snap["hash"]
    assert pagina.json()["decisao"] is None

    # 2) decisão SEM X-Tenant
    decisao = client.post(
        f"/api/v1/aprovacao/{token}/decidir",
        json={"decisao": "aprovado", "decidido_por": APROVADOR},
        headers=_H_APROVADOR_SEM_TENANT,
    )
    assert decisao.status_code == 200, decisao.text
    assert decisao.json()["decisao"] == "aprovado"
    assert decisao.json()["decidido_meta"]["device"] == "pytest-aprovador-externo"
    repo = app.state.repositorio_os
    assert repo.obter_jornada(jornada_id).estado == "aprovado"  # efeito de domínio real
    assert repo.listar_eventos(os_id=os_id, tipo="snapshot.approved")

    # 3) uso ÚNICO continua valendo sem header: 2ª decisão → 409
    repetida = client.post(
        f"/api/v1/aprovacao/{token}/decidir",
        json={"decisao": "aprovado"},
        headers=_H_APROVADOR_SEM_TENANT,
    )
    assert repetida.status_code == 409
    assert repetida.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    # 4) escopo fechado: anunciar OUTRO tenant não alcança o pacote. O 403 vem de
    # `get_current_user` (emenda G01) — o header é asserção conferida contra a credencial,
    # e a isenção do C03 é do header OBRIGATÓRIO, nunca da conferência.
    outro = client.get(
        f"/api/v1/aprovacao/{token}",
        headers={**_H_APROVADOR_SEM_TENANT, "X-Tenant": "torre-residencial"},
    )
    assert outro.status_code == 403, outro.text

    # 5) a isenção é SÓ do link mágico — o resto da API v1 segue exigindo X-Tenant
    sem_tenant = client.get("/api/v1/os", headers={"Authorization": "Bearer dev-analista"})
    assert sem_tenant.status_code == 400
    assert client.post(f"/api/v1/snapshots/{snap['id']}/link-magico").status_code == 400


def test_M8_A6_criador_nao_aprova(client: TestClient, app: FastAPI) -> None:
    """A6 (§10.5 — UAT #5 achado 2): criador ≠ aprovador, checado SERVER-SIDE.

    O buraco provado na VPS: a mesma pessoa montava o snapshot, gerava o link mágico
    para si própria e decidia mandando `decidido_por` no corpo — endpoint público, string
    livre, ninguém lia o `criado_por` do snapshot. A correção carimba o DESTINATÁRIO na
    EMISSÃO (o token é a credencial, e nasce endereçado): a identidade do aprovador
    passa a vir do link, nunca do corpo do POST.
    """
    repo = app.state.repositorio_os
    jornada_id, os_id, snap = _preparar_snapshot(client, app)
    criador = "analista@dev.jornada.local"  # dono do Bearer `dev-analista` de `_h()`
    assert repo.obter_snapshot(uuid.UUID(snap["id"])).conteudo["criado_por"] == criador

    # 1) AUTO-APROVAÇÃO: o cenário exato da VPS morre na emissão (caixa/espaços normalizados)
    auto = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": "  Analista@DEV.Jornada.Local  "},
        headers=_h(),
    )
    assert auto.status_code == 409, auto.text
    assert auto.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    # a mensagem PRECISA ser a da segregação: o `analista` também não tem a alçada da
    # faixa, e sem checar o texto este 409 passaria mesmo com a guarda do criador morta
    assert "não pode aprová-lo" in auto.json()["detail"]
    assert not repo.listar_aprovacoes(uuid.UUID(snap["id"]))  # nenhum link foi emitido

    # 2) destinatário é OBRIGATÓRIO — não há mais link anônimo
    assert (
        client.post(f"/api/v1/snapshots/{snap['id']}/link-magico", headers=_h()).status_code == 422
    )

    # 3) roster (§8-M0): usuário do sistema sem o papel da faixa de alçada → 409
    sem_papel = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": "solicitante@dev.jornada.local"},
        headers=_h(),
    )
    assert sem_papel.status_code == 409, sem_papel.text
    assert "lider" in sem_papel.json()["detail"]

    # 3a) o roster do PORTAL (§8-M3) conta igual: `portal@` é solicitante e não aprova.
    # Varrer só `DEV_TOKENS` fazia este e-mail passar por "de fora" e pular a alçada.
    portal = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": "portal@dev.jornada.local"},
        headers=_h(),
    )
    assert portal.status_code == 409, portal.text
    assert "solicitante" in portal.json()["detail"]

    # 3b) alçada é ESCADA: papel de faixa superior (`aprovador`, até R$1M) cobre a de R$100k
    acima = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": "aprovador@dev.jornada.local"},
        headers=_h(),
    )
    assert acima.status_code == 201, acima.text

    # 4) aprovação legítima por OUTRA pessoa segue funcionando
    link = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": "Aprovador@DEV.Jornada.Local"},
        headers=_h(),
    )
    assert link.status_code == 201, link.text
    assert link.json()["aprovador_email"] == APROVADOR
    token = link.json()["token"]
    pagina = client.get(f"/api/v1/aprovacao/{token}", headers=_H_APROVADOR_SEM_TENANT)
    assert pagina.status_code == 200, pagina.text
    assert pagina.json()["aprovador_email"] == APROVADOR

    # 5) forjar `decidido_por` no corpo falha ALTO e não decide nada
    forjada = client.post(
        f"/api/v1/aprovacao/{token}/decidir",
        json={"decisao": "aprovado", "decidido_por": criador},
        headers=_H_APROVADOR_SEM_TENANT,
    )
    assert forjada.status_code == 409, forjada.text
    assert forjada.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert repo.obter_jornada(jornada_id).estado != "aprovado"  # link continua intacto
    assert not repo.listar_eventos(os_id=os_id, tipo="snapshot.approved")

    # 6) sem identidade no corpo: o registrado é o e-mail congelado na emissão
    ok = client.post(
        f"/api/v1/aprovacao/{token}/decidir",
        json={"decisao": "aprovado"},
        headers=_H_APROVADOR_SEM_TENANT,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["decidido_meta"]["decidido_por"] == APROVADOR
    aprovado = repo.listar_eventos(os_id=os_id, tipo="snapshot.approved")[-1]
    assert aprovado.actor == APROVADOR  # trilha real, não declarada


def test_M8_A6_evasoes_da_segregacao(client: TestClient, app: FastAPI) -> None:
    """A6 (§10.5): a guarda criador ≠ aprovador SOZINHA, e o subendereçamento.

    Aqui quem monta o snapshot é o `lider` — que TEM a alçada da faixa. Sem isso a
    recusa poderia vir da checagem de papel e a segregação passaria por testada sem
    nunca ter sido exercida (foi o que aconteceu no primeiro corte deste aceite).
    """
    repo = app.state.repositorio_os
    _, _, snap = _preparar_snapshot(client, app, token="dev-lider")
    assert repo.obter_snapshot(uuid.UUID(snap["id"])).conteudo["criado_por"] == (
        "lider@dev.jornada.local"
    )

    # 1) o criador tem o papel apto e AINDA ASSIM não emite o link para si próprio:
    # só a segregação pode recusar isto
    auto = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": "lider@dev.jornada.local"},
        headers=_h("dev-lider"),
    )
    assert auto.status_code == 409, auto.text
    assert "não pode aprová-lo" in auto.json()["detail"]

    # 2) subendereçamento: `lider+aprova@` é a MESMA caixa postal do criador
    plus = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": "Lider+aprova@Dev.Jornada.Local"},
        headers=_h("dev-lider"),
    )
    assert plus.status_code == 409, plus.text
    assert "não pode aprová-lo" in plus.json()["detail"]
    assert not repo.listar_aprovacoes(uuid.UUID(snap["id"]))

    # 3) a chave SÓ colapsa a mesma caixa: OUTRA pessoa não é barrada pela segregação.
    # Mas o `+tag` dela também não passa mais — desde o E03 `aprovador_email` é um LOGIN,
    # não um endereço de envio (não há camada de e-mail no projeto), e o rótulo depois do
    # `+` não é login de ninguém. A recusa muda de motivo, e a mensagem prova isso: quem
    # decide precisa de conta, e a conta é `aprovador@dev.jornada.local` exatamente.
    com_tag = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": "aprovador+jornada@dev.jornada.local"},
        headers=_h("dev-lider"),
    )
    assert com_tag.status_code == 409, com_tag.text
    assert "não é usuário do sistema" in com_tag.json()["detail"]
    assert not repo.listar_aprovacoes(uuid.UUID(snap["id"]))

    # …e a forma canônica da MESMA pessoa passa (o caminho legítimo não pode fechar)
    outro = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": APROVADOR},
        headers=_h("dev-lider"),
    )
    assert outro.status_code == 201, outro.text
    assert outro.json()["aprovador_email"] == APROVADOR


def test_M8_A6b_quem_emite_nao_endereca_o_link_a_si_mesmo(client: TestClient, app: FastAPI) -> None:
    """E02b (UAT #5 pós-onda 1): a primeira guarda comparava o aprovador só com o
    `criado_por` do SNAPSHOT — mas montar o pacote é um clique disponível a qualquer
    Escritor. O líder que desenhou a jornada pedia ao analista para empacotar e depois
    emitia o link para si mesmo: 201 na emissão, 200 na decisão, §10.5 evaporada com o
    controle constando como "no ar". Quem emite também não aprova.
    """
    repo = app.state.repositorio_os
    # o ANALISTA monta o pacote — então `criado_por` != quem vai emitir
    _, _, snap = _preparar_snapshot(client, app, token="dev-analista")
    assert repo.obter_snapshot(uuid.UUID(snap["id"])).conteudo["criado_por"] == (
        "analista@dev.jornada.local"
    )

    # o LÍDER emite para si mesmo: passa pela guarda do criador (são pessoas distintas)
    # e tem a alçada da faixa — só a segregação do EMISSOR pode recusar
    auto = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": "lider@dev.jornada.local"},
        headers=_h("dev-lider"),
    )
    assert auto.status_code == 409, auto.text
    assert "para si mesmo" in auto.json()["detail"]
    assert not repo.listar_aprovacoes(uuid.UUID(snap["id"])), "nenhum token pode nascer"

    # subendereçamento do emissor cai na mesma caixa
    plus = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": "Lider+aprova@Dev.Jornada.Local"},
        headers=_h("dev-lider"),
    )
    assert plus.status_code == 409, plus.text

    # emitir para OUTRA pessoa segue funcionando (o caminho legítimo não pode fechar)
    ok = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": APROVADOR},
        headers=_h("dev-lider"),
    )
    assert ok.status_code == 201, ok.text


def test_M8_E03_so_a_sessao_do_aprovador_decide(client: TestClient, app: FastAPI) -> None:
    """E03 (§10.5 — UAT #5, o que sobrou depois do A6/E02b): POSSE DO TOKEN NÃO É PODER.

    O buraco que este aceite mata: `POST /snapshots/{id}/link-magico` devolve o token em
    CLARO para quem emite (é a única vez que ele existe fora do hash) e o `decidir` era
    anônimo. Ou seja, o analista que emitia o link tinha, em mãos, a credencial completa
    do aprovador — bastava colar a URL noutra aba. A segregação do A6 congelou o
    DESTINATÁRIO; faltava exigir que quem apresenta o token SEJA ele.

    Agora a identidade vem da sessão e é conferida contra o e-mail congelado na emissão.
    Os quatro casos do §10.5, na ordem em que um atacante os tentaria.
    """
    repo = app.state.repositorio_os
    jornada_id, os_id, snap = _preparar_snapshot(client, app)
    token = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": APROVADOR},
        headers=_h(),  # emitido pelo `dev-analista` — que fica com o token em claro
    ).json()["token"]
    corpo = {"decisao": "aprovado"}

    # 1) SEM sessão: o token sozinho não abre nem a página nem a decisão. 401, e não 404:
    # a credencial é conferida ANTES de existir pergunta sobre o token.
    anonimo = {"User-Agent": "pytest-anonimo"}
    assert client.get(f"/api/v1/aprovacao/{token}", headers=anonimo).status_code == 401
    sem_sessao = client.post(f"/api/v1/aprovacao/{token}/decidir", json=corpo, headers=anonimo)
    assert sem_sessao.status_code == 401, sem_sessao.text
    assert sem_sessao.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    # nem um token INEXISTENTE responde sem credencial (nada de sondar links por fora)
    assert client.get("/api/v1/aprovacao/" + "x" * 43, headers=anonimo).status_code == 401

    # 2) O EMISSOR, de posse do token em claro, logado como ele mesmo → 403.
    # Este é literalmente o cenário do achado: mesma pessoa, mesma URL, outra aba.
    emissor = client.post(
        f"/api/v1/aprovacao/{token}/decidir", json=corpo, headers=_h("dev-analista")
    )
    assert emissor.status_code == 403, emissor.text
    assert emissor.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    # o 403 é MUDO sobre quem é o aprovador: quem está com token alheio não ganha o
    # e-mail dele de brinde (§10.2 — nome/e-mail de pessoa não vaza em erro)
    assert APROVADOR not in emissor.text

    # 3) OUTRA pessoa qualquer do tenant, também com o token → 403 idêntico
    terceiro = client.post(
        f"/api/v1/aprovacao/{token}/decidir", json=corpo, headers=_h("dev-lider")
    )
    assert terceiro.status_code == 403, terceiro.text

    # nada aconteceu: o link continua virgem e o twin não foi aprovado por ninguém
    assert repo.obter_jornada(jornada_id).estado != "aprovado"
    assert not repo.listar_eventos(os_id=os_id, tipo="snapshot.approved")
    assert repo.listar_aprovacoes(uuid.UUID(snap["id"]))[0].decisao is None

    # 4) o APROVADOR designado decide — e só ele
    ok = client.post(f"/api/v1/aprovacao/{token}/decidir", json=corpo, headers=_H_APROVADOR)
    assert ok.status_code == 200, ok.text
    assert ok.json()["decidido_meta"]["sessao_email"] == APROVADOR
    assert repo.obter_jornada(jornada_id).estado == "aprovado"
    assert repo.listar_eventos(os_id=os_id, tipo="snapshot.approved")[-1].actor == APROVADOR


def test_M8_E03_ler_o_pacote_exige_sessao_do_tenant(client: TestClient, app: FastAPI) -> None:
    """E03 (§10.5): `GET /aprovacao/{token}` também deixa de ser anônimo — e por quê.

    O pacote carrega custo, criativos e, pelo achado 9 do UAT #5, PII herdada do
    briefing. Um token de 72h numa URL vaza por histórico de navegador, `Referer`, print
    encaminhado e log de proxy; isso não é controle de acesso para dado de cliente
    (§10.2). Como não há camada de e-mail e quem decide precisa de conta de qualquer
    forma, exigir sessão para LER não custa usabilidade nenhuma: é a mesma pessoa.

    O corte fica onde a informação já mora: LER é de qualquer sessão do tenant dono do
    pacote (são os mesmos dados que essa pessoa lê pelas rotas da OS); DECIDIR é só do
    destinatário — e o payload diz isso à UI para ela não oferecer um botão que dará 403.
    """
    _, _, snap = _preparar_snapshot(client, app)
    token = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": APROVADOR},
        headers=_h(),
    ).json()["token"]

    # colega do tenant: LÊ o pacote…
    colega = client.get(f"/api/v1/aprovacao/{token}", headers=_h("dev-lider"))
    assert colega.status_code == 200, colega.text
    assert colega.json()["snapshot"]["hash"] == snap["hash"]
    # …e a própria resposta avisa que ele NÃO é quem decide (a UI desabilita os botões)
    assert colega.json()["sessao"] == {
        "email": "lider@dev.jornada.local",
        "nome": "Dev Lider",
        "pode_decidir": False,
    }

    # o aprovador vê o mesmo pacote com `pode_decidir` verdadeiro
    dono = client.get(f"/api/v1/aprovacao/{token}", headers=_H_APROVADOR)
    assert dono.status_code == 200, dono.text
    assert dono.json()["sessao"]["pode_decidir"] is True


def test_M8_E03_link_para_quem_nao_tem_conta_e_recusado(client: TestClient, app: FastAPI) -> None:
    """E03 (§10.5): a emissão recusa aprovador SEM CONTA — e falha CEDO, de propósito.

    Não há camada de e-mail no projeto (SMTP_URL existe no config e não tem consumidor),
    então não há convite: contas nascem pelo admin (§8-M0/E04). Se a decisão exige sessão,
    um link endereçado a quem não pode entrar é um link natimorto — e descobrir isso na
    hora de decidir seria o pior momento possível (aprovador travado, prazo correndo,
    ninguém sabendo que o problema é falta de conta). Recusar na EMISSÃO põe a falha na
    frente de quem pode resolvê-la, com o admin a um pedido de distância.

    Efeito colateral que vale por si: "e-mail de fora" era o jeito de PULAR a checagem de
    alçada — sem papéis conhecidos, o serviço não tinha o que conferir e emitia assim
    mesmo. Agora todo destinatário tem papéis, e a faixa da política sempre vale.
    """
    repo = app.state.repositorio_os
    _, _, snap = _preparar_snapshot(client, app)

    de_fora = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": "diretor.cliente@claro.com.br"},
        headers=_h(),
    )
    assert de_fora.status_code == 409, de_fora.text
    assert de_fora.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "não é usuário do sistema" in de_fora.json()["detail"]
    assert "admin" in de_fora.json()["detail"]  # diz o que fazer, não só que falhou
    assert not repo.listar_aprovacoes(uuid.UUID(snap["id"])), "nenhum token pode nascer"


def test_M8_E03_conta_com_subendereco_nao_herda_a_decisao(client: TestClient, app: FastAPI) -> None:
    """E03 (§10.5 — auditoria da frente 3): a régua que RECUSA não pode ser a que CONCEDE.

    `_chave_identidade` colapsa o `+tag` de propósito: para a segregação do E02b ("o
    emissor está endereçando o link a si mesmo?") errar para o lado de barrar custa um
    link a reemitir. Usar a MESMA chave para responder "esta sessão é a do aprovador?"
    inverte o sinal do erro — o alargamento deixa de barrar gente demais e passa a
    AUTORIZAR gente demais, que é escalação de privilégio.

    O cenário concreto, todo ele com contas legítimas: `aprovador+qa@…` é uma conta
    DISTINTA (login próprio, senha própria, papel `solicitante`, alçada nenhuma). O link
    foi endereçado a `aprovador@…`, cujo papel cobre a faixa de custo do snapshot
    (§11.4). Com a comparação por chave, a sessão do robô de QA decide no lugar do
    aprovador, a alçada conferida na emissão vira decorativa — e a trilha ainda carimba
    `decidido_por` com o e-mail do INOCENTE.

    Aqui a decisão passa a exigir a MESMA CONTA (e-mail normalizado, igualdade exata).
    Nada se perde no caminho legítimo: desde o E03 o link só nasce endereçado a um
    e-mail que TEM conta, e o e-mail da conta é exatamente o que a sessão apresenta.
    """
    repo = app.state.repositorio_os
    jornada_id, os_id, snap = _preparar_snapshot(client, app)

    # 1) o admin cria uma conta cujo login só difere do aprovador pelo rótulo `+`
    vizinha = "aprovador+qa@dev.jornada.local"
    criada = client.post(
        "/api/v1/auth/usuarios",
        json={
            "email": vizinha,
            "nome": "Robô de QA",
            "papeis": ["solicitante"],  # NENHUMA alçada de aprovação (§11.4)
            "senha_provisoria": "provisoria-longa-01",
        },
        headers=_h("dev-admin"),
    )
    assert criada.status_code == 201, criada.text

    # 2) o link vai para o APROVADOR de verdade — o que tem o papel da faixa
    token = client.post(
        f"/api/v1/snapshots/{snap['id']}/link-magico",
        json={"aprovador_email": APROVADOR},
        headers=_h(),
    ).json()["token"]

    # 3) o robô de QA entra com a própria conta (sessão por cookie, §8-M0/G01)
    with TestClient(app, raise_server_exceptions=False) as intruso:
        entrada = intruso.post(
            "/api/v1/auth/login",
            json={"email": vizinha, "senha": "provisoria-longa-01"},
            headers={"X-Tenant": TENANT},
        )
        assert entrada.status_code == 200, entrada.text
        trocou = intruso.post(  # senha provisória nasce expirada (§8-M0)
            "/api/v1/auth/trocar-senha",
            json={"senha_atual": "provisoria-longa-01", "senha_nova": "frase-propria-longa-01"},
            headers={"X-Tenant": TENANT},
        )
        assert trocou.status_code == 200, trocou.text

        # 4) ele LÊ o pacote (é do tenant) mas a própria resposta nega a decisão…
        pagina = intruso.get(f"/api/v1/aprovacao/{token}", headers={"X-Tenant": TENANT})
        assert pagina.status_code == 200, pagina.text
        assert pagina.json()["sessao"]["email"] == vizinha
        assert pagina.json()["sessao"]["pode_decidir"] is False, "conta ≠ pessoa-aproximada"

        # 5) …e a decisão é recusada com o MESMO 403 mudo de qualquer portador indevido
        golpe = intruso.post(
            f"/api/v1/aprovacao/{token}/decidir",
            json={"decisao": "aprovado"},
            headers={"X-Tenant": TENANT},
        )
        assert golpe.status_code == 403, golpe.text
        assert APROVADOR not in golpe.text  # 403 segue sem entregar o e-mail do aprovador

    # 6) nada foi decidido: link virgem, twin não aprovado, trilha limpa
    assert repo.listar_aprovacoes(uuid.UUID(snap["id"]))[0].decisao is None
    assert repo.obter_jornada(jornada_id).estado != "aprovado"
    assert not repo.listar_eventos(os_id=os_id, tipo="snapshot.approved")

    # 7) o caminho legítimo continua aberto — a conta EXATA do link decide
    ok = client.post(
        f"/api/v1/aprovacao/{token}/decidir", json={"decisao": "aprovado"}, headers=_H_APROVADOR
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["decidido_meta"]["sessao_email"] == APROVADOR


# ------------------------------------------------- Contrato das demais rotas §8-M8 (T9)


def test_M8_portoes_e_custo_alcada(client: TestClient, app: FastAPI) -> None:
    """`GET /os/{id}/portoes`: pendente → verde conforme insumos; certificado expirado
    reprova (M5-A3); `enviar-alcada` casa a faixa da política (§11.4)."""
    jornada_id, os_id = _semear_jornada(client, app)
    repo = app.state.repositorio_os

    portoes = client.get(f"/api/v1/os/{os_id}/portoes", headers=_h()).json()["portoes"]
    assert {p["estado"] for p in portoes.values()} == {"pendente"}  # sem insumos

    # certificado EXPIRADO → vermelho (publish M9 recusa — M5-A3)
    agora = datetime.now(UTC)
    repo.adicionar_certificado(
        CertificadoElegibilidade(
            id=uuid.uuid4(),
            os_id=os_id,
            hash="c" * 64,
            suprimidos={"optout": 1_000},
            liquido=VOLUME_LIQUIDO,
            emitido_em=agora - timedelta(days=8),
            valido_ate=agora - timedelta(days=1),
        )
    )
    resposta = client.get(f"/api/v1/os/{os_id}/portoes", headers=_h()).json()
    assert resposta["portoes"]["certificado"]["estado"] == "vermelho"
    # certificado válido mais recente → verde
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

    # sem simulação: enviar custo à alçada → 409 (pré-requisito §6)
    sem_custo = client.post(f"/api/v1/os/{os_id}/custo/enviar-alcada", headers=_h())
    assert sem_custo.status_code == 409
    assert sem_custo.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)

    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h()).status_code
        == 200
    )
    envio = client.post(f"/api/v1/os/{os_id}/custo/enviar-alcada", headers=_h())
    assert envio.status_code == 200, envio.text
    assert envio.json()["faixa"] == {"ate": 100_000, "papel": "lider"}  # §11.4 alcadas

    portoes = client.get(f"/api/v1/os/{os_id}/portoes", headers=_h()).json()["portoes"]
    assert portoes["certificado"]["estado"] == "verde"
    assert portoes["custo_alcada"]["estado"] == "verde"
    assert portoes["governor"] == {
        "estado": "verde",
        "stub": True,
        "colisao_critica": False,
        "motivo": None,
    }
    assert portoes["experimento"]["estado"] == "pendente"  # sem pré-registro


def test_M8_experimento_pre_registro(client: TestClient, app: FastAPI) -> None:
    """`POST /experimentos`: n_minimo CALCULADO no servidor (poder 0,80/α 0,05 — mesmas
    premissas do motor §6); holdout abaixo do `holdout_min` da política → 422."""
    _, os_id = _semear_jornada(client, app)
    resposta = client.post(
        "/api/v1/experimentos",
        json={"os_id": str(os_id), "mde_pp": 1.0, "janela_dias": 14},
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    esperado = n_minimo_por_mde(0.008, 1.0)  # prior conversao_organica v1 (§6)
    assert corpo["experimento"]["n_minimo"] == esperado
    assert corpo["experimento"]["holdout_pct"] == 10.0  # default = holdout_min §11.4
    assert corpo["experimento"]["estado"] == "pre_registrado"
    assert corpo["experimento"]["travado_em"]  # nasce travado (anti-p-hacking)
    assert corpo["poder"]["n_minimo_por_braco"] == esperado
    assert corpo["poder"]["n_holdout_previsto"] == VOLUME_LIQUIDO // 10
    assert corpo["poder"]["suficiente_previsto"] is (VOLUME_LIQUIDO // 10 >= esperado)

    abaixo = client.post(
        "/api/v1/experimentos",
        json={"os_id": str(os_id), "mde_pp": 1.0, "janela_dias": 14, "holdout_pct": 5.0},
        headers=_h(),
    )
    assert abaixo.status_code == 422
    assert abaixo.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)


def test_M8_snapshot_pre_requisitos(client: TestClient, app: FastAPI) -> None:
    """Snapshot exige simulação + previsto congelado (409); hash composto é único —
    repetir sem mudança → 409 (pacote imutável §1.1.1)."""
    jornada_id, os_id = _semear_jornada(client, app)
    payload = {"os_id": str(os_id)}

    sem_simulacao = client.post("/api/v1/snapshots", json=payload, headers=_h())
    assert sem_simulacao.status_code == 409

    client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    sem_previsto = client.post("/api/v1/snapshots", json=payload, headers=_h())
    assert sem_previsto.status_code == 409

    client.post(f"/api/v1/jornadas/{jornada_id}/congelar-previsto", headers=_h())
    criado = client.post("/api/v1/snapshots", json=payload, headers=_h())
    assert criado.status_code == 201, criado.text
    componentes = criado.json()["conteudo"]["componentes"]
    assert set(componentes) == {"jgc", "sql", "criativos", "politica", "custo", "experimento"}
    assert componentes["jgc"]["jornada_id"] == str(jornada_id)

    duplicado = client.post("/api/v1/snapshots", json=payload, headers=_h())
    assert duplicado.status_code == 409
    assert duplicado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
