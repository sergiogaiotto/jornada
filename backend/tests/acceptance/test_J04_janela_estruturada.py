"""J04 (onda 6) — a janela ESTRUTURADA liga o `wait_alem_da_janela` (fecho do D04).

O D04 registrou: a regra existia, testada, e NENHUM chamador de produção passava
`janela_oferta_dias` — código morto, porque a janela vivia como texto livre no
briefing e derivá-la por parser seria inventar semântica (§1.3.5). Agora o briefing
aceita `janela_inicio`/`janela_fim` (ISO, opcionais) e todos os chamadores derivam a
janela deles (`domain/intake/janela.py`).

INVERSÃO (verificada): remover o argumento `janela_oferta_dias=janela_oferta_dias(...)`
do `_validar` de jornada_service deixa `test_J04_wait_maior_que_a_janela_e_422`
vermelho; removê-lo do `_rodar` de simulador_service deixa o caso do simular vermelho.
Sem os campos no briefing, TUDO se comporta como antes do J04 (contra-prova no último
teste — o mesmo grafo salva 201).
"""

import uuid
from typing import Any

from fastapi import FastAPI
from starlette.testclient import TestClient

from adapters.llm.fake import LLMFake
from agents import consultor as agente_consultor
from domain.audiencia.modelos import Segmento
from domain.intake.janela import janela_oferta_dias
from domain.jornada.validacao import validar_grafo

TENANT = "torre-movel"


def _h(token: str = "dev-analista") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ helper puro
def test_J04_helper_deriva_dias_da_janela_estruturada() -> None:
    briefing = {
        "janela_inicio": {"valor": "2026-07-01", "inferido": False},
        "janela_fim": {"valor": "2026-08-15", "inferido": True},
    }
    assert janela_oferta_dias(briefing) == 45.0  # convenção fixada: (fim - início).days


def test_J04_helper_e_tolerante_como_o_precedente_do_simulador() -> None:
    """Coerção tolerante (o `_numero` da verba é o gabarito): o que não parseia vira
    None — regra inerte, nunca 500, nunca bloqueio por dado torto."""
    assert janela_oferta_dias(None) is None
    assert janela_oferta_dias({}) is None
    assert janela_oferta_dias({"janela_inicio": {"valor": "2026-07-01"}}) is None  # sem fim
    assert (
        janela_oferta_dias(
            {
                "janela_inicio": {"valor": "01/07 a 15/08"},  # o TEXTUAL não é parseado
                "janela_fim": {"valor": "2026-08-15"},
            }
        )
        is None
    )
    assert (
        janela_oferta_dias(
            {
                "janela_inicio": {"valor": "2026-08-15"},
                "janela_fim": {"valor": "2026-07-01"},  # invertida
            }
        )
        is None
    )


# ------------------------------------------------------------- validador (unit)
def _grafo_com_wait(duracao: str, os_codigo: str = "OS-J04") -> dict[str, Any]:
    return {
        "jgcVersion": "1.0",
        "meta": {"osCodigo": os_codigo, "tenant": TENANT, "reentrada": "nao"},
        "nodes": [
            {
                "id": "n1",
                "type": "entrySource",
                "data": {"deRef": "DE_e", "modo": "fire_once", "reentrada": "nao"},
            },
            {"id": "n2", "type": "wait", "data": {"duracao": duracao}},
            {
                "id": "n3",
                "type": "channel.email",
                "data": {"assetRef": "a1", "optIn": True},
            },
            {"id": "n4", "type": "goal", "data": {"metrica": "conversion", "deRef": "DE_c"}},
        ],
        "edges": [
            {"id": "e1", "from": "n1", "to": "n2", "cond": None},
            {"id": "e2", "from": "n2", "to": "n3", "cond": None},
            {"id": "e3", "from": "n3", "to": "n4", "cond": None},
        ],
    }


def test_J04_validador_reprova_wait_alem_da_janela_quando_ela_existe() -> None:
    erros = validar_grafo(_grafo_com_wait("P30D"), janela_oferta_dias=5.0)
    assert any(e["regra"] == "wait_alem_da_janela" and e["no"] == "n2" for e in erros), erros
    assert validar_grafo(_grafo_com_wait("P2D"), janela_oferta_dias=5.0) == []
    assert validar_grafo(_grafo_com_wait("P30D"), janela_oferta_dias=None) == []  # inerte


