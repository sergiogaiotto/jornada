"""Aceite §8-M8-A8 (emenda D09) · O vermelho do §6 passa a RECUSAR, não só pintar.

O D08 tirou do VERDE o `frequencySplit` cujas conds não casam com o mix do governor.
Mas parou na cor: `avisos` é `list[str]` sem severidade e `_semaforo` anexava os avisos
DEPOIS do `return "vermelho"`, então nenhum aviso conseguia bloquear. E, mais grave, o
§6 dizia "vermelho bloqueia T9/T11" sem que ninguém lesse a cor: `criar_snapshot` exigia
apenas que a simulação EXISTISSE, qualquer que fosse o resultado.

O efeito prático era o pior tipo de achado — o controle que aparenta existir. Uma jornada
com 100% do volume evaporando num split passava por T9, virava snapshot, ia para
aprovação e para o SFMC, com o painel de portões todo verde.

Este arquivo prova o que o unit do D09 **não pode** provar. `test_D08` mede a COR; aqui
se mede a RECUSA. A distinção é o critério do projeto: *se o teste passaria com o
consumidor removido, ele não fecha nada.* Apagar a recusa de `criar_snapshot` deixa este
arquivo vermelho enquanto todo o unit segue verde — e é essa assimetria que documenta
quem realmente protege.

Três contratos, e o terceiro é tão importante quanto os outros dois:

1. **T9 é recusada** (409) e o motivo nomeia o nó.
2. **T8 NÃO é bloqueada.** O §6 diz T9/T11, não T8. Congelar o previsto de uma simulação
   vermelha continua 200 — legislar além do contrato é o mesmo pecado com o sinal
   trocado. O Ensaio é o lugar de ver o problema, não de ser impedido de medir.
3. **Grafo saudável ainda cria snapshot.** Sem esta direção, o passo poderia ser um
   bloqueio cego que reprova tudo e ninguém perceberia.
"""

import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain.audiencia.modelos import Segmento
from domain.jornada.canonico import hash_jgc
from domain.jornada.modelos import JornadaVersao
from tests.acceptance.test_M8 import PARAMS, VOLUME_LIQUIDO, _criar_os, _grafo, _h

TENANT = "torre-movel"


def _no(id_: str, tipo: str, **data: Any) -> dict[str, Any]:
    return {"id": id_, "type": tipo, "data": data}


def _ar(id_: str, de: str, para: str, **extra: Any) -> dict[str, Any]:
    return {"id": id_, "from": de, "to": para, **extra}


def _grafo_volume_zerado(os_codigo: str) -> dict[str, Any]:
    """O grafo v5 REAL do UAT: classes na forma D05 ('baixa'/'alta').

    O validador aprova (premissa do achado — `test_D08` afirma isso explicitamente), o
    save aceita, e o motor descobre que nenhuma cond casa com o mix do governor.
    """
    return {
        "jgcVersion": "1.0",
        "meta": {"osCodigo": os_codigo, "tenant": TENANT, "reentrada": "nao"},
        "nodes": [
            _no("n1", "entrySource", deRef="DE_x", modo="fire_once", reentrada="nao"),
            _no(
                "fq",
                "frequencySplit",
                classes=[{"id": "baixa", "max": 2}, {"id": "alta", "min": 3}],
                fonte="DE_freq",
            ),
            _no("a", "channel.sms", assetRef="s1", optIn=True),
            _no("b", "channel.push", assetRef="s2", optIn=True),
            _no("n9", "goal", metrica="conversao", deRef="DE_m"),
            _no("n0", "exit", motivo="fim"),
        ],
        "edges": [
            _ar("e1", "n1", "fq"),
            _ar("c0", "fq", "a", cond="baixa"),
            _ar("c1", "fq", "b", cond="alta"),
            _ar("e4", "a", "n9"),
            _ar("e5", "b", "n9"),
            _ar("e6", "n9", "n0"),
        ],
    }


def _semear(client: TestClient, app: FastAPI, grafo_de: Any) -> tuple[uuid.UUID, uuid.UUID]:
    os_ = _criar_os(client)
    os_id = uuid.UUID(os_["id"])
    # o §6 exige segmento recontado como entrada do Ensaio (JGC + segmento + priors)
    app.state.repositorio_os.adicionar_segmento(
        Segmento(
            id=uuid.uuid4(),
            os_id=os_id,
            origem="estudio_sql",
            contagem_bruta=61_000,
            contagem_liquida=VOLUME_LIQUIDO,
            volume_abordagem={"email": {"n": VOLUME_LIQUIDO, "pct": 100.0}},
        )
    )
    jgc = grafo_de(os_["codigo"])
    jornada = JornadaVersao(
        id=uuid.uuid4(),
        os_id=os_id,
        versao=app.state.repositorio_os.proxima_versao(os_id),
        grafo=jgc,
        hash=hash_jgc(jgc),
    )
    app.state.repositorio_os.adicionar_jornada(jornada)
    return jornada.id, os_id


