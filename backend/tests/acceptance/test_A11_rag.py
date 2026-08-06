"""Aceites do A11 · RAG funcional em produção (§7.4) — via TestClient, SEM rede
(§1.3.5): LLM = LLMFake, embeddings = EmbeddingFake determinístico.

Cobre o wire de verdade: a base `dicionario_dados` ingerida no repositório aparece
como `evidencias_rag` (top-k=8) no PROMPT do engineer e as evidências citadas voltam
na resposta/ledger; o consultor recebe `precedentes` das bases dele; embeddings
degradados NÃO derrubam o caminho do agente (degrade suave §10.6).
"""

import json
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.embedding.fake import EmbeddingFake
from adapters.llm.fake import LLMFake
from app.rag import semear_rag_demo
from domain.agentes.modelos import AgenteEvidence
from tests.acceptance.test_M5 import SQL_CONFORME, _criar_os, _h, _resposta_engineer

TENANT = "torre-movel"


def _seed_dicionario(app: FastAPI) -> int:
    """Ingesta a seed DEMO no repositório do app com o MESMO fake de embeddings das
    rotas (vetores e consulta na mesma dimensão)."""
    return semear_rag_demo(app.state.repositorio_os, app.state.embedding, tenant_id=TENANT)


def test_A11_engineer_recebe_evidencias_do_retriever_e_cita(
    client: TestClient, app: FastAPI
) -> None:
    """FakeEmbedding+FakeLLM: gerar-sql monta o contexto com `evidencias_rag`
    (top-k=8 da base `dicionario_dados` autorizada à skill) e o SQL sai com
    evidências citadas (ledger `invocacao.evidencias` preenchido)."""
    total = _seed_dicionario(app)
    assert total >= 15
    app.state.llm = LLMFake(resposta=_resposta_engineer(SQL_CONFORME))
    os_ = _criar_os(client)
    resposta = client.post(
        f"/api/v1/os/{os_['id']}/segmento/gerar-sql",
        json={"instrucoes": "Pós-pago com consumo_pct alto e pacotes avulsos recorrentes."},
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["via_ai"] is True and corpo["evidencias"]  # citadas na saída

    contexto = json.loads(app.state.llm.chamadas[0]["mensagens"][1]["content"])
    evidencias = contexto["evidencias_rag"]
    assert len(evidencias) >= 8  # §7.3: top-k=8 + as pinadas de compliance (A24)
    trechos = " ".join(e["trecho"] for e in evidencias)
    assert "consumo_pct" in trechos  # ranking real: a consulta puxa a coluna citada
    # A24: o Guard exige as 7 listas e opt-in por canal em TODA segmentação — essas
    # evidências entram sempre, à frente do top-k (não dependem de sorte semântica).
    refs = [e["ref"] for e in evidencias]
    assert "lista_supressao" in refs
    assert any(r.startswith("hybris_base_clientes.opt_in_") for r in refs)
    assert refs[0] in {"lista_supressao"} or refs[0].startswith("hybris_base_clientes.")
    assert all(
        e["base"] == "dicionario_dados" and e["id"] and "trecho" in e
        for e in contexto["evidencias_rag"]
    )  # só bases autorizadas à skill (engineer: dicionario_dados|historico_campanhas)

    repo = app.state.repositorio_os
    invocacao = repo.listar_invocacoes(TENANT)[-1]
    assert invocacao.evidencias  # ledger via_ai com evidências (§4.1/§7.3)


def test_A11_embeddings_degradados_nao_derrubam_o_engineer(
    client: TestClient, app: FastAPI
) -> None:
    """Hub de embeddings fora (§10.6) → retriever devolve [] e o fluxo segue: prompt
    SEM `evidencias_rag` (idêntico ao pré-A11), resposta 201 — RAG nunca vira 500."""
    app.state.embedding = EmbeddingFake(disponivel=False)
    app.state.llm = LLMFake(resposta=_resposta_engineer(SQL_CONFORME))
    os_ = _criar_os(client)
    resposta = client.post(
        f"/api/v1/os/{os_['id']}/segmento/gerar-sql",
        json={"instrucoes": "Pós-pago elegível a upgrade 5G."},
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    contexto = json.loads(app.state.llm.chamadas[0]["mensagens"][1]["content"])
    assert "evidencias_rag" not in contexto  # degrade suave: chave fora do contexto


def test_A11_consultor_recebe_precedentes_das_bases_dele(client: TestClient, app: FastAPI) -> None:
    """Consultor (bases_rag: historico_campanhas|ofertas): precedentes citáveis do
    retriever entram no contexto como `precedentes`; a base `dicionario_dados`
    (não autorizada à skill) fica FORA."""
    repo = app.state.repositorio_os
    _seed_dicionario(app)  # base NÃO autorizada ao consultor — não pode vazar
    [vetor] = app.state.embedding.embed(["campanha upgrade 5G pos_pago roas historico"])
    repo.adicionar_evidencia(
        AgenteEvidence(
            id=uuid.uuid4(),
            tenant_id=TENANT,
            base="historico_campanhas",
            ref="OS-2025-0311",
            chunk="Campanha upgrade 5G pos_pago (OS-2025-0311): ROAS 12x, verba R$ 80k.",
            embedding=vetor,
        )
    )
    pedido = client.post(
        "/api/v1/pedidos",
        json={"solicitante": {"nome": "Ana", "area": "Ofertas"}},
        headers=_h(),
    )
    assert pedido.status_code == 201, pedido.text
    resposta = client.post(
        f"/api/v1/pedidos/{pedido.json()['id']}/mensagem",
        json={"mensagem": "Quero repetir a campanha de upgrade 5G do ano passado."},
        headers=_h(),
    )
    assert resposta.status_code == 200, resposta.text
    contexto = json.loads(app.state.llm.chamadas[0]["mensagens"][1]["content"])
    assert [p["ref"] for p in contexto["precedentes"]] == ["OS-2025-0311"]
    assert all(p["base"] != "dicionario_dados" for p in contexto["precedentes"])
