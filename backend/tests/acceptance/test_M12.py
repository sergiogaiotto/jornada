"""Aceites do módulo M12 · Ateliê T16 + Políticas + Auditoria (SDD §8-M12, §7.1,
§4.1 `agente`/`skill_versao`/`harness_case`/`harness_run`/`policy_versao`/`invocacao`
— todas na 0001_core, nenhuma migração nova) — IDs = SDD (§1.3.4).

Rodam via TestClient, sem docker e SEM REDE (§1.3.5): a execução da skill e o judge
usam o LLMFake DETERMINÍSTICO (o hub real jamais é chamado); parser, consolidação do
harness (score por dimensão, ≥90 §7.1), ciclo draft→em_revisao→publicada, o
congelamento (`os.frozen` §4.1), a validação/violações de política (compliance nunca
é LLM) e a reconstrução Art. 20 são 100% código. Seeds §11.4: agentes+skills v1
publicadas + 3 casos golden por agente-chave + política v1 publicada.
"""

import json
import uuid
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.llm.fake import LLMFake
from adapters.publicacoes import publicacoes_vigentes
from adapters.relogio import RelogioSistema
from app.errors import PROBLEM_CONTENT_TYPE
from application.ports.publicacoes_ia import PublicacoesIaPort
from application.services.atelie_service import ServicoAtelie
from domain.atelie.modelos import DIMENSOES_PADRAO
from domain.audiencia.modelos import Segmento
from domain.governanca.modelos import Snapshot
from domain.governanca.politicas import POLITICA_SEED
from domain.lancamento.modelos import Launch

TENANT = "torre-movel"

# Campos com fonte nas fixtures (§11) — mesma pré-condição de GO do test_M4.
BRIEFING_COM_FONTE: dict[str, Any] = {
    "publico": {"valor": "Pós-pago sem 5G", "inferido": False},
    "verba": {"valor": 250_000.0, "inferido": False},
}


def _h(token: str = "dev-analista") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _skill_md(nome: str = "engineer", versao: str = "1.1") -> str:
    """SKILL.md canônico §7.1 (mesma forma do exemplo do SDD, com 2+ espaços)."""
    return (
        "---\n"
        f"name: {nome}            version: {versao}      camada: especialista\n"
        "modelo_perfil: 120b       etapa: audiencia\n"
        "bases_rag: [dicionario_dados, historico_campanhas]\n"
        "exige_evidencia: true     max_retries: 2\n"
        "saida: {formato: json, schema: sql_publico.schema.json}\n"
        "---\n"
        "Você gera SQL de segmentação. NUNCA omita as 7 listas de exclusão no WHERE.\n"
        "Cite a evidência RAG de cada coluna usada. Sem evidência → responda que não sabe.\n"
    )


def _judge(notas: dict[str, int]) -> str:
    """Resposta enlatada do judge (rubrica fixa §7.1) — o LLMFake devolve o MESMO
    texto para execução e julgamento; só as `notas` importam ao consolidador."""
    return json.dumps({"notas": notas, "justificativa": "avaliação golden"}, ensure_ascii=False)


NOTAS_VERDES = dict.fromkeys(DIMENSOES_PADRAO, 95)
NOTAS_EVIDENCIA_FRACA = {**NOTAS_VERDES, "evidencia": 85}  # uma dimensão < 90 reprova (§7.1)


def _agentes(client: TestClient) -> dict[str, dict[str, Any]]:
    resposta = client.get("/api/v1/agentes", headers=_h())
    assert resposta.status_code == 200, resposta.text
    return {a["nome"]: a for a in resposta.json()["agentes"]}


def _criar_candidata(client: TestClient, agente_id: str, versao: str = "1.1") -> str:
    criada = client.post(
        f"/api/v1/agentes/{agente_id}/skills",
        json={"skill_md": _skill_md(versao=versao)},
        headers=_h(),
    )
    assert criada.status_code == 201, criada.text
    assert criada.json()["estado"] == "draft"
    skill_id: str = criada.json()["id"]
    revisao = client.post(f"/api/v1/skills/{skill_id}/revisao", headers=_h())
    assert revisao.status_code == 200 and revisao.json()["estado"] == "em_revisao"
    return skill_id


