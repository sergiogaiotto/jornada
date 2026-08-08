"""Aceite §8-M7-B6 (emenda K04 · achado D06) · Salvar o grafo MINTA versão.

Até a onda 7, `PUT /jornadas/{id}/grafo` mutava o MESMO registro (`jornada.grafo = ...`)
e o adapter SQL fazia `on_conflict_do_update`. Uma sessão inteira de edição colapsava
numa linha: o UAT #4 mediu ~25 PUTs virando UMA versão. O twin é a fonte da verdade do
§1.1 e o histórico dele existia só no papel — o dropdown de versões mostrava saltos, sem
os passos que os produziram.

E havia um buraco pior que perder histórico. `criar_snapshot` NÃO muda o estado da
jornada: entre montar o snapshot e a decisão do aprovador, a versão segue `simulado` e
portanto editável. O snapshot guarda o JGC por REFERÊNCIA, e o compilador materializa o
grafo ATUAL carimbado com o hash APROVADO, sem conferir igualdade. Um PUT nessa janela
publicava no SFMC um grafo que ninguém aprovou, com o carimbo de aprovado. Mintar versão
fecha essa janela **por construção**: a versão aprovada deixa de ser alcançável pela
edição, sem precisar de guarda nova em lugar nenhum.

**Por que "o antes" é congelado por HTTP.** O repositório em memória guarda REFERÊNCIA
viva: `obter_jornada(...).grafo` devolve o mesmo objeto que o serviço mutaria, então um
teste que guardasse essa referência compararia o objeto já alterado consigo mesmo e
passaria com o bug intacto. A cópia serializada que vem do `GET` é imune a isso.

A garantia do no-op é tão parte do fecho quanto o minting: sem ela, o D06 encheria o
histórico de versões idênticas a cada auto-save do canvas e zeraria o Ensaio junto —
transformando um conserto em regressão de produto.
"""

import copy
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.acceptance.test_M7 import _gerar_jornada, _grafo_modificado, _h


def _versoes(client: TestClient, os_id: str) -> list[dict[str, Any]]:
    resposta = client.get(f"/api/v1/os/{os_id}/jornadas", headers=_h())
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    return corpo["jornadas"] if isinstance(corpo, dict) else corpo


def test_M7_B6_save_minta_versao_e_nao_toca_na_origem(client: TestClient, app: FastAPI) -> None:
    """O coração do D06: id novo, versão nova, e a ORIGEM byte a byte como estava.

    Inversão: restaurar o bloco antigo (`jornada.grafo = grafo` + `salvar_jornada`)
    mata este teste na releitura da origem E na contagem de versões.
    """
    os_, corpo = _gerar_jornada(client, app)
    v1 = corpo["jornada"]
    # "antes" congelado como CÓPIA SERIALIZADA — ver o docstring sobre aliasing
    antes = copy.deepcopy(client.get(f"/api/v1/jornadas/{v1['id']}", headers=_h()).json())

    salvo = client.put(
        f"/api/v1/jornadas/{v1['id']}/grafo",
        json={"grafo": _grafo_modificado(os_["codigo"])},
        headers=_h(),
    )
    assert salvo.status_code == 200, salvo.text
    nova = salvo.json()["jornada"]

    assert nova["id"] != v1["id"], "o save sobrescreveu a versão em vez de mintar (D06)"
    assert nova["versao"] == v1["versao"] + 1
    assert nova["hash"] != v1["hash"]
    assert nova["estado"] == "rascunho"

    # a origem tem de sair da chamada exatamente como entrou
    depois = client.get(f"/api/v1/jornadas/{v1['id']}", headers=_h()).json()
    assert depois == antes, "a versão de origem foi mutada — o histórico continua sendo destruído"

    versoes = _versoes(client, os_["id"])
    assert len(versoes) == 2, f"esperava 2 versões no histórico, veio {len(versoes)}"
    assert len({v["hash"] for v in versoes}) == 2, "duas versões com o mesmo hash"


def test_M7_B6_save_identico_e_no_op(client: TestClient, app: FastAPI) -> None:
    """Reordenar/reenviar o mesmo grafo NÃO versiona — e não zera o Ensaio.

    O hash é insensível à ordem desde a emenda I03, e o README promete que reordenar o
    desenho não cria versão nem mexe no SFMC. Sem esta guarda, o D06 transformaria cada
    auto-save do canvas numa versão nova e apagaria a simulação junto.

    Inversão: remover o early-return do no-op deixa este teste vermelho — a prova de que
    a guarda não é decorativa.
    """
    os_, corpo = _gerar_jornada(client, app)
    v1 = corpo["jornada"]

    grafo = copy.deepcopy(v1["grafo"])
    grafo["nodes"] = list(reversed(grafo["nodes"]))  # mesmo grafo, outra ordem
    grafo["edges"] = list(reversed(grafo["edges"]))

    salvo = client.put(f"/api/v1/jornadas/{v1['id']}/grafo", json={"grafo": grafo}, headers=_h())
    assert salvo.status_code == 200, salvo.text
    assert salvo.json()["jornada"]["id"] == v1["id"], (
        "grafo idêntico (só reordenado) criou versão nova — o hash canônico do I03 "
        "existe justamente para isto não acontecer"
    )
    assert len(_versoes(client, os_["id"])) == 1, "o histórico ganhou uma versão idêntica"


def test_M7_B6_versao_simulada_de_origem_preserva_o_ensaio(
    client: TestClient, app: FastAPI
) -> None:
    """Editar uma versão simulada não pode apagar o Ensaio DELA.

    Antes, o save mutava o registro e zerava `simulacao`/`previsto` — quem tinha simulado
    e resolvia mexer no grafo perdia a medição da versão anterior, sem aviso. Agora a
    simulação pertence ao grafo que foi simulado: a versão nova nasce sem ela (correto —
    o grafo mudou), e a de origem mantém a sua.
    """
    os_, corpo = _gerar_jornada(client, app)
    v1 = corpo["jornada"]

    # simula direto no repositório: o que se afirma aqui é a preservação, não o motor
    origem = app.state.repositorio_os.obter_jornada(uuid.UUID(v1["id"]))
    origem.simulacao = {"semaforo": "verde", "motivos_semaforo": []}
    origem.estado = "simulado"
    app.state.repositorio_os.salvar_jornada(origem)

    salvo = client.put(
        f"/api/v1/jornadas/{v1['id']}/grafo",
        json={"grafo": _grafo_modificado(os_["codigo"])},
        headers=_h(),
    )
    assert salvo.status_code == 200, salvo.text
    nova = app.state.repositorio_os.obter_jornada(uuid.UUID(salvo.json()["jornada"]["id"]))
    assert nova.simulacao is None, (
        "o grafo mudou: a versão NOVA não pode herdar o Ensaio do grafo antigo (§6)"
    )
    assert nova.estado == "rascunho"

    preservada = app.state.repositorio_os.obter_jornada(uuid.UUID(v1["id"]))
    assert preservada.simulacao is not None, "editar apagou o Ensaio da versão de origem"
    assert preservada.estado == "simulado", "o estado da versão de origem foi rebaixado"
