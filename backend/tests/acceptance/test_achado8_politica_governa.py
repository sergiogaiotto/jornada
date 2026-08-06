"""Achado 8 do UAT #5 (docs/UAT5-2026-08-06-cacada.md) — a tela de Políticas passa a
GOVERNAR de fato.

O que estava provado no achado: publicar política v2 com `holdout_min=40` e o
`PUT /segmentos/{id}/holdout {"holdout_pct": 15}` respondia **200**; publicar `alcadas`
novas e o `/custo/enviar-alcada` devolvia a faixa da CONSTANTE; publicar `frequency_cap`
novo e a simulação seguia com o antigo. Uma única rota (`api/v1/validacao.py`) lia o
banco — e nem essa fechava o ciclo, porque o snapshot assinava `politica.versao` da
constante enquanto o GO congelava `frozen.policy_version` do banco: o mesmo artefato
assinado com duas versões.

Este arquivo é o ACEITE do fechamento, um teste por eixo (holdout · alçadas ·
frequency cap) mais a consistência do artefato assinado. Cada teste passa pelo estado
ANTES da publicação — o 200 que o achado descreve — e só então publica a v2 e cobra a
mudança de comportamento. Sem esse "antes", o teste não distingue política que governa
de coincidência de valores.

Nada aqui usa LLM em caminho de veredito (§10.6): política, alçada, holdout e o motor
§6 são 100% código.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import DEV_TOKENS, Usuario
from app.errors import PROBLEM_CONTENT_TYPE
from application.ports.publicacoes import ORIGEM_PUBLICADA, ORIGEM_SEED
from domain.audiencia.modelos import Segmento
from domain.jornada.canonico import hash_jgc
from domain.jornada.modelos import JornadaVersao
from tests.conftest import TENANT_ALHEIO

TENANT = "torre-movel"
VOLUME_LIQUIDO = 50_000
PARAMS = {"seed": 42, "runs": 40, "n_personas": 300}  # rápido; §6 de perf não é daqui

# Briefing com fonte nas fixtures (§11) — pré-condição do GO (mesma do test_M4/M12).
BRIEFING_COM_FONTE: dict[str, Any] = {
    "publico": {"valor": "Pós-pago sem 5G", "inferido": False},
    "verba": {"valor": 250_000.0, "inferido": False},
}


def _h(token: str = "dev-analista", tenant: str = TENANT) -> dict[str, str]:
    return {"X-Tenant": tenant, "Authorization": f"Bearer {token}"}


def _grafo(os_codigo: str, tenant: str = TENANT) -> dict[str, Any]:
    """JGC §5 válido: entrada → randomSplit 90/10 → wait → e-mail → goal; holdout sai."""
    return {
        "jgcVersion": "1.0",
        "meta": {
            "osCodigo": os_codigo,
            "tenant": tenant,
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


def _criar_os(
    client: TestClient,
    *,
    briefing: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    resposta = client.post(
        "/api/v1/os",
        json={
            "nome": "Upgrade Pós-Pago 5G",
            "tshirt": "G",
            "briefing": briefing if briefing is not None else BRIEFING_COM_FONTE,
        },
        headers=headers or _h(),
    )
    assert resposta.status_code == 201, resposta.text
    return dict(resposta.json())


def _executar_go(
    client: TestClient, os_: dict[str, Any], *, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """Fluxo M4 até o GO — é ele que grava `frozen.policy_version` (§8-M4-A2)."""
    h = headers or _h()
    assert (
        client.post(f"/api/v1/os/{os_['id']}/fase", json={"fase": "discutida"}, headers=h)
    ).status_code == 200
    for campo in BRIEFING_COM_FONTE:
        assert (
            client.post(f"/api/v1/os/{os_['id']}/validacoes/{campo}", headers=h)
        ).status_code == 201
    go = client.post(f"/api/v1/os/{os_['id']}/go", headers=h)
    assert go.status_code == 200, go.text
    return dict(go.json()["os"])


def _semear_segmento_e_jornada(
    client: TestClient, app: FastAPI, os_: dict[str, Any], *, tenant: str = TENANT
) -> tuple[uuid.UUID, uuid.UUID]:
    """Segmento recontado + versão do twin direto no repo (mesmo atalho do test_M8)."""
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
    jgc = _grafo(os_["codigo"], tenant)
    jornada = JornadaVersao(
        id=uuid.uuid4(),
        os_id=os_id,
        versao=repo.proxima_versao(os_id),
        grafo=jgc,
        hash=hash_jgc(jgc),
        premissas=[],
        custo_projetado=0.0,
        created_at=datetime.now(UTC),
    )
    repo.salvar_jornada(jornada)
    return jornada.id, os_id


def _publicar_politica(client: TestClient, **mudancas: Any) -> int:
    """Publica uma nova versão da política pela ROTA REAL do M12 (draft + publicar).

    Parte do `conteudo` publicado vigente e só troca o que o teste quer provar — o
    conjunto de campos é FECHADO (§4.1) e um draft incompleto morreria em 422 antes de
    chegar ao ponto. Publicar exige `lider` (§8-M0).
    """
    atual = client.get("/api/v1/policies", headers=_h()).json()["publicada"]
    conteudo = {**atual["conteudo"], **mudancas}
    draft = client.post("/api/v1/policies", json={"conteudo": conteudo}, headers=_h())
    assert draft.status_code == 201, draft.text
    publicada = client.post(
        f"/api/v1/policies/{draft.json()['id']}/publicar", headers=_h("dev-lider")
    )
    assert publicada.status_code == 200, publicada.text
    versao: int = publicada.json()["versao"]
    return versao


# ------------------------------------------------------------------ eixo 1: holdout
def test_achado8_holdout_min_publicado_passa_a_reprovar(client: TestClient, app: FastAPI) -> None:
    """Publicar `holdout_min=40` e o PUT de holdout 15 vira 422 — antes era 200.

    Este é o caso LITERAL do achado 8. A prova depende do "antes": com a v1 publicada
    (holdout_min 10) o MESMO PUT de 15 passa, então o 422 posterior só pode vir da
    política nova, não de uma régua qualquer que já reprovasse 15.
    """
    os_ = _criar_os(client)
    _semear_segmento_e_jornada(client, app, os_)
    segmento_id = app.state.repositorio_os.listar_segmentos(uuid.UUID(os_["id"]))[0].id
    caminho = f"/api/v1/segmentos/{segmento_id}/holdout"

    # v1 publicada (§11.4): holdout_min = 10 → 15 é legítimo
    antes = client.put(caminho, json={"holdout_pct": 15.0}, headers=_h())
    assert antes.status_code == 200, antes.text
    assert antes.json()["holdout_pct"] == 15.0

    assert _publicar_politica(client, holdout_min=40.0) == 2

    depois = client.put(caminho, json={"holdout_pct": 15.0}, headers=_h())
    assert depois.status_code == 422, depois.text  # ANTES DO FIX: 200
    assert depois.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "40" in depois.json()["detail"], depois.json()

    # e o que a v2 permite continua passando: a régua mudou, não travou
    acima = client.put(caminho, json={"holdout_pct": 45.0}, headers=_h())
    assert acima.status_code == 200, acima.text
    assert acima.json()["holdout_pct"] == 45.0


# ------------------------------------------------------------------ eixo 2: alçadas
def test_achado8_faixa_de_alcada_vem_da_politica_publicada(
    client: TestClient, app: FastAPI
) -> None:
    """Publicar `alcadas` novas e `/custo/enviar-alcada` devolve a faixa da v2.

    O eixo mais perigoso dos três: alçada é quem PODE aprovar gasto. Com a constante,
    reorganizar a escada de aprovação na tela não mudava nem o e-mail que recebia o
    link mágico, nem o papel exigido — governança de verba puramente decorativa.
    """
    os_ = _criar_os(client)
    jornada_id, os_id = _semear_segmento_e_jornada(client, app, os_)
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    ).status_code == 200

    # v1 (§11.4): [{ate: 100.000, lider}, {ate: 1.000.000, aprovador}] → custo cai na 1ª
    antes = client.post(f"/api/v1/os/{os_id}/custo/enviar-alcada", headers=_h())
    assert antes.status_code == 200, antes.text
    assert antes.json()["faixa"] == {"ate": 100_000, "papel": "lider"}

    # v2: a primeira faixa vira irrisória — qualquer custo real escala para `aprovador`
    assert (
        _publicar_politica(
            client,
            alcadas=[
                {"ate": 0.01, "papel": "lider"},
                {"ate": 9_999_999, "papel": "aprovador"},
            ],
        )
        == 2
    )

    depois = client.post(f"/api/v1/os/{os_id}/custo/enviar-alcada", headers=_h())
    assert depois.status_code == 200, depois.text
    assert depois.json()["faixa"] == {"ate": 9_999_999, "papel": "aprovador"}  # era `lider`

    # o painel de portões (T9) lê a MESMA fonte — tela e portão não podem divergir
    portoes = client.get(f"/api/v1/os/{os_id}/portoes", headers=_h()).json()["portoes"]
    assert portoes["custo_alcada"]["faixa"] == {"ate": 9_999_999, "papel": "aprovador"}


# ----------------------------------------------------------- eixo 3: frequency cap
def test_achado8_simulacao_usa_o_frequency_cap_publicado(client: TestClient, app: FastAPI) -> None:
    """Publicar `frequency_cap` novo e o Ensaio Geral (§6) passa a usá-lo.

    A pressão de contato por canal é comparada contra o cap da política dentro do motor
    (`pressao_contato[canal].cap_janela` / `colisao_critica`). Com a constante, apertar
    o cap de e-mail na tela não mudava um número sequer da simulação — e é a simulação
    que alimenta o portão do governor no T9.
    """
    os_ = _criar_os(client)
    jornada_id, _ = _semear_segmento_e_jornada(client, app, os_)

    antes = client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    assert antes.status_code == 200, antes.text
    pressao_antes = antes.json()["simulacao"]["pressao_contato"]["email"]
    assert pressao_antes["cap_janela"] == 4  # §11.4 v1: e-mail 4 por janela de 7 dias

    assert (
        _publicar_politica(
            client,
            frequency_cap={"email": 0, "sms": 2, "push": 5, "whatsapp": 2, "janela_dias": 7},
        )
        == 2
    )

    depois = client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    assert depois.status_code == 200, depois.text
    pressao_depois = depois.json()["simulacao"]["pressao_contato"]["email"]
    assert pressao_depois["cap_janela"] == 0  # era 4 — a MESMA jornada, mesma seed
    # o cap novo não é só exibido: reprova a pressão que antes passava
    assert pressao_antes["colisao_critica"] is False
    assert pressao_depois["colisao_critica"] is True


# ------------------------------------- consistência do artefato assinado (frozen ↔ snapshot)
def test_achado8_snapshot_assina_a_versao_congelada_no_go(client: TestClient, app: FastAPI) -> None:
    """O pacote assinado cita a MESMA versão de política que o GO congelou.

    Era o segundo furo do achado 8: `validacao_service` congelava
    `frozen.policy_version` do BANCO e `aprovacao_service` gravava `politica.versao` da
    CONSTANTE. Com a v1 nas duas fontes ninguém percebia — o desencontro só aparece
    depois de publicar a v2, que é exatamente o cenário deste teste: a OS em voo segue
    na v1 (§8-M12-A2) e o snapshot tem que assinar a v1, não a v2 recém-publicada.
    """
    os_ = _executar_go(client, _criar_os(client))
    assert os_["frozen"]["policy_version"] == 1
    jornada_id, os_id = _semear_segmento_e_jornada(client, app, os_)
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    ).status_code == 200
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/congelar-previsto", headers=_h())
    ).status_code == 200

    # publica a v2 DEPOIS do GO: a OS em voo não muda de versão (simetria §8-M12-A2)
    assert _publicar_politica(client, holdout_min=40.0) == 2
    congelada = client.get(f"/api/v1/os/{os_id}", headers=_h()).json()["frozen"]["policy_version"]
    assert congelada == 1

    snapshot = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=_h())
    assert snapshot.status_code == 201, snapshot.text
    politica = snapshot.json()["conteudo"]["componentes"]["politica"]
    assert politica["versao"] == congelada  # ANTES DO FIX: 1 no frozen, constante no pacote
    assert politica["conteudo"]["holdout_min"] == 10.0  # conteúdo da v1, não da v2

    # …e é o relatório de policy drift (§8-M12) que denuncia o atraso — não o silêncio
    # de um snapshot que trocasse de política sozinho.
    drift = client.get("/api/v1/policies/drift", headers=_h()).json()
    assert drift["policy_publicada"] == 2
    assert [e["os_id"] for e in drift["em_drift"]] == [str(os_id)]
    assert [v["regra"] for v in drift["em_drift"][0]["violacoes"]] == ["holdout_min"]


# ---------------------------------- colisão de numeração entre o seed e a v1 do tenant
@pytest.fixture()
def lider_alheio(monkeypatch: pytest.MonkeyPatch) -> str:
    """Líder REAL de `outra-torre` — publicar política exige o papel (§8-M0), e forjar
    o `X-Tenant` é exatamente o que o fix do achado 5 proíbe."""
    token = "dev-lider-outra-torre"
    monkeypatch.setitem(
        DEV_TOKENS,
        token,
        Usuario(
            id=uuid.uuid5(uuid.NAMESPACE_URL, "jornada/dev/lider/outra-torre"),
            tenant_id=TENANT_ALHEIO,
            nome="Líder (outra torre)",
            email="lider@outra-torre.local",
            papeis=("analista", "lider"),
        ),
    )
    return token


def test_achado8_tenant_sem_seed_nao_assina_a_v1_do_banco(
    client: TestClient, app: FastAPI, lider_alheio: str
) -> None:
    """O número da política NÃO basta para identificar o que governou a OS.

    Só `default_tenant` recebe `semear_politicas` (§11.4 — `api/v1/plataforma.py`), então
    um tenant novo entra em produção com ZERO linhas em `policy_versao` e é governado
    pelo SEED. O GO congela `policy_version=1` vindo dele. Quando esse tenant publica a
    PRIMEIRA política pela T16, a versão nasce `max(existentes)+1` = **1** — o mesmo
    número, conteúdo diferente.

    Sem a ORIGEM congelada, `politica_versionada(1, tenant)` encontrava a v1 do BANCO e
    o pacote assinado carimbava um `holdout_min` que nunca governou aquela OS: o achado
    8 de volta (duas fontes para o mesmo carimbo), agora por colisão de numeração em vez
    de constante compilada. Medido antes do fix: `politica.conteudo.holdout_min == 40.0`
    num pacote cuja OS foi congelada sob o seed (10.0).
    """
    h = _h(lider_alheio, TENANT_ALHEIO)

    # o tenant novo não tem NENHUMA linha de política — quem governa é o seed §11.4
    assert client.get("/api/v1/policies", headers=h).json()["policies"] == []

    os_ = _executar_go(client, _criar_os(client, headers=h), headers=h)
    assert os_["frozen"]["policy_version"] == 1
    assert os_["frozen"]["policy_origem"] == ORIGEM_SEED  # e NÃO uma linha de banco

    jornada_id, os_id = _semear_segmento_e_jornada(client, app, os_, tenant=TENANT_ALHEIO)
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=h)
    ).status_code == 200
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/congelar-previsto", headers=h)
    ).status_code == 200

    # a PRIMEIRA política do tenant nasce v1 — mesmo número que o GO congelou do seed
    draft = client.post(
        "/api/v1/policies",
        json={"conteudo": {**_conteudo_seed(client), "holdout_min": 40.0}},
        headers=h,
    )
    assert draft.status_code == 201, draft.text
    publicada = client.post(f"/api/v1/policies/{draft.json()['id']}/publicar", headers=h)
    assert publicada.status_code == 200, publicada.text
    assert publicada.json()["versao"] == 1  # a colisão

    # a partir daqui a v1 do BANCO governa de fato (é o objetivo da frente)…
    segmento_id = app.state.repositorio_os.listar_segmentos(os_id)[0].id
    reprovado = client.put(
        f"/api/v1/segmentos/{segmento_id}/holdout", json={"holdout_pct": 15.0}, headers=h
    )
    assert reprovado.status_code == 422, reprovado.text

    # …mas o pacote assinado continua citando o que REALMENTE governou no GO: o seed.
    snapshot = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=h)
    assert snapshot.status_code == 201, snapshot.text
    politica = snapshot.json()["conteudo"]["componentes"]["politica"]
    assert politica["versao"] == 1
    assert politica["conteudo"]["holdout_min"] == 10.0, (
        "ANTES DO FIX: 40.0 — o pacote assinava a v1 do banco, que nunca governou esta OS"
    )


def test_achado8_origem_publicada_quando_o_tenant_tem_linha_no_banco(
    client: TestClient, app: FastAPI
) -> None:
    """Contraprova do teste acima: com linha real em `policy_versao`, a origem congelada
    é `policy_versao` e a busca do pacote passa pelo BANCO — o desvio do seed é
    estreito, não um atalho que desliga a consulta."""
    _publicar_politica(client, holdout_min=12.0)  # v2 real no banco do tenant semeado
    os_ = _executar_go(client, _criar_os(client))
    assert os_["frozen"]["policy_version"] == 2
    assert os_["frozen"]["policy_origem"] == ORIGEM_PUBLICADA

    jornada_id, os_id = _semear_segmento_e_jornada(client, app, os_)
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    ).status_code == 200
    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/congelar-previsto", headers=_h())
    ).status_code == 200

    snapshot = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=_h())
    assert snapshot.status_code == 201, snapshot.text
    politica = snapshot.json()["conteudo"]["componentes"]["politica"]
    assert (politica["versao"], politica["conteudo"]["holdout_min"]) == (2, 12.0)


def _conteudo_seed(client: TestClient) -> dict[str, Any]:
    """Conteúdo vigente do tenant semeado — base fechada (§4.1) para montar o draft do
    tenant novo sem repetir o seed §11.4 dentro do teste."""
    return dict(client.get("/api/v1/policies", headers=_h()).json()["publicada"]["conteudo"])