def _os_com_go(client: TestClient) -> dict[str, Any]:
    """OS em VOO: briefing validado campo a campo e GO executado (fluxo M4)."""
    criada = client.post(
        "/api/v1/os",
        json={"nome": "Upgrade Pós-Pago 5G", "tshirt": "G", "briefing": BRIEFING_COM_FONTE},
        headers=_h(),
    )
    assert criada.status_code == 201, criada.text
    os_ = criada.json()
    assert (
        client.post(f"/api/v1/os/{os_['id']}/fase", json={"fase": "discutida"}, headers=_h())
    ).status_code == 200
    for campo in BRIEFING_COM_FONTE:
        assert (
            client.post(f"/api/v1/os/{os_['id']}/validacoes/{campo}", headers=_h())
        ).status_code == 201
    go = client.post(f"/api/v1/os/{os_['id']}/go", headers=_h())
    assert go.status_code == 200, go.text
    resultado: dict[str, Any] = go.json()["os"]
    return resultado


# --------------------------------------------------------------------- Aceites §8-M12


def test_M12_A1(client: TestClient, app: FastAPI) -> None:
    """A1: publicar skill com harness < 90 → 409 (portão §7.1: score ≥ 90 POR
    DIMENSÃO do judge); com harness verde a publicação passa."""
    engineer = _agentes(client)["engineer"]  # seeds §11.4: v1.0 publicada + 3 casos
    assert engineer["versao_publicada"] == "1.0"
    skill_id = _criar_candidata(client, engineer["id"])

    # harness com judge reprovando UMA dimensão (evidencia 85 < 90) → run vermelho
    app.state.llm = LLMFake(resposta=_judge(NOTAS_EVIDENCIA_FRACA))
    run = client.post(f"/api/v1/skills/{skill_id}/harness", headers=_h())
    assert run.status_code == 201, run.text
    corpo_run = run.json()
    assert corpo_run["passou"] is False
    assert corpo_run["casos"] == 3  # golden dataset §11.4: 3 casos por agente-chave
    assert corpo_run["score_por_dimensao"]["evidencia"] < 90.0
    assert corpo_run["dimensoes_reprovadas"] == ["evidencia"]

    # publicar com harness < 90 → 409 problem+json e a skill NÃO muda de estado (A1)
    bloqueada = client.post(f"/api/v1/skills/{skill_id}/publicar", headers=_h("dev-lider"))
    assert bloqueada.status_code == 409, bloqueada.text
    assert bloqueada.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "90" in bloqueada.json()["detail"]
    assert client.get(f"/api/v1/skills/{skill_id}", headers=_h()).json()["estado"] == "em_revisao"

    # harness VERDE (todas as dimensões ≥ 90) → publicar passa e registra o score
    app.state.llm = LLMFake(resposta=_judge(NOTAS_VERDES))
    verde = client.post(f"/api/v1/skills/{skill_id}/harness", headers=_h())
    assert verde.status_code == 201 and verde.json()["passou"] is True
    publicada = client.post(f"/api/v1/skills/{skill_id}/publicar", headers=_h("dev-lider"))
    assert publicada.status_code == 200, publicada.text
    corpo = publicada.json()
    assert corpo["estado"] == "publicada"
    assert corpo["harness_score"] == 95.0 and corpo["publicada_em"]
    assert _agentes(client)["engineer"]["versao_publicada"] == "1.1"


