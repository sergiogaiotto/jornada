"""Regressão do UAT #5 achado 3 (docs/UAT5-2026-08-06-cacada.md) — D07 pela metade.

A emenda D07 criou `domain/jornada/adjacencia.saidas_do_grafo()` como fonte ÚNICA da
adjacência do JGC e converteu validação (§5.3), taxímetro (§8-M7) e motor (§6) — mas
`compilar_recursos` (§5.4) e `preview_do_no` (§8-M7) ficaram com a QUARTA cópia, a que
itera SÓ `edges`. Todo `decisionSplit` roteado por `data.regras[].to` (a forma que a
seed da OS demo usa no n13, §11.4) saía do compilador com `outcomes: []`:

- o export (JSON nativo do JB e XML de auditoria — §8-M7) importa o Decision Split sem
  nenhuma saída e os nós a jusante (push, SMS, WhatsApp, goal) ficam órfãos;
- `compilador_service` (plan/apply), `prevoo_service` e `drift_service` reaproveitam
  `compilar_recursos`, logo o drift comparava contra o payload JÁ ERRADO e diria
  "em_sincronia" com a jornada quebrada.

Falso verde do CI: o `JGC_GOLDEN` do M9-A2 não tinha nenhum `decisionSplit` — daí o
golden ganhar aqui um braço roteado por regra E um roteado por aresta `cond`.
"""

import copy
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from lxml import etree

from adapters.aleatorio import rng_disponivel
from adapters.demo_seeds import _grafo_demo
from application.services.compilador_service import _payload_contido
from domain.jornada.adjacencia import saidas_do_grafo
from domain.jornada.canonico import hash_jgc
from domain.jornada.compilador import compilar_recursos
from domain.jornada.drift import avaliar_recurso
from domain.jornada.exportacao import export_json, export_xml
from domain.jornada.sfmc_preview import external_key, preview_do_no
from domain.jornada.taximetro import calcular
from domain.jornada.validacao import validar_grafo
from domain.simulacao.motor import simular

PRIORS: dict[str, Any] = {
    "entrega": {"email": 0.95, "sms": 0.98, "push": 0.9},
    "abertura": {"email": 0.25},
    "conversao": {"email": 0.03, "sms": 0.02, "push": 0.02},
    "ticket_medio": 120.0,
    "organico": 0.01,
}
TARIFAS = {"email": Decimal("0.0018"), "sms": Decimal("0.0005"), "push": Decimal("0.0001")}
GERADO_EM = datetime(2026, 8, 6, tzinfo=UTC)  # ClockPort fixo: o XML é determinístico
XSD_PATH = Path(__file__).resolve().parents[2] / "domain" / "jornada" / "journey_export.xsd"


def _journey(grafo: dict[str, Any], hash_: str) -> dict[str, Any]:
    """Payload do recurso `journey` (interaction) compilado — §5.4.1."""
    return next(r for r in compilar_recursos(grafo, hash_) if r["tipo_sfmc"] == "journey")[
        "payload"
    ]


def _atividade(grafo: dict[str, Any], hash_: str, no_id: str) -> dict[str, Any]:
    chave = external_key(hash_, no_id)
    return next(a for a in _journey(grafo, hash_)["activities"] if a["key"] == chave)


# ------------------------------------------------- a jornada publicada da OS demo
def test_achado3_decision_split_da_os_demo_sai_com_outcomes() -> None:
    """`n13` rotea SÓ por `regras[].to` (seed §11.4) — saía do compilador com []."""
    grafo = _grafo_demo()
    hash_ = hash_jgc(grafo)
    atividade = _atividade(grafo, hash_, "n13")

    assert atividade["type"] == "decisionSplit"
    assert [o["next"] for o in atividade["outcomes"]] == [
        external_key(hash_, "n5"),  # abriu_email == false → push
        external_key(hash_, "n6"),  # senão → wait → SMS → WhatsApp → goal
    ]
    assert [o["cond"] for o in atividade["outcomes"]] == ["abriu_email == false", "senao"]


def test_achado3_export_json_da_os_demo_leva_as_saidas() -> None:
    """`GET /jornadas/{id}/export?formato=json` é o import nativo do JB (§8-M7)."""
    grafo = _grafo_demo()
    hash_ = hash_jgc(grafo)
    spec = json.loads(export_json(grafo, hash_))
    atividade = next(a for a in spec["activities"] if a["key"] == external_key(hash_, "n13"))
    assert atividade["outcomes"], "decisionSplit exportado sem nenhuma saída (achado 3)"