def test_M8_A8_snapshot_recusado_com_simulacao_vermelha(client: TestClient, app: FastAPI) -> None:
    """O contrato inteiro numa sequência: vermelho · T8 livre · T9 recusada.

    Inversão: apagar a recusa em `aprovacao_service.criar_snapshot` deixa este teste
    vermelho enquanto `test_D08` segue verde — a prova documental de que quem protege é
    o consumidor, não a cor.
    """
    jornada_id, os_id = _semear(client, app, _grafo_volume_zerado)

    simulacao = client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    assert simulacao.status_code == 200, simulacao.text
    corpo = simulacao.json()["simulacao"]
    assert corpo["semaforo"] == "vermelho", corpo["motivos_semaforo"]
    assert any("100%" in m and "fq" in m for m in corpo["motivos_semaforo"]), (
        f"o motivo tem de nomear o nó e a perda total — veio {corpo['motivos_semaforo']!r}"
    )

    # T8 NÃO é bloqueada: o §6 diz T9/T11. Medir o desastre é justamente o que o Ensaio
    # serve para fazer; impedir de congelar seria legislar além do contrato.
    congelar = client.post(f"/api/v1/jornadas/{jornada_id}/congelar-previsto", headers=_h())
    assert congelar.status_code == 200, (
        f"o §6 bloqueia T9/T11, nunca T8 — congelar devolveu {congelar.status_code}: "
        f"{congelar.text[:200]}"
    )

    # T9 é recusada, e o motivo chega a quem clicou
    snapshot = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=_h())
    assert snapshot.status_code == 409, (
        f"snapshot de jornada que não entrega nada foi ACEITO ({snapshot.status_code}) — "
        "o vermelho voltou a ser decorativo"
    )
    assert "VERMELHA" in snapshot.text and "fq" in snapshot.text, snapshot.text[:300]


def test_M8_A8_portao_simulacao_aparece_no_painel(client: TestClient, app: FastAPI) -> None:
    """Portão que não aparece no painel é limite ESCONDIDO — doutrina do projeto.

    Sem esta linha o operador veria os quatro portões verdes e levaria o 409 na cara ao
    clicar em criar snapshot, sem nenhuma pista de onde está o problema.

    Inversão: remover `"simulacao": self._portao_simulacao(os_)` de `portoes` reprova.
    """
    jornada_id, os_id = _semear(client, app, _grafo_volume_zerado)

    # antes de simular: PENDENTE, não verde — ausência de medida nunca é aprovação
    painel = client.get(f"/api/v1/os/{os_id}/portoes", headers=_h()).json()
    assert painel["portoes"]["simulacao"]["estado"] == "pendente", painel["portoes"]

    client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())

    painel = client.get(f"/api/v1/os/{os_id}/portoes", headers=_h()).json()
    simulacao = painel["portoes"]["simulacao"]
    assert simulacao["estado"] == "vermelho", painel["portoes"]
    assert "100%" in simulacao["motivo"], simulacao["motivo"]
    # e os quatro portões antigos continuam existindo, intactos
    for antigo in ("certificado", "experimento", "custo_alcada", "governor"):
        assert antigo in painel["portoes"], f"o portão {antigo} sumiu do painel"


def test_M8_A8_grafo_saudavel_ainda_cria_snapshot(client: TestClient, app: FastAPI) -> None:
    """Guarda-corpo na direção contrária: o fecho não pode virar bloqueio cego.

    Usa o grafo do M8 (randomSplit + holdout, sem frequencySplit) — o mesmo caminho
    feliz que o resto da suíte exercita. Se esta linha ficar vermelha, a regra do D09
    vazou para grafos que ela não deveria tocar.
    """
    jornada_id, os_id = _semear(client, app, _grafo)

    simulacao = client.post(f"/api/v1/jornadas/{jornada_id}/simular", json=PARAMS, headers=_h())
    assert simulacao.status_code == 200, simulacao.text
    corpo = simulacao.json()["simulacao"]
    assert corpo["bloqueantes"] == [], f"grafo saudável ganhou bloqueante: {corpo['bloqueantes']!r}"
    assert corpo["semaforo"] != "vermelho", corpo["motivos_semaforo"]

    assert (
        client.post(f"/api/v1/jornadas/{jornada_id}/congelar-previsto", headers=_h()).status_code
        == 200
    )
    snapshot = client.post("/api/v1/snapshots", json={"os_id": str(os_id)}, headers=_h())
    assert snapshot.status_code == 201, (
        f"o caminho feliz parou de criar snapshot ({snapshot.status_code}) — o D09 "
        f"virou bloqueio cego: {snapshot.text[:300]}"
    )