def test_M12_A2(client: TestClient, app: FastAPI) -> None:
    """A2: OS em voo NÃO muda de versão ao publicar skill nova — o GO congelou
    `os.frozen.agent_versions` (§4.1/§8-M4-A2) e publicar não toca OS alguma; OS
    sem GO resolve a versão publicada ATUAL; um NOVO GO congela a nova."""
    versoes_seed = {  # guard é determinístico (sem skill §7.2) — não entra no frozen
        a["nome"]: a["versao_publicada"]
        for a in _agentes(client).values()
        if a["versao_publicada"] is not None
    }
    os_em_voo = _os_com_go(client)  # congela as versões publicadas ATUAIS (seeds v1.0)
    assert os_em_voo["frozen"]["agent_versions"]["engineer"] == "1.0"

    # publica engineer 1.1 (harness verde) DEPOIS do GO
    skill_id = _criar_candidata(client, _agentes(client)["engineer"]["id"])
    app.state.llm = LLMFake(resposta=_judge(NOTAS_VERDES))
    assert client.post(f"/api/v1/skills/{skill_id}/harness", headers=_h()).status_code == 201
    assert (
        client.post(f"/api/v1/skills/{skill_id}/publicar", headers=_h("dev-lider")).status_code
        == 200
    )

    # a OS em voo permanece EXATAMENTE como congelada no GO (A2)
    consulta = client.get(f"/api/v1/os/{os_em_voo['id']}", headers=_h())
    assert consulta.status_code == 200
    frozen = consulta.json()["frozen"]
    assert frozen == os_em_voo["frozen"]  # nada foi reescrito pela publicação
    assert frozen["agent_versions"]["engineer"] == "1.0"
    assert frozen["agent_versions"] == versoes_seed  # snapshot das publicadas do GO

    # resolução por OS (frozen §4.1): em voo → 1.0; plataforma (publicada atual) → 1.1
    servico = ServicoAtelie(
        app.state.repositorio_os,
        RelogioSistema(),
        LLMFake(),
        app.state.tracer,
        # O serviço passou a exigir a política de IA PUBLICADA (§10.2). Aqui o teste só
        # exercita `versao_para_os`, que nem chega ao LLM — mas a porta é obrigatória no
        # construtor de propósito: um Ateliê montável sem ela é um Ateliê que nasce mudo.
        cast(PublicacoesIaPort, publicacoes_vigentes(app.state.repositorio_os)),
    )
    em_voo = servico.versao_para_os(TENANT, uuid.UUID(os_em_voo["id"]), "engineer")
    assert em_voo == {"agente": "engineer", "versao": "1.0", "origem": "frozen"}
    nova = client.post("/api/v1/os", json={"nome": "OS nova", "tshirt": "P"}, headers=_h())
    sem_go = servico.versao_para_os(TENANT, uuid.UUID(nova.json()["id"]), "engineer")
    assert sem_go == {"agente": "engineer", "versao": "1.1", "origem": "publicada"}

    # um NOVO GO congela a versão nova (o congelado é POR campanha, não global)
    os_nova_em_voo = _os_com_go(client)
    assert os_nova_em_voo["frozen"]["agent_versions"]["engineer"] == "1.1"


# ------------------------------------------------- Contratos das demais rotas §8-M12