def test_achado3_export_xml_da_os_demo_leva_as_saidas() -> None:
    """O XML de auditoria herda de `montar_interaction` — mesma origem, mesmo fix."""
    grafo = _grafo_demo()
    hash_ = hash_jgc(grafo)
    xml = export_xml(grafo, hash_, versao=1, gerado_em=GERADO_EM).decode()
    depois = xml.split(f'<Activity key="{external_key(hash_, "n13")}"', 1)[1]
    bloco = depois.split("</Activity>", 1)[0]
    assert "<Outcomes/>" not in bloco, "Decision Split exportado em XML sem saídas (achado 3)"
    assert f'next="{external_key(hash_, "n5")}"' in bloco


def test_achado3_preview_do_no_mostra_as_saidas() -> None:
    """`GET /jornadas/{id}/no/{noId}/sfmc-preview` (§8-M7) tinha a MESMA cópia."""
    grafo = _grafo_demo()
    preview = preview_do_no(grafo, hash_jgc(grafo), "n13")
    assert [s["to"] for s in preview["payload"]["outcomes"]] == ["n5", "n6"]


# ------------------------------- fonte única: os quatro consumidores, mesmo grafo
def _grafo_das_duas_formas() -> dict[str, Any]:
    """As DUAS formas de roteamento do `decisionSplit` (§5.2) no mesmo grafo:

    `d1` rotea por `data.regras[].to` (forma da seed demo e do que o Flow gera);
    `d2` rotea por aresta com `cond` (forma do JGC "clássico", regra sem `to`).
    """
    return {
        "jgcVersion": "1.0",
        "meta": {"osCodigo": "OS-2026-0457", "tenant": "torre-movel", "reentrada": "nao"},
        "nodes": [
            {
                "id": "n1",
                "type": "entrySource",
                "data": {"deRef": "DE_x", "modo": "fire_once", "reentrada": "nao"},
            },
            {
                "id": "d1",
                "type": "decisionSplit",
                "data": {
                    "regras": [
                        {"expr": "abriu_email == false", "to": "n3"},
                        {"expr": "senao", "to": "d2"},
                    ]
                },
            },
            {"id": "n3", "type": "channel.push", "data": {"assetRef": "ast-push", "optIn": True}},
            {
                "id": "d2",
                "type": "decisionSplit",
                "data": {"regras": [{"id": "vip", "cond": "score > 90"}, {"id": "resto"}]},
            },
            {"id": "n4", "type": "channel.sms", "data": {"assetRef": "ast-sms", "optIn": True}},
            {"id": "n9", "type": "goal", "data": {"metrica": "conversao", "deRef": "DE_m"}},
            {"id": "n0", "type": "exit", "data": {"motivo": "fim"}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "d1", "cond": None},
            {"id": "e2", "from": "n3", "to": "d2", "cond": None},
            {"id": "e3", "from": "d2", "to": "n4", "cond": "vip"},
            {"id": "e4", "from": "d2", "to": "n9", "cond": "resto"},
            {"id": "e5", "from": "n4", "to": "n9", "cond": None},
            {"id": "e6", "from": "n9", "to": "n0", "cond": None},
        ],
    }


def test_achado3_compilador_ve_exatamente_a_adjacencia_da_fonte_unica() -> None:
    """Compilador == `saidas_do_grafo` par a par (menos entrySource: vira trigger)."""
    grafo = _grafo_das_duas_formas()
    hash_ = hash_jgc(grafo)
    entradas = {n["id"] for n in grafo["nodes"] if n["type"] == "entrySource"}
    esperado = {
        no_id: {(str(s["id"]), str(s["to"]), s.get("cond")) for s in saidas}
        for no_id, saidas in saidas_do_grafo(grafo).items()
        if no_id not in entradas
    }
    obtido = {
        a["key"].rsplit("-", 1)[1]: {
            (str(o["key"]), str(o["next"]).rsplit("-", 1)[1], o["cond"]) for o in a["outcomes"]
        }
        for a in _journey(grafo, hash_)["activities"]
        if a["outcomes"]
    }
    assert obtido == esperado


