"""I04 (onda 5) — o `usage` do LLM flui até `invocacao.tokens` (§10.8).

A coluna existia desde a migração 0001, a persistência funcionava (round-trip provado
em test_persistencia_sql_parte2), e o valor morria na PORTA: `LLMPort.chat` devolvia
`str` e descartava `resposta.usage`. O §10.8 ("tokens/latência espelhados na tabela
`invocacao`") ficava cumprido pela metade, e o `teto_tokens` da IA Responsável seguia
deliberadamente FORA do conjunto fechado por falta de medição.

Estes aceites provam o fluxo por ROTA HTTP com o LLMFake do conftest (§1.3.5), cuja
contagem é determinística (palavras do texto). INVERSÃO (verificada): reverter o
retorno de `LLMFake.chat`/`hubgpu.chat` para a string crua quebra a suíte no unpacking
dos serviços; reverter só o `tokens=` de um `_registrar_invocacao` deixa o aceite
correspondente vermelho com `tokens is None`.
"""

import uuid
from typing import Any

from fastapi import FastAPI
from starlette.testclient import TestClient

from adapters.llm.fake import LLMFake
from tests.acceptance.test_M7 import _criar_os_com_segmento, _grafo, _h, _resposta_flow

TENANT = "torre-movel"


def test_I04_ajuda_grava_tokens_no_ledger(client: TestClient, app: FastAPI) -> None:
    """Caminho mais curto: POST /ajuda/perguntar → ledger com tokens NÃO nulos,
    iguais à contagem determinística do fake (1 palavra: "resposta-fake")."""
    resposta = client.post(
        "/api/v1/ajuda/perguntar",
        json={
            "pagina": "cockpit",
            "pergunta": "como funciona o semaforo?",
            "contexto": "guia da pagina cockpit",
        },
        headers=_h(),
    )
    assert resposta.status_code == 200, resposta.text
    invocacao = app.state.repositorio_os.obter_invocacao(uuid.UUID(resposta.json()["invocacao_id"]))
    assert invocacao is not None
    assert invocacao.tokens == 1  # len("resposta-fake".split()) — função pura do texto


def test_I04_retry_do_flow_soma_as_chamadas_na_mesma_linha(
    client: TestClient, app: FastAPI
) -> None:
    """Uma linha de ledger do `gerar` cobre TODAS as chamadas do retry §7.3 — a
    métrica de custo soma, nunca subrepresenta mostrando só a última tentativa."""
    os_ = _criar_os_com_segmento(client, app)
    grafo_bom = _grafo(os_["codigo"])
    grafo_ruim: dict[str, Any] = {**grafo_bom, "nodes": [n for n in grafo_bom["nodes"]]}
    grafo_ruim["nodes"] = [n for n in grafo_ruim["nodes"] if n["type"] != "goal"]
    grafo_ruim["edges"] = [a for a in grafo_bom["edges"] if a["id"] != "e5"]
    resposta_ruim = _resposta_flow(grafo_ruim)  # reprova no §5.3 (sem_goal) → retry
    resposta_boa = _resposta_flow(grafo_bom)
    app.state.llm = LLMFake(respostas=[resposta_ruim, resposta_boa])

    criada = client.post(f"/api/v1/os/{os_['id']}/jornada/gerar", headers=_h())
    assert criada.status_code == 201, criada.text

    invocacoes = app.state.repositorio_os.listar_invocacoes(TENANT)
    do_flow = [i for i in invocacoes if i.output and "jornada_id" in (i.output or {})]
    assert do_flow, "o gerar tem de ter gravado a linha do ledger"
    esperado = len(resposta_ruim.split()) + len(resposta_boa.split())
    assert do_flow[-1].tokens == esperado, (
        f"tokens={do_flow[-1].tokens!r} — a linha do ledger deveria somar as DUAS "
        f"chamadas do retry ({esperado})"
    )
