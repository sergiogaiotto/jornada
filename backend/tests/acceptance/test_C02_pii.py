"""Aceite C02 · PII nunca em prompt de LLM nem no ledger (SDD §10.2 — emenda C02).

Achado do UAT #3 adversarial (docs/UAT3-VPS-2026-08-06-adversarial.md): CPF, telefone
e e-mail digitados pelo solicitante chegavam EM CLARO ao prompt do hub e eram gravados
em claro no ledger `invocacao` — violação direta do §10.2 (LGPD).

Guarda-corpo por COMPORTAMENTO: o teste manda PII pela porta de entrada real (HTTP) e
inspeciona o que o LLMFake REALMENTE recebeu e o que o repositório REALMENTE gravou —
não testa a implementação do sanitizador (isso é o unit `tests/unit/test_mascarar.py`).
"""

import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.llm.fake import LLMFake

TENANT = "torre-movel"

# PII plantada na mensagem, em várias formas (com e sem pontuação) — §10.2
CPF = "529.982.247-25"
CPF_CRU = "52998224725"
EMAIL = "joao.silva@clientereal.com.br"
TELEFONE = "(11) 98765-4321"
TELEFONE_CRU = "11987654321"
PII = (CPF, CPF_CRU, EMAIL, TELEFONE, TELEFONE_CRU)

# O que NÃO pode se perder: o pedido de negócio em volta da PII
MENSAGEM = (
    f"O contato do cliente é {EMAIL}, CPF {CPF} (ou {CPF_CRU}), "
    f"telefone {TELEFONE} e também {TELEFONE_CRU}. "
    "A verba é de R$ 480.000 para 847.312 clientes na janela de 01/10 a 15/10."
)


def _h(token: str = "portal-dev") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _resposta_consultor() -> str:
    return json.dumps(
        {"resposta": "Anotado. Confirma a verba e a janela?", "inferencias": []},
        ensure_ascii=False,
    )