# ------------------------------------------------------- consultor (whitelist)
def test_J04_consultor_infere_janela_estruturada_e_descarta_campo_estranho() -> None:
    saida = agente_consultor.interpretar_saida(
        '{"resposta": "ok", "inferencias": ['
        '{"campo": "janela_inicio", "valor": "2026-07-01", "evidencias": ["informado"]},'
        '{"campo": "janela_fim", "valor": "2026-08-15", "evidencias": ["informado"]},'
        '{"campo": "campo_inventado", "valor": "x", "evidencias": ["nada"]}]}'
    )
    campos = {i.campo for i in saida.inferencias}
    assert campos == {"janela_inicio", "janela_fim"}  # o estranho continua descartado


def test_J04_consultor_descarta_janela_em_formato_nao_ISO() -> None:
    """Auditoria da onda 6: o 120b real tende a emitir data BR ('01/07/2026'). Um
    valor presente-mas-inválido seria gravado, exibido como 'confirmado' na T2, e a
    regra ficaria inerte SEM aviso — o usuário acha que declarou. Melhor não gravar.
    INVERSÃO: remover o filtro `parse_data_iso(valor) is None` de interpretar_saida
    deixa este teste vermelho."""
    saida = agente_consultor.interpretar_saida(
        '{"resposta": "ok", "inferencias": ['
        '{"campo": "janela_inicio", "valor": "01/07/2026", "evidencias": ["informado"]},'
        '{"campo": "janela_fim", "valor": "15 de agosto", "evidencias": ["informado"]},'
        '{"campo": "objetivo", "valor": "upgrade 5G", "evidencias": ["informado"]}]}'
    )
    campos = {i.campo for i in saida.inferencias}
    assert campos == {"objetivo"}  # as datas BR não entram; o obrigatório entra