def test_M12_parser_e_ciclo_de_vida(client: TestClient, app: FastAPI) -> None:
    """Parser §7.1 valida CAMPOS (422 com a lista de erros); nome divergente 422;
    versão duplicada 409; ciclo draft→em_revisao→publicada é o ÚNICO caminho; run
    obsoleto (skill_md editado após o harness) não publica; RBAC: publicar é lider."""
    agentes = _agentes(client)
    engineer_id = agentes["engineer"]["id"]

    # front-matter inválido: sem version, camada/perfil/base fora do fechado, sem corpo
    invalida = (
        "---\nname: Engineer!  camada: chefe\nmodelo_perfil: 7b\nbases_rag: [wikipedia]\n---\n"
    )
    resposta = client.post(
        f"/api/v1/agentes/{engineer_id}/skills", json={"skill_md": invalida}, headers=_h()
    )
    assert resposta.status_code == 422, resposta.text
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    erros = " · ".join(resposta.json()["erros"])
    for fragmento in ("name", "version", "camada", "modelo_perfil", "bases_rag", "corpo"):
        assert fragmento in erros

    # name divergente do agente dono → 422; versão 1.0 já existe (seed) → 409
    divergente = client.post(
        f"/api/v1/agentes/{engineer_id}/skills",
        json={"skill_md": _skill_md(nome="flow", versao="9.9")},
        headers=_h(),
    )
    assert divergente.status_code == 422 and "diverge" in divergente.json()["detail"]
    duplicada = client.post(
        f"/api/v1/agentes/{engineer_id}/skills",
        json={"skill_md": _skill_md(versao="1.0")},
        headers=_h(),
    )
    assert duplicada.status_code == 409

    # ciclo: publicar direto do draft → 409; revisão de novo → 409; publicada não edita
    criada = client.post(
        f"/api/v1/agentes/{engineer_id}/skills",
        json={"skill_md": _skill_md(versao="2.0")},
        headers=_h(),
    )
    skill_id = criada.json()["id"]
    assert (
        client.post(f"/api/v1/skills/{skill_id}/publicar", headers=_h("dev-lider")).status_code
        == 409  # draft → publicada não existe (§8-M12)
    )
    assert client.post(f"/api/v1/skills/{skill_id}/revisao", headers=_h()).status_code == 200
    assert client.post(f"/api/v1/skills/{skill_id}/revisao", headers=_h()).status_code == 409
    sem_run = client.post(f"/api/v1/skills/{skill_id}/publicar", headers=_h("dev-lider"))
    assert sem_run.status_code == 409 and "nenhum harness_run" in sem_run.json()["detail"]

    # RBAC (§8-M0): analista NÃO publica (portão de plataforma é do lider)
    app.state.llm = LLMFake(resposta=_judge(NOTAS_VERDES))
    assert client.post(f"/api/v1/skills/{skill_id}/harness", headers=_h()).status_code == 201
    assert client.post(f"/api/v1/skills/{skill_id}/publicar", headers=_h()).status_code == 403

    # em_revisao é imutável (409); run obsoleto: editar o DRAFT após harness → 409
    assert (
        client.put(
            f"/api/v1/skills/{skill_id}",
            json={"skill_md": _skill_md(versao="2.0")},
            headers=_h(),
        ).status_code
        == 409
    )
    rascunho = client.post(
        f"/api/v1/agentes/{engineer_id}/skills",
        json={"skill_md": _skill_md(versao="3.0")},
        headers=_h(),
    ).json()
    assert client.post(f"/api/v1/skills/{rascunho['id']}/harness", headers=_h()).status_code == 201
    editada = client.put(
        f"/api/v1/skills/{rascunho['id']}",
        json={"skill_md": _skill_md(versao="3.0") + "\nRegra nova após o harness.\n"},
        headers=_h(),
    )
    assert editada.status_code == 200
    assert client.post(f"/api/v1/skills/{rascunho['id']}/revisao", headers=_h()).status_code == 200
    obsoleto = client.post(f"/api/v1/skills/{rascunho['id']}/publicar", headers=_h("dev-lider"))
    assert obsoleto.status_code == 409 and "obsoleto" in obsoleto.json()["detail"]

    # harness sem golden dataset → 409 (agente novo criado sem casos). O nome é de
    # sandbox: as 5 triagens do roster §7.2 já vêm das seeds (A18) e colidiriam aqui.
    novo = client.post(
        "/api/v1/agentes",
        json={"nome": "triagem_sandbox", "camada": "triagem", "modelo_perfil": "20b"},
        headers=_h(),
    )
    assert novo.status_code == 201, novo.text
    skill_nova = client.post(
        f"/api/v1/agentes/{novo.json()['id']}/skills",
        json={"skill_md": _skill_md(nome="triagem_sandbox", versao="1.0")},
        headers=_h(),
    )
    sem_casos = client.post(f"/api/v1/skills/{skill_nova.json()['id']}/harness", headers=_h())
    assert sem_casos.status_code == 409 and "golden" in sem_casos.json()["detail"]

    # `agente.nome` unique (§4.1) → 409; guard determinístico veio das seeds (§7.2)
    assert (
        client.post(
            "/api/v1/agentes",
            json={"nome": "triagem_sandbox", "camada": "triagem"},
            headers=_h(),
        ).status_code
        == 409
    )
    guard = _agentes(client)["guard"]
    assert guard["deterministico"] is True and guard["versao_publicada"] is None