def _criar_pedido(client: TestClient) -> dict[str, Any]:
    resposta = client.post(
        "/api/v1/pedidos",
        json={
            "solicitante": {"nome": "Ana Lima", "area": "Marketing"},
            "conteudo": {"objetivo": "Upgrade 5G", "publico": "Pós-pago 12+ meses"},
        },
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_C02_pii_nunca_no_prompt_nem_no_ledger(client: TestClient, app: FastAPI) -> None:
    """§10.2/C02: CPF+e-mail+telefone enviados pelo consultor (a) não aparecem em
    NENHUMA mensagem entregue ao LLM, (b) não aparecem em NENHUM campo do ledger
    `invocacao`, (c) o restante do texto sobrevive — o agente ainda entende o pedido."""
    fake = LLMFake(resposta=_resposta_consultor())
    app.state.llm = fake  # §1.3.5: nenhuma rede

    pedido = _criar_pedido(client)
    resposta = client.post(
        f"/api/v1/pedidos/{pedido['id']}/mensagem",
        json={"mensagem": MENSAGEM},
        headers=_h(),
    )
    assert resposta.status_code == 200, resposta.text

    # (a) o PROMPT que o hub recebeu não tem PII — inspeciona TODAS as chamadas
    assert fake.chamadas, "o consultor precisa ter chamado o LLM"
    prompt = json.dumps(fake.chamadas, ensure_ascii=False)
    for sensivel in PII:
        assert sensivel not in prompt, f"PII {sensivel!r} vazou para o prompt (§10.2)"

    # (b) o LEDGER gravado não tem PII — o `invocacao` é a fonte de auditoria LGPD
    invocacoes = app.state.repositorio_os.listar_invocacoes(TENANT)
    assert len(invocacoes) == 1
    ledger = json.dumps(
        {"input": invocacoes[0].input, "output": invocacoes[0].output},
        ensure_ascii=False,
        default=str,
    )
    for sensivel in PII:
        assert sensivel not in ledger, f"PII {sensivel!r} vazou para o ledger (§10.2)"

    # (c) o texto mascarado PRESERVA o resto: marcadores no lugar da PII e os números
    # de NEGÓCIO intactos (mascarar não pode comer verba/audiência/datas)
    gravado = invocacoes[0].input["mensagem"]
    assert "[CPF]" in gravado and "[EMAIL]" in gravado and "[TELEFONE]" in gravado
    assert "O contato do cliente é [EMAIL], CPF [CPF]" in gravado
    for negocio in ("R$ 480.000", "847.312", "01/10 a 15/10"):
        assert negocio in gravado, f"{negocio!r} não é PII e não podia ser mascarado"
    # prompt e ledger recebem EXATAMENTE o mesmo texto (um único ponto de mascaramento)
    assert gravado in prompt


def test_C02_pii_mascarada_no_engineer(client: TestClient, app: FastAPI) -> None:
    """O sanitizador é ÚNICO e vale para todo agente que recebe texto livre: aqui o
    engineer (instruções do Estúdio SQL). Mesmo com o LLM devolvendo lixo (a saída é
    rejeitada por código), o prompt e o ledger já nasceram sem PII."""
    fake = LLMFake(resposta="isso não é json")
    app.state.llm = fake

    os_ = client.post(
        "/api/v1/os",
        json={"nome": "Upgrade 5G", "tshirt": "M"},
        headers=_h("dev-analista"),
    )
    assert os_.status_code == 201, os_.text
    os_id = os_.json()["id"]

    client.post(
        f"/api/v1/os/{os_id}/segmento/gerar-sql",
        json={"instrucoes": f"Excluir o cliente de CPF {CPF} e o e-mail {EMAIL}."},
        headers=_h("dev-analista"),
    )

    prompt = json.dumps(fake.chamadas, ensure_ascii=False)
    assert fake.chamadas, "o engineer precisa ter chamado o LLM"
    assert CPF not in prompt and EMAIL not in prompt
    assert "[CPF]" in prompt and "[EMAIL]" in prompt


def test_C02_pii_mascarada_no_criativo(client: TestClient, app: FastAPI) -> None:
    """O Estúdio Criativo (T6) também recebe texto livre (`instrucoes`) e o repassa aos
    TRÊS agentes do pipeline (visual→copy→content), gravando uma linha de ledger por
    chamada: PII não pode aparecer em nenhuma das três, nem no prompt nem no ledger."""
    fake = LLMFake(resposta="isso não é json")  # saída rejeitada por código; o que
    app.state.llm = fake  # importa aqui é o que ENTROU

    os_ = client.post(
        "/api/v1/os",
        json={"nome": "Upgrade 5G", "tshirt": "M"},
        headers=_h("dev-analista"),
    )
    assert os_.status_code == 201, os_.text

    client.post(
        f"/api/v1/os/{os_.json()['id']}/criativos/gerar",
        json={
            "kv_master": {"conceito": "Upgrade 5G", "promessa": "Mais velocidade"},
            "instrucoes": f"Personalize para {EMAIL}, CPF {CPF}, telefone {TELEFONE}.",
        },
        headers=_h("dev-analista"),
    )

    assert fake.chamadas, "o criativo precisa ter chamado o LLM"
    prompt = json.dumps(fake.chamadas, ensure_ascii=False)
    ledger = json.dumps(
        [i.input for i in app.state.repositorio_os.listar_invocacoes(TENANT)],
        ensure_ascii=False,
        default=str,
    )
    for sensivel in PII:
        assert sensivel not in prompt, f"PII {sensivel!r} vazou para o prompt do T6 (§10.2)"
        assert sensivel not in ledger, f"PII {sensivel!r} vazou para o ledger do T6 (§10.2)"
    assert "[CPF]" in prompt and "[EMAIL]" in prompt and "[TELEFONE]" in prompt