# ------------------------------------------------------------ ponta a ponta HTTP
def _criar_os(client: TestClient, app: FastAPI, briefing: dict[str, Any]) -> dict[str, Any]:
    resposta = client.post(
        "/api/v1/os",
        json={"nome": "J04 janela", "tshirt": "M", "briefing": briefing},
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    os_ = resposta.json()
    app.state.repositorio_os.adicionar_segmento(
        Segmento(
            id=uuid.uuid4(),
            os_id=uuid.UUID(os_["id"]),
            origem="estudio_sql",
            contagem_bruta=1000,
            contagem_liquida=1000,
        )
    )
    return os_


def test_J04_wait_maior_que_a_janela_e_422(client: TestClient, app: FastAPI) -> None:
    os_ = _criar_os(
        client,
        app,
        {
            "janela": {"valor": "01/07 a 05/07 (rampa)", "inferido": False},  # display
            "janela_inicio": {"valor": "2026-07-01", "inferido": False},
            "janela_fim": {"valor": "2026-07-05", "inferido": False},  # 4 dias
        },
    )
    grafo = _grafo_com_wait("P30D", os_["codigo"])
    recusado = client.post(f"/api/v1/os/{os_['id']}/jornada", json={"grafo": grafo}, headers=_h())
    assert recusado.status_code == 422, recusado.text
    erros = recusado.json()["erros"]
    assert any(e["regra"] == "wait_alem_da_janela" and e["no"] == "n2" for e in erros), erros

    # o MESMO wait dentro da janela salva — e o simular (mesma régua) aceita
    aceito = client.post(
        f"/api/v1/os/{os_['id']}/jornada",
        json={"grafo": _grafo_com_wait("P2D", os_["codigo"])},
        headers=_h(),
    )
    assert aceito.status_code == 201, aceito.text
    simulada = client.post(
        f"/api/v1/jornadas/{aceito.json()['jornada']['id']}/simular",
        json={"seed": 42, "runs": 10, "n_personas": 100},
        headers=_h(),
    )
    assert simulada.status_code == 200, simulada.text


def test_J04_briefing_sem_os_campos_mantem_o_comportamento_antigo(
    client: TestClient, app: FastAPI
) -> None:
    """Contra-prova: sem janela estruturada a regra segue INERTE — o wait de 30 dias
    que o teste acima recusa salva 201 aqui, como salvava antes do J04."""
    os_ = _criar_os(client, app, {"janela": {"valor": "01/07 a 15/08", "inferido": False}})
    aceito = client.post(
        f"/api/v1/os/{os_['id']}/jornada",
        json={"grafo": _grafo_com_wait("P30D", os_["codigo"])},
        headers=_h(),
    )
    assert aceito.status_code == 201, aceito.text


def test_J04_patch_do_briefing_recusa_janela_nao_ISO(client: TestClient, app: FastAPI) -> None:
    """Verificação da onda 6: o consultor descarta data BR, mas o EDITOR HUMANO (PATCH)
    também precisa recusá-la — senão o furo do 'presente-mas-inválido' só mudou de porta.
    PATCH /pedidos/{id}/campos e PATCH /os/{id}/briefing/{campo} com data não-ISO → 422.

    INVERSÃO: remover `exigir_janela_iso` de `editar_campos`/`editar_briefing` deixa
    este teste vermelho."""
    portal = {"X-Tenant": TENANT, "Authorization": "Bearer portal-dev"}
    pedido = client.post(
        "/api/v1/pedidos",
        json={"solicitante": {"nome": "Ana"}, "conteudo": {}},
        headers=portal,
    )
    assert pedido.status_code == 201, pedido.text
    pid = pedido.json()["id"]

    # data BR no PATCH de campos (o corpo é o mapa {campo: valor} direto) → 422
    ruim = client.patch(
        f"/api/v1/pedidos/{pid}/campos",
        json={"janela_inicio": "01/07/2026"},
        headers=_h(),
    )
    assert ruim.status_code == 422, ruim.text
    assert "janela_inicio" in ruim.json()["detail"]

    # ISO passa
    bom = client.patch(
        f"/api/v1/pedidos/{pid}/campos",
        json={"janela_inicio": "2026-07-01"},
        headers=_h(),
    )
    assert bom.status_code == 200, bom.text


def test_J04_optimize_tambem_honra_a_janela(client: TestClient, app: FastAPI) -> None:
    """Consumidor esquecido que a auditoria da onda 6 pegou (P1): o Optimize (M11)
    validava a proposta e a aprovação SEM a janela — um wait alem dela passava pela
    rota do optimize enquanto o MESMO grafo via /jornada dava 422.

    INVERSÃO: remover `janela_oferta_dias=` de qualquer um dos dois validar_grafo do
    otimizacao_service deixa este teste vermelho."""
    import json

    from tests.acceptance.test_M11 import (
        _grafo,
        _resposta_optimize,
        _semear_jornada,
        _simular_e_congelar,
    )

    jornada_id, os_id = _semear_jornada(client, app)
    repo = app.state.repositorio_os
    os_ = repo.obter_os(TENANT, os_id)
    os_.briefing = {  # janela de 4 dias — o wait de 30d da proposta a estoura
        "janela_inicio": {"valor": "2026-07-01", "inferido": False},
        "janela_fim": {"valor": "2026-07-05", "inferido": False},
    }
    repo.salvar_os(os_)
    _simular_e_congelar(client, jornada_id)

    # a proposta padrão do M11 troca a espera para PT2H (dentro da janela) — alongo
    # para P30D, alem da janela, sem tocar no resto (segue válida em tudo mais)
    codigo = repo.obter_os(TENANT, os_id).codigo
    proposta = json.loads(_resposta_optimize(codigo))
    longo = _grafo(codigo)
    next(n for n in longo["nodes"] if n["id"] == "n3")["data"]["duracao"] = "P30D"
    proposta["propostas"] = [{**proposta["propostas"][0], "grafo": longo}]
    app.state.llm = LLMFake(resposta=json.dumps(proposta, ensure_ascii=False))

    corpo = client.get(f"/api/v1/os/{os_id}/propostas", headers=_h()).json()
    # a proposta com wait alem da janela é DESCARTADA (não aparece como válida)
    assert corpo["propostas"] == []
    descartadas = " ".join(
        e["regra"] for a in corpo.get("avisos", []) for e in a.get("descartada_por", [])
    )
    assert "wait_alem_da_janela" in descartadas, corpo