def test_M12_harness_e_dry_run(client: TestClient, app: FastAPI) -> None:
    """Harness: judge malformado reprova (nada é inventado §1.3.5) e hub fora → 503
    degraded (§10.6). Dry-run lado a lado: MESMA entrada nas DUAS versões, saídas
    lado a lado, nada persiste; run gravado em `harness_run` aparece no GET."""
    engineer = _agentes(client)["engineer"]
    skill_id = _criar_candidata(client, engineer["id"])

    # judge fora do contrato (texto livre) → notas 0 em TODAS as dimensões → reprova
    app.state.llm = LLMFake(resposta="nota dez, aprovadíssimo!")
    malformado = client.post(f"/api/v1/skills/{skill_id}/harness", headers=_h())
    assert malformado.status_code == 201
    corpo = malformado.json()
    assert corpo["passou"] is False and corpo["score"] == 0.0
    assert set(corpo["dimensoes_reprovadas"]) == set(DIMENSOES_PADRAO)

    # hub indisponível → 503 degraded (harness/dry-run não são caminho crítico §10.6)
    app.state.llm = LLMFake(disponivel=False)
    fora = client.post(f"/api/v1/skills/{skill_id}/harness", headers=_h())
    assert fora.status_code == 503 and fora.json()["modo"] == "degraded"
    dry_fora = client.post(
        f"/api/v1/skills/{skill_id}/dry-run", json={"entrada": {"x": 1}}, headers=_h()
    )
    assert dry_fora.status_code == 503

    # dry-run lado a lado (§8-M12): 2 chamadas (atual 1.0 publicada + candidata 1.1)
    fake = LLMFake(resposta='{"sql": "SELECT contato_hash ..."}')
    app.state.llm = fake
    dry = client.post(
        f"/api/v1/skills/{skill_id}/dry-run",
        json={"entrada": {"pedido": "SQL pós-pago 5G"}},
        headers=_h(),
    )
    assert dry.status_code == 200, dry.text
    lado_a_lado = dry.json()
    assert lado_a_lado["entrada"] == {"pedido": "SQL pós-pago 5G"}
    assert lado_a_lado["atual"]["versao"] == "1.0" and lado_a_lado["atual"]["estado"] == "publicada"
    assert lado_a_lado["candidata"]["versao"] == "1.1"
    assert lado_a_lado["candidata"]["saida"] == '{"sql": "SELECT contato_hash ..."}'
    assert len(fake.chamadas) == 2  # mesma entrada, dois lados — e nada persiste
    entradas = [
        json.loads(mensagens[1]["content"])
        for mensagens in (chamada["mensagens"] for chamada in fake.chamadas)
        if isinstance(mensagens, list)
    ]
    assert entradas[0] == entradas[1] == {"pedido": "SQL pós-pago 5G"}

    # runs ficam no histórico da skill (GET) — inclusive o reprovado (auditoria)
    consulta = client.get(f"/api/v1/skills/{skill_id}", headers=_h())
    runs = consulta.json()["harness_runs"]
    assert len(runs) == 1 and runs[0]["passou"] is False  # o 503 não gravou run
    eventos = app.state.repositorio_os.listar_eventos(tipo="harness.run")
    assert eventos and eventos[-1].payload["agente"] == "engineer"


