"""Aceite C02 · PII nunca em prompt de LLM nem no ledger (SDD §10.2 — emenda C02).

Achado do UAT #3 adversarial (docs/UAT3-VPS-2026-08-06-adversarial.md): CPF, telefone
e e-mail digitados pelo solicitante chegavam EM CLARO ao prompt do hub e eram gravados
em claro no ledger `invocacao` — violação direta do §10.2 (LGPD).

**Achado 9 do UAT #5** (docs/UAT5-2026-08-06-cacada.md): o C02 fechou a janela e deixou
a PORTA. `mascarar_pii` era chamado em `mensagem`/`instrucoes`/`pergunta`, mas o
BRIEFING — `POST /pedidos`, `PATCH /pedidos/{id}/campos`, `PATCH /os/{id}/briefing/{campo}`
— entrava em claro, ia para o prompt, para o ledger, para o NOME da OS e daí para a
página pública do link mágico. E este arquivo ficava VERDE com o vazamento aberto,
porque criava o pedido com briefing sem PII e plantava a PII só em `instrucoes`. A
correção do aceite é esta: a PII agora entra pelo BRIEFING, que é o furo real.

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


# Briefing COM PII (achado 9): é assim que o solicitante realmente digita — o campo de
# texto livre do formulário, não a conversa. `verba` numérica prova que o sanitizador
# estrutural não mexe em tipo nem em número de negócio.
CONTEUDO_COM_PII: dict[str, Any] = {
    "objetivo": f"Ligar para João {TELEFONE_CRU} CPF {CPF}",
    "publico": f"Pós-pago 12+ meses; contato de teste {EMAIL}",
    "verba": 480_000.0,
}


def _criar_pedido(client: TestClient, conteudo: dict[str, Any] | None = None) -> dict[str, Any]:
    resposta = client.post(
        "/api/v1/pedidos",
        json={
            "solicitante": {"nome": "Ana Lima", "area": "Marketing"},
            "conteudo": CONTEUDO_COM_PII if conteudo is None else conteudo,
        },
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def test_C02_pii_nunca_no_prompt_nem_no_ledger(client: TestClient, app: FastAPI) -> None:
    """§10.2/C02: CPF+e-mail+telefone enviados pelo consultor (a) não aparecem em
    NENHUMA mensagem entregue ao LLM, (b) não aparecem em NENHUM campo do ledger
    `invocacao`, (c) o restante do texto sobrevive — o agente ainda entende o pedido.

    O pedido agora nasce com PII no BRIEFING (achado 9): `montar_mensagens` recebe
    `pedido.conteudo`, então (a) passou a cobrir as DUAS portas de uma vez."""
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

    # (d) o RAG (§7.4/A11) indexa e CONSULTA texto: o `agente_evidence` é uma base
    # vetorial que sobrevive à OS, então PII embutida ali seria persistente e difícil
    # de purgar. A consulta enviada ao EmbeddingPort é a mesma mensagem já sanitizada.
    consultas = json.dumps(app.state.embedding.chamadas, ensure_ascii=False)
    assert app.state.embedding.chamadas, "o retriever precisa ter consultado o embedding"
    for sensivel in PII:
        assert sensivel not in consultas, f"PII {sensivel!r} vazou para o embedding (§10.2)"


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


def test_C02_pii_no_briefing_nao_chega_a_os_nem_ao_outbox(client: TestClient, app: FastAPI) -> None:
    """Achado 9 do UAT #5 — o furo REAL: a PII entra pelo BRIEFING, não pela conversa.

    Percorre as TRÊS portas do briefing (`POST /pedidos`, `PATCH /pedidos/{id}/campos`,
    `PATCH /os/{id}/briefing/{campo}`) e o `nome` do converter, e prova o que a VPS
    mostrou vazando: nome da OS ("Ligar para Joao 11987654321 CPF 529.982.247-25" —
    que vai para a página pública do link mágico), briefing persistido e payloads do
    outbox. Números de negócio (verba 480000) continuam intactos e TIPADOS."""
    repo = app.state.repositorio_os

    # (1) porta 1 — criação com PII no briefing
    pedido = _criar_pedido(client)
    conteudo = pedido["conteudo"]
    assert "[CPF]" in conteudo["objetivo"]["valor"]
    assert "[TELEFONE]" in conteudo["objetivo"]["valor"]
    assert "[EMAIL]" in conteudo["publico"]["valor"]
    assert conteudo["verba"]["valor"] == 480_000.0, "número de negócio é float, não string"
    assert pedido["completude"] == 60.0  # 3 de 5 obrigatórios: o mascaramento não some com campo

    # (2) porta 2 — PATCH de campos com PII (quem não digitou na criação digita aqui)
    completo = client.patch(
        f"/api/v1/pedidos/{pedido['id']}/campos",
        json={"oferta": f"Falar com o titular {TELEFONE}", "janela": "01/10 a 15/10"},
        headers=_h("dev-analista"),
    )
    assert completo.status_code == 200, completo.text
    assert "[TELEFONE]" in completo.json()["conteudo"]["oferta"]["valor"]
    assert completo.json()["completude"] == 100.0

    # (3) conversão com nome DERIVADO do objetivo (`_nome_padrao`) — o caso da VPS
    os_a = client.post(
        f"/api/v1/pedidos/{pedido['id']}/converter",
        json={"tshirt": "M"},
        headers=_h("dev-analista"),
    )
    assert os_a.status_code == 201, os_a.text
    assert "[CPF]" in os_a.json()["nome"] and "[TELEFONE]" in os_a.json()["nome"]

    # (4) conversão com nome EXPLÍCITO do usuário — texto livre igualmente sanitizado
    outro = _criar_pedido(client)
    client.patch(
        f"/api/v1/pedidos/{outro['id']}/campos",
        json={"oferta": "Upgrade", "janela": "01/10 a 15/10"},
        headers=_h("dev-analista"),
    )
    os_b = client.post(
        f"/api/v1/pedidos/{outro['id']}/converter",
        json={"nome": f"Campanha do {EMAIL}", "tshirt": "M"},
        headers=_h("dev-analista"),
    )
    assert os_b.status_code == 201, os_b.text
    assert "[EMAIL]" in os_b.json()["nome"]

    # (5) porta 3 — PATCH do briefing da OS já criada
    patch = client.patch(
        f"/api/v1/os/{os_a.json()['id']}/briefing/oferta",
        json={"valor": f"Ligar para {CPF_CRU}"},
        headers=_h("dev-analista"),
    )
    assert patch.status_code == 200, patch.text
    assert "[CPF]" in patch.json()["briefing"]["oferta"]["valor"]

    # (6) nada disso deixou PII no estado persistido: OS (nome+briefing), pedidos e
    # payloads do outbox — que é por onde a integração externa lê (§2.3)
    persistido = json.dumps(
        {
            "os": [
                {"nome": o.nome, "briefing": o.briefing}
                for o in repo.listar_os(TENANT, limit=50, offset=0)
            ],
            "pedidos": [p.conteudo for p in repo.listar_pedidos(TENANT)],
            "eventos": [{"type": e.type, "payload": e.payload} for e in repo.listar_eventos()],
        },
        ensure_ascii=False,
        default=str,
    )
    for sensivel in PII:
        assert sensivel not in persistido, f"PII {sensivel!r} sobreviveu no estado (§10.2)"


def test_C02_pii_na_CHAVE_do_campo_do_briefing(client: TestClient, app: FastAPI) -> None:
    """Achado 9 (b) — o furo que sobrou depois do primeiro fix: a CHAVE.

    `conteudo`/`campos` são `dict[str, Any]` ABERTO no schema (`api/v1/intake.py`): não
    há enum de campos, então quem digita escolhe o NOME do campo. O fix inicial mascarou
    só os valores, e o nome do campo seguia em claro para três lugares medidos aqui:
    o `conteudo` persistido, a resposta HTTP e — o pior — o payload de
    `pedido.campos_editados` (`{"campos": sorted(campos)}`), que é o que a integração
    externa consome no outbox (§2.3). É a mesma chave que `editar_briefing` já
    mascarava quando vinha pelo PATH da URL; pela porta do JSON estava aberta."""
    criado = client.post(
        "/api/v1/pedidos",
        json={
            "solicitante": {"nome": "Ana Lima", "area": "Marketing"},
            # o solicitante nomeia o campo com o dado do titular dentro
            "conteudo": {f"objetivo do CPF {CPF}": "Upgrade 5G", "publico": "Pós-pago"},
        },
        headers=_h(),
    )
    assert criado.status_code == 201, criado.text
    chaves = list(criado.json()["conteudo"])
    assert f"objetivo do CPF {CPF}" not in chaves, "CPF sobreviveu na CHAVE do conteúdo"
    assert "objetivo do CPF [CPF]" in chaves

    editado = client.patch(
        f"/api/v1/pedidos/{criado.json()['id']}/campos",
        json={f"oferta contato {EMAIL}": "10% off", "janela": "01/10 a 15/10"},
        headers=_h("dev-analista"),
    )
    assert editado.status_code == 200, editado.text
    assert "oferta contato [EMAIL]" in editado.json()["conteudo"]

    # o evento do outbox carrega a LISTA de campos editados — era o vazamento em claro
    estado = json.dumps(
        {
            "pedidos": [p.conteudo for p in app.state.repositorio_os.listar_pedidos(TENANT)],
            "eventos": [
                {"type": e.type, "payload": e.payload}
                for e in app.state.repositorio_os.listar_eventos()
            ],
        },
        ensure_ascii=False,
        default=str,
    )
    for sensivel in PII:
        assert sensivel not in estado, f"PII {sensivel!r} vazou pela CHAVE do campo (§10.2)"