def test_achado3_taximetro_motor_validador_e_compilador_veem_as_mesmas_saidas() -> None:
    """Os nós só alcançáveis por `regras[].to` (n3) e por aresta `cond` (n4) têm de
    existir para os QUATRO consumidores — ou o twin cobra e projeta o que não dispara.
    """
    grafo = _grafo_das_duas_formas()
    hash_ = hash_jgc(grafo)

    # validador (§5.3): nada órfão pelas duas formas
    assert validar_grafo(grafo) == []

    # taxímetro (§8-M7-A2): os dois canais recebem volume
    custo, memoria, _ = calcular(grafo, volume_entrada=1000, tarifas=TARIFAS)
    volumes = {linha["no"]: linha["volume"] for linha in memoria}
    assert volumes["n3"] > 0 and volumes["n4"] > 0
    assert custo > 0

    # motor Monte Carlo (§6): os dois canais recebem tráfego
    funil = simular(
        grafo,
        volume_entrada=1000,
        personas={},
        priors=PRIORS,
        tarifas=TARIFAS,
        politica={},
        ger=rng_disponivel().gerador(42),
        runs=20,
        ticket_medio=120.0,
        hora_inicio=9.0,
    )["funil"]
    assert funil["n3"]["p50"] > 0 and funil["n4"]["p50"] > 0

    # compilador (§5.4): os dois splits saem com as saídas que a fonte única enxerga
    for no_id in ("d1", "d2"):
        atividade = _atividade(grafo, hash_, no_id)
        assert len(atividade["outcomes"]) == 2, f"{no_id} compilado sem as duas saídas"
    assert {o["next"] for o in _atividade(grafo, hash_, "d1")["outcomes"]} == {
        external_key(hash_, "n3"),
        external_key(hash_, "d2"),
    }


# ------------------------------- auditoria do achado 3: os consumidores A JUSANTE
# O relatório (§"o que esta caçada NÃO cobriu") registra que o impacto sobre plan/
# apply e drift foi INFERIDO do código, nunca medido. As três checagens abaixo medem
# — e caem junto com o compilador se a cópia inline voltar.
def _journey_do_sfmc_sem_saidas(grafo: dict[str, Any], hash_: str, no_id: str) -> dict[str, Any]:
    """Estado "real" do SFMC: a MESMA interaction, mas com o split sem saída nenhuma —
    exatamente o payload que o twin mandava ao JB antes do fix."""
    real = copy.deepcopy(_journey(grafo, hash_))
    for atividade in real["activities"]:
        if atividade["key"] == external_key(hash_, no_id):
            atividade["outcomes"] = []
    return real


def test_achado3_export_xml_com_saida_de_regra_valida_contra_o_xsd() -> None:
    """A saída derivada de regra tem `key` sintético `{no}:{to}` (adjacencia.py) — o
    XSD do export (§8-M7-B5) só é exercido pelo `_grafo` do M7, que não tem NENHUM
    `decisionSplit`: sem esta checagem, o contrato do XML nunca viu a forma nova."""
    grafo = _grafo_demo()
    hash_ = hash_jgc(grafo)
    documento = etree.fromstring(export_xml(grafo, hash_, versao=1, gerado_em=GERADO_EM))
    etree.XMLSchema(etree.parse(str(XSD_PATH))).assertValid(documento)
    chaves = documento.xpath("//Outcome/@key")
    assert "n13:n5" in chaves and "n13:n6" in chaves


def test_achado3_drift_flagra_o_journey_que_perdeu_as_saidas_no_sfmc() -> None:
    """§5.4.5: `journey` compara o campo `activities` — com o compilador torto, o
    esperado JÁ vinha sem saídas e o monitor diria `em_sincronia` com a jornada
    quebrada no JB (o cenário exato do achado 3)."""
    grafo = _grafo_demo()
    hash_ = hash_jgc(grafo)
    check = avaliar_recurso(
        snapshot_id=uuid.uuid4(),
        ambiente="prod",
        tipo_sfmc="journey",
        external_key=f"jrn-{hash_[:12]}",
        payload_esperado=_journey(grafo, hash_),
        estado_real=_journey_do_sfmc_sem_saidas(grafo, hash_, "n13"),
        agora=GERADO_EM,
    )
    assert check.estado == "drift_sfmc", "drift cego ao Decision Split sem saídas (achado 3)"
    assert "activities" in check.diff["campos"]


def test_achado3_plan_marca_alterar_quando_o_sfmc_esta_sem_as_saidas() -> None:
    """§5.4.1: `plan` decide criar/alterar/manter por `_payload_contido`. Com o
    compilador torto o plano diria `manter` — o apply nunca reconvergiria o split."""
    grafo = _grafo_demo()
    hash_ = hash_jgc(grafo)
    assert not _payload_contido(
        _journey(grafo, hash_), _journey_do_sfmc_sem_saidas(grafo, hash_, "n13")
    ), "plan diria `manter` para um Decision Split órfão no SFMC (achado 3)"