# ------------------------------------------ Parte 2 · Políticas + Auditoria (§8-M12)


def _resposta_consultor() -> str:
    """Saída enlatada do consultor no contrato do SKILL.md (mesmo padrão do test_M3)."""
    return json.dumps(
        {
            "resposta": "Com base em precedentes, sugiro verba de R$ 480.000. Confere?",
            "inferencias": [
                {
                    "campo": "verba",
                    "valor": "R$ 480.000",
                    "evidencias": ["historico_campanhas:OS-2025-0311", "ofertas:tabela-q3"],
                }
            ],
        },
        ensure_ascii=False,
    )


def _invocacao_via_consultor(client: TestClient, app: FastAPI) -> dict[str, Any]:
    """Gera uma linha REAL do ledger `invocacao` (fluxo M3: consultor infere verba
    com evidências) e devolve o evento de auditoria via_ai correspondente."""
    app.state.llm = LLMFake(resposta=_resposta_consultor())
    portal = {"X-Tenant": TENANT, "Authorization": "Bearer portal-dev"}
    pedido = client.post(
        "/api/v1/pedidos",
        json={"solicitante": {"nome": "Ana Lima", "area": "Marketing"}, "conteudo": {}},
        headers=portal,
    )
    assert pedido.status_code == 201, pedido.text
    conversa = client.post(
        f"/api/v1/pedidos/{pedido.json()['id']}/mensagem",
        json={"mensagem": "Qual verba você sugere para o upgrade 5G?"},
        headers=portal,
    )
    assert conversa.status_code == 200, conversa.text
    auditoria = client.get(
        "/api/v1/auditoria", params={"tipo": "agent.invoked", "agente": "consultor"}, headers=_h()
    )
    assert auditoria.status_code == 200, auditoria.text
    eventos: list[dict[str, Any]] = auditoria.json()["eventos"]
    assert eventos, "evento via_ai do consultor deveria estar na trilha (§2.3 agent.invoked)"
    return eventos[-1]


