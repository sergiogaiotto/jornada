"""Aceites do M-Guia · chat "IA, me ajude com esta página" (§8-M-Guia, emenda
2026-08-05) — IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker e SEM REDE (§1.3.5): o hub real nunca é chamado —
LLMFake responde (A1) ou simula forced_off (A2 — §10.6). O contexto é o conteúdo do
guia da página, enviado pelo FRONT (fonte única em frontend/src/guia/conteudo.ts);
o contrato valida ≤ 8k chars.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.llm.fake import LLMFake
from app.errors import PROBLEM_CONTENT_TYPE
from domain.agentes.modelos import agente_uuid

TENANT = "torre-movel"
HEADERS = {"X-Tenant": TENANT, "Authorization": "Bearer dev-analista"}

CONTEXTO_COCKPIT = (
    "Cockpit — home do portfólio: KPIs (No ar, Aguardando aprovação, Em risco, No ciclo), "
    "kanban pelas 8 fases (Pensada→Encerrada) e saúde DERIVADA de pendências/SLAs "
    "(nunca editável). Selecionar um card coloca a OS em foco e habilita o menu."
)


def test_guia_A1(client: TestClient, app: FastAPI) -> None:
    """§8-M-Guia-A1: a resposta usa o contexto do guia enviado pelo front — o
    prompt do agente ajuda (perfil 20b §3) carrega o contexto e o histórico da
    sessão; `invocacao` via_ai gravada com os_id NULL e pergunta mascarada (§10.2);
    contexto acima de 8k chars → 422 (contrato)."""
    resposta_fake = (
        "No Cockpit, a saúde é derivada de pendências bloqueantes e SLAs — "
        "não existe botão para editá-la."
    )
    fake = LLMFake(resposta=resposta_fake)
    app.state.llm = fake

    resposta = client.post(
        "/api/v1/ajuda/perguntar",
        json={
            "pagina": "cockpit",
            "pergunta": "Por que não consigo editar a saúde? Meu telefone é 11987654321.",
            "contexto": CONTEXTO_COCKPIT,
            "historico": [
                {"papel": "usuario", "texto": "O que é o Cockpit?"},
                {"papel": "ia", "texto": "É a home do portfólio de campanhas."},
            ],
        },
        headers=HEADERS,
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["resposta"] == resposta_fake
    assert corpo["pagina"] == "cockpit" and corpo["via_ai"] is True

    # o prompt levou o CONTEXTO do guia (injeção do front — fonte única) e o histórico
    assert len(fake.chamadas) == 1
    chamada = fake.chamadas[0]
    assert chamada["perfil"] == "20b"  # §3: resumos de UI → 20b
    conteudos = [m["content"] for m in chamada["mensagens"]]
    assert any(CONTEXTO_COCKPIT in c for c in conteudos)
    assert any("home do portfólio de campanhas" in c for c in conteudos)  # histórico
    assert conteudos[-1].startswith("Por que não consigo editar a saúde?")

    # ledger via_ai (LGPD Art. 20): os_id NULL (ajuda é da página) + PII mascarada (§10.2)
    invocacoes = [
        i
        for i in app.state.repositorio_os.listar_invocacoes(TENANT)
        if i.agente_id == agente_uuid("ajuda")
    ]
    assert len(invocacoes) == 1
    invocacao = invocacoes[0]
    assert invocacao.os_id is None
    assert corpo["invocacao_id"] == str(invocacao.id)
    assert "11987654321" not in str(invocacao.input)
    assert "[PII-mascarada]" in invocacao.input["pergunta"]
    assert invocacao.input["contexto_chars"] == len(CONTEXTO_COCKPIT)

    # contrato: contexto > 8k chars → 422 (o back NÃO aceita payload sem limite)
    grande = client.post(
        "/api/v1/ajuda/perguntar",
        json={"pagina": "cockpit", "pergunta": "Oi?", "contexto": "x" * 8001},
        headers=HEADERS,
    )
    assert grande.status_code == 422


def test_guia_A2(client: TestClient, app: FastAPI) -> None:
    """§8-M-Guia-A2: hub fora (`forced_off` §10.6) → 503 problem+json com
    `modo: degraded` — o front oferece o guia estático como modo manual; nenhuma
    invocação é gravada (o LLM nem respondeu)."""
    app.state.llm = LLMFake(disponivel=False)

    resposta = client.post(
        "/api/v1/ajuda/perguntar",
        json={"pagina": "cockpit", "pergunta": "Como uso esta tela?", "contexto": "guia"},
        headers=HEADERS,
    )
    assert resposta.status_code == 503
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert resposta.json()["modo"] == "degraded"
    assert [
        i
        for i in app.state.repositorio_os.listar_invocacoes(TENANT)
        if i.agente_id == agente_uuid("ajuda")
    ] == []