def test_M12_A3(client: TestClient, app: FastAPI) -> None:
    """A3 (Art. 20 LGPD): a reconstrução devolve EXATAMENTE input/evidências/output/
    judge DA ÉPOCA — mesmo após skill NOVA publicada; o ledger `invocacao` é imutável."""
    evento = _invocacao_via_consultor(client, app)

    # o evento via_ai é "clicável" (§8-M12): detalhe COMPLETO do ledger embutido
    assert evento["via_ai"] is True and evento["tipo"] == "agent.invoked"
    detalhe = evento["invocacao"]
    assert detalhe["agente"] == "consultor" and detalhe["skill_versao"] == "1.0"
    invocacao_id = evento["payload"]["invocacao_id"]
    assert detalhe["invocacao_id"] == invocacao_id

    # RBAC: reconstrução Art. 20 é dpo|lider (analista → 403); id inexistente → 404
    assert (
        client.post(f"/api/v1/auditoria/reconstruir/{invocacao_id}", headers=_h()).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/auditoria/reconstruir/{uuid.uuid4()}", headers=_h("dev-dpo")
        ).status_code
        == 404
    )

    # reconstrução da ÉPOCA: exatamente o que o ledger gravou no momento da invocação
    primeira = client.post(f"/api/v1/auditoria/reconstruir/{invocacao_id}", headers=_h("dev-dpo"))
    assert primeira.status_code == 200, primeira.text
    epoca = primeira.json()
    assert epoca["input"]["mensagem"] == "Qual verba você sugere para o upgrade 5G?"
    assert epoca["evidencias"] == ["historico_campanhas:OS-2025-0311", "ofertas:tabela-q3"]
    assert epoca["output"]["inferencias"][0]["campo"] == "verba"
    assert epoca["judge"] is None  # gravado assim na época — devolvido assim (Art. 20)
    assert epoca["skill_versao"] == "1.0"

    # publica skill NOVA do consultor (harness verde §7.1) DEPOIS da invocação
    consultor = _agentes(client)["consultor"]
    criada = client.post(
        f"/api/v1/agentes/{consultor['id']}/skills",
        json={"skill_md": _skill_md(nome="consultor", versao="2.0")},
        headers=_h(),
    )
    assert criada.status_code == 201, criada.text
    skill_id = criada.json()["id"]
    assert client.post(f"/api/v1/skills/{skill_id}/revisao", headers=_h()).status_code == 200
    app.state.llm = LLMFake(resposta=_judge(NOTAS_VERDES))
    assert client.post(f"/api/v1/skills/{skill_id}/harness", headers=_h()).status_code == 201
    assert (
        client.post(f"/api/v1/skills/{skill_id}/publicar", headers=_h("dev-lider")).status_code
        == 200
    )
    assert _agentes(client)["consultor"]["versao_publicada"] == "2.0"

    # reconstrução IDÊNTICA após a publicação: dados da época, não os atuais (A3)
    segunda = client.post(f"/api/v1/auditoria/reconstruir/{invocacao_id}", headers=_h("dev-dpo"))
    assert segunda.status_code == 200
    reconstruida = segunda.json()
    for chave in ("input", "evidencias", "output", "judge", "skill_versao", "created_at"):
        assert reconstruida[chave] == epoca[chave], f"{chave} divergiu da época (Art. 20)"

    # a própria reconstrução é auditável (evento `auditoria.reconstruida`, via_ai=False)
    trilha = client.get(
        "/api/v1/auditoria", params={"tipo": "auditoria.reconstruida"}, headers=_h()
    ).json()
    assert trilha["total"] == 2  # duas reconstruções acima (a de 404 não conta)
    assert all(e["via_ai"] is False for e in trilha["eventos"])
    # filtro via_ai=true não devolve eventos de reconstrução (filtros §8-M12)
    so_via_ai = client.get("/api/v1/auditoria", params={"via_ai": "true"}, headers=_h()).json()
    assert so_via_ai["eventos"] and all(e["via_ai"] is True for e in so_via_ai["eventos"])


def test_M12_policies_e_drift(client: TestClient, app: FastAPI) -> None:
    """Contratos §8-M12 (parte 2): GET/POST /policies (draft→publicada com versão
    sequencial; conteúdo §4.1 validado → 422 com erros; RBAC lider no publicar) e
    relatório de policy drift: OS em voo congelada em versão antiga que VIOLARIA a
    nova → listada; pendências de adequação OPCIONAIS (não bloqueantes, idempotentes)."""
    # seed §11.4: política v1 PUBLICADA (mesmo conteúdo do fallback do GO)
    inicial = client.get("/api/v1/policies", headers=_h())
    assert inicial.status_code == 200, inicial.text
    assert inicial.json()["publicada"]["versao"] == 1
    assert inicial.json()["publicada"]["conteudo"] == POLITICA_SEED["conteudo"]

    # OS em VOO congela policy_version=1 no GO (§8-M4-A2)
    os_em_voo = _os_com_go(client)
    assert os_em_voo["frozen"]["policy_version"] == 1

    # artefatos congelados da OS: segmento com holdout 5% e launch armado com os
    # breakers da política v1 (§8-M10) — base determinística do relatório de drift
    repo = app.state.repositorio_os
    os_id = uuid.UUID(os_em_voo["id"])
    repo.adicionar_segmento(
        Segmento(id=uuid.uuid4(), os_id=os_id, origem="estudio_sql", holdout_pct=5.0)
    )
    snapshot = Snapshot(id=uuid.uuid4(), os_id=os_id, hash="f" * 64, conteudo={}, previsto=None)
    repo.adicionar_snapshot(snapshot)
    repo.adicionar_launch(
        Launch(
            id=uuid.uuid4(),
            snapshot_id=snapshot.id,
            estado="armado",
            breakers={"optout_pct_max": 0.6},
        )
    )

    # conteúdo inválido → 422 problem+json com erros ACUMULADOS (padrão parser §7.1)
    invalida = client.post(
        "/api/v1/policies",
        json={"conteudo": {"holdout_min": "muito", "campo_estranho": 1}},
        headers=_h(),
    )
    assert invalida.status_code == 422, invalida.text
    assert invalida.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    erros = " · ".join(invalida.json()["erros"])
    for fragmento in ("holdout_min", "campo_estranho", "breakers", "precedencia"):
        assert fragmento in erros

    # draft válido: v2 aperta holdout_min (10→15) e o breaker de optout (0,6→0,4)
    conteudo_v2: dict[str, Any] = {
        **POLITICA_SEED["conteudo"],
        "holdout_min": 15.0,
        "breakers": {**POLITICA_SEED["conteudo"]["breakers"], "optout_pct_max": 0.4},
    }
    draft = client.post("/api/v1/policies", json={"conteudo": conteudo_v2}, headers=_h())
    assert draft.status_code == 201, draft.text
    assert draft.json()["versao"] == 2 and draft.json()["estado"] == "draft"
    policy_id = draft.json()["id"]

    # sem drift ANTES de publicar (a publicada ainda é a v1 congelada na OS)
    assert client.get("/api/v1/policies/drift", headers=_h()).json()["em_drift"] == []

    # RBAC: analista NÃO publica política (portão de plataforma é do lider §8-M0)
    assert client.post(f"/api/v1/policies/{policy_id}/publicar", headers=_h()).status_code == 403
    publicada = client.post(f"/api/v1/policies/{policy_id}/publicar", headers=_h("dev-lider"))
    assert publicada.status_code == 200, publicada.text
    corpo = publicada.json()
    assert corpo["estado"] == "publicada" and corpo["publicada_em"]
    assert repo.listar_eventos(tipo="policy.published")  # tipo mínimo §2.3

    # publicar de novo → 409 (não é draft); a OS em voo NÃO mudou de versão (frozen)
    assert (
        client.post(f"/api/v1/policies/{policy_id}/publicar", headers=_h("dev-lider")).status_code
        == 409
    )
    consulta = client.get(f"/api/v1/os/{os_em_voo['id']}", headers=_h())
    assert consulta.json()["frozen"]["policy_version"] == 1  # simetria com A2

    # relatório de drift (também embutido na resposta do publicar): OS em voo
    # congelada na v1 viola holdout_min novo (5 < 15) e breaker frouxo (0,6 > 0,4)
    drift = client.get("/api/v1/policies/drift", headers=_h()).json()
    assert drift == corpo["drift"]
    assert drift["policy_publicada"] == 2 and drift["os_em_voo"] == 1
    entrada = drift["em_drift"][0]
    assert entrada["os_id"] == os_em_voo["id"]
    assert entrada["policy_version_congelada"] == 1
    regras = sorted(v["regra"] for v in entrada["violacoes"])
    assert regras == ["breakers.optout_pct_max", "holdout_min"]

    # pendências de adequação OPCIONAIS: não bloqueantes + idempotentes por origem
    abertas = client.post("/api/v1/policies/drift/pendencias", headers=_h())
    assert abertas.status_code == 201, abertas.text
    assert len(abertas.json()["pendencias_abertas"]) == 1
    pendencias = repo.listar_pendencias(os_id)
    adequacao = [p for p in pendencias if p.origem == "policy_drift:v2"]
    assert len(adequacao) == 1 and adequacao[0].bloqueante is False
    repeticao = client.post("/api/v1/policies/drift/pendencias", headers=_h())
    assert repeticao.json()["pendencias_abertas"] == []  # dedupe (re-POST não duplica)

    # nova OS com GO congela a v2 (o congelado é por campanha, não retroativo)
    os_nova = _os_com_go(client)
    assert os_nova["frozen"]["policy_version"] == 2
