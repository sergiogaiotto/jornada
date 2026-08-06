"""F03 · A política de IA Responsável GOVERNA a plataforma em execução (§10.2).

`test_F03_ia_responsavel_api.py` prova que a política tem tabela, rota, autor e data.
Isso é metade do conserto — e é exatamente a metade que o achado 8 do UAT #5 já tinha
em pé quando foi aberto: a tela de Políticas do M12 publicava, versionava e mostrava o
autor, e mesmo assim nada mudava de comportamento.

Este arquivo é a OUTRA metade, e é o entregável da onda. O auditor mediu o buraco em
uma frase: *nada fora do próprio teste importa o módulo* — `grep -rn "ia_responsavel"`
fora de `domain/ia_responsavel/` só achava `test_F03`. Os quatro parâmetros governavam
FUNÇÕES PURAS QUE NINGUÉM CHAMAVA. Um teste de unidade sobre uma função pura prova que
a função está certa; não prova que a plataforma obedece.

A regra deste arquivo é, então, uma só: **nada é verificado no domínio**. Cada teste
publica a política pela ROTA do DPO e cobra a mudança numa ROTA DE USUÁRIO — e cobra
também o efeito COLATERAL que distingue enforcement de aparência (a chamada ao LLM que
não aconteceu, o grafo que mudou no banco, o texto que sumiu do ledger).

Cada teste passa pelo estado ANTES da publicação. Sem esse "antes" o teste não
distingue política que governa de coincidência de valores — foi assim que o achado 8
sobreviveu a uma suíte verde por semanas.

Um teste por parâmetro fiado:

* (a) `dados_llm`        → a chamada ao modelo NÃO acontece  (`test_a_*`)
* (b) `retencao`         → o texto some do ledger na GRAVAÇÃO (`test_b_*`)
* (c) `decisao_automatizada` → o twin passa a aplicar sozinho (`test_c_*`)
* (f) `modelos_permitidos`   → o perfil do roster é recusado  (`test_f_*`)

`teto_tokens` e `rotulo_ia` não têm teste aqui porque não têm enforcement — e é por
isso que `politica.CAMPOS_CONTEUDO` os REJEITA. A ausência deles neste arquivo é o
mesmo fato que a rejeição deles lá.
"""

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.llm.fake import LLMFake
from app.errors import PROBLEM_CONTENT_TYPE
from application.ports.publicacoes import ORIGEM_PUBLICADA, ORIGEM_SEED
from application.services import portao_ia
from domain.ia_responsavel.politica import ACOES_VIA_AI
from domain.ia_responsavel.retencao import REDIGIDO
from tests.acceptance.test_M7 import (
    _criar_os_com_segmento,
    _gerar_jornada,
    _grafo,
    _resposta_flow,
)
from tests.acceptance.test_M11 import (
    EXPERIMENTO_14D,
    _resposta_optimize,
    _semear_jornada,
    _simular_e_congelar,
)

TENANT = "torre-movel"
MOTIVO = "Aperto pedido pelo comitê de privacidade após revisão trimestral."

# PII real (CPF com dígito verificador válido — o mascarador §10.2 confere).
CPF = "529.982.247-25"
PERGUNTA_COM_CPF = f"Meu CPF é {CPF}. Como preencho o briefing desta tela?"
CONTEXTO = "Guia do Cockpit: a saúde da OS deriva de pendências bloqueantes e SLAs."


def _h(token: str = "dev-analista", tenant: str = TENANT) -> dict[str, str]:
    return {"X-Tenant": tenant, "Authorization": f"Bearer {token}"}


# --------------------------------------------------------------- política pela ROTA
def _conservador(client: TestClient) -> dict[str, Any]:
    """Default de fábrica servido pela PRÓPRIA API — nunca redigitado no teste.

    Copiar o conteúdo esperado para dentro do teste faria o teste validar a memória de
    quem o escreveu, não o default que a aplicação usa.
    """
    vigente = client.get("/api/v1/ia-responsavel/politica", headers=_h("dev-dpo"))
    assert vigente.status_code == 200, vigente.text
    return dict(json.loads(json.dumps(vigente.json()["default_conservador"])))


def _publicar(client: TestClient, conteudo: dict[str, Any]) -> int:
    """Publica pela rota REAL do DPO (§8-M12) — nada de escrever no repo por dentro.

    Um teste que injetasse o conteúdo direto no repositório provaria que o domínio
    funciona quando alimentado à mão, que é precisamente o que já estava provado e
    precisamente o que não bastava.
    """
    resposta = client.post(
        "/api/v1/ia-responsavel/politicas",
        json={"conteudo": conteudo, "motivo": MOTIVO},
        headers=_h("dev-dpo"),
    )
    assert resposta.status_code == 201, resposta.text
    versao: int = resposta.json()["versao"]
    return versao


def _perguntar(client: TestClient, pergunta: str = PERGUNTA_COM_CPF) -> Any:
    """`POST /ajuda/perguntar` — a rota de usuário mais curta que chega ao LLM.

    Escolhida de propósito para os parâmetros (a), (b) e (f): não exige OS, segmento
    nem jornada, então o que o teste mede é o portão, sem um andaime de setup capaz de
    falhar por outro motivo e mascarar o resultado.
    """
    return client.post(
        "/api/v1/ajuda/perguntar",
        json={"pagina": "cockpit", "pergunta": pergunta, "contexto": CONTEXTO},
        headers=_h(),
    )


# ============================================================ (a) dados que vão ao LLM
def test_a_dados_llm_bloquear_impede_a_chamada_ao_modelo(client: TestClient, app: FastAPI) -> None:
    """Publicar `cpf: bloquear` e a rota para de chamar o modelo — antes ela chamava.

    O assert que carrega o peso NÃO é o status: é `len(fake.chamadas)` inalterado. Um
    422 com a chamada já feita seria vazamento com mensagem de erro bonita em cima — o
    dado teria saído do perímetro e a tela diria que não saiu. `bloquear` só se
    distingue de `mascarar` nesse ponto: mascarar deixa o texto sair (marcado, mas
    sai); bloquear é a única ação que impede a saída.
    """
    fake = LLMFake(resposta="No Cockpit, a saúde é derivada de pendências e SLAs.")
    app.state.llm = fake

    # ---- ANTES: o default MASCARA (piso do C02) e a chamada acontece normalmente
    antes = _perguntar(client)
    assert antes.status_code == 200, antes.text
    assert len(fake.chamadas) == 1, "com o default, a pergunta tem de chegar ao modelo"
    prompt = json.dumps(fake.chamadas, ensure_ascii=False)
    assert CPF not in prompt and "[CPF]" in prompt  # C02 continua valendo — nada se perdeu

    # ---- o DPO aperta: cartão/CPF em texto de marketing nunca é parâmetro legítimo
    conteudo = _conservador(client)
    conteudo["dados_llm"]["acoes"]["cpf"] = "bloquear"
    assert _publicar(client, conteudo) == 1

    # ---- DEPOIS: mesma requisição, mesmo texto, comportamento OPOSTO
    depois = _perguntar(client)
    assert depois.status_code == 422, depois.text
    assert depois.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "cpf" in depois.json()["detail"].lower()

    # O QUE PROVA O ENFORCEMENT: nenhuma chamada nova ao modelo, nenhuma linha nova no
    # ledger. O dado não saiu do perímetro e não foi gravado em lugar nenhum.
    assert len(fake.chamadas) == 1, "a política BLOQUEIA: o texto não podia chegar ao modelo"
    assert len(app.state.repositorio_os.listar_invocacoes(TENANT)) == 1

    # ---- e a régua mudou, não travou: texto SEM CPF segue passando sob a mesma v1
    limpo = _perguntar(client, "Como preencho o briefing desta tela?")
    assert limpo.status_code == 200, limpo.text
    assert len(fake.chamadas) == 2


def test_a_default_publicado_preserva_exatamente_o_piso_do_C02(
    client: TestClient, app: FastAPI
) -> None:
    """Publicar a v1 conservadora não pode fazer NINGUÉM perder proteção (§10.2).

    A troca de `mascarar_pii` por `sanear_para_llm` nos seis serviços é uma troca de
    regra fixa por regra publicada; se ela mudasse o default, a onda teria fiado a
    política ao custo de afrouxar o C02 — trocando um achado por outro. Aqui o mesmo
    texto atravessa a rota ANTES e DEPOIS da publicação do default e o prompt tem de
    ser byte a byte o mesmo.
    """
    fake = LLMFake(resposta="ok")
    app.state.llm = fake

    assert _perguntar(client).status_code == 200
    prompt_antes = json.dumps(fake.chamadas[-1], ensure_ascii=False)
    assert (
        client.get("/api/v1/ia-responsavel/politica", headers=_h("dev-dpo")).json()["origem"]
        == ORIGEM_SEED
    )

    assert _publicar(client, _conservador(client)) == 1
    assert (
        client.get("/api/v1/ia-responsavel/politica", headers=_h("dev-dpo")).json()["origem"]
        == ORIGEM_PUBLICADA
    )

    assert _perguntar(client).status_code == 200
    assert json.dumps(fake.chamadas[-1], ensure_ascii=False) == prompt_antes


def test_a_otimizacao_o_sinal_de_rejeicao_obedece_a_politica(
    client: TestClient, app: FastAPI
) -> None:
    """O `motivo` de rejeição é texto de usuário e vai ao modelo — sob a política.

    Este é o serviço que quitou a dívida de `SEM_PORTAO_HOJE` nesta onda, e ele merece
    rota própria em vez de carona no guarda-corpo estático: o `motivo` que o analista
    digita em `POST /propostas/{id}/rejeitar` vira `Aprendizado(status='sinal')`, é
    relido na rodada seguinte e entra no prompt do optimize (`sinais_de_rejeicao`).
    Texto livre com viagem de ida e volta pelo banco é o caminho mais fácil de um CPF
    chegar ao modelo dias depois de digitado, quando ninguém mais associa a tela ao
    vazamento.

    A rota é um GET que DEGRADA quando o hub cai (§10.6). A distinção que o teste cobra
    é entre as duas formas de "não deu": hub fora é 200 degradado (acidente de
    infraestrutura, a leitura continua); política que BLOQUEIA é recusa explícita
    (decisão do DPO, e escondê-la atrás de um 200 seria o achado 8 de novo).
    """
    jornada_id, os_id = _semear_jornada(client, app, experimento=EXPERIMENTO_14D)
    _simular_e_congelar(client, jornada_id)
    codigo = client.get(f"/api/v1/os/{os_id}", headers=_h()).json()["codigo"]

    def _rejeitar_todas(motivo: str) -> None:
        """Zera os pendentes — sem isso a rota não regenera (decidir é humano §1.1.3)."""
        pendentes = client.get(f"/api/v1/os/{os_id}/propostas", headers=_h())
        assert pendentes.status_code == 200, pendentes.text
        for proposta in pendentes.json()["propostas"]:
            recusa = client.post(
                f"/api/v1/propostas/{proposta['id']}/rejeitar",
                json={"motivo": motivo},
                headers=_h(),
            )
            assert recusa.status_code == 200, recusa.text

    fake = LLMFake(resposta=_resposta_optimize(codigo))
    app.state.llm = fake
    _rejeitar_todas(f"Cliente reclamou pelo CPF {CPF} — cadência agressiva demais.")
    assert app.state.repositorio_os.listar_aprendizados(os_id=os_id, status="sinal")

    # ---- ANTES: o default MASCARA e o sinal chega ao modelo já marcado (C02)
    antes = client.get(f"/api/v1/os/{os_id}/propostas", headers=_h())
    assert antes.status_code == 200, antes.text
    assert antes.json()["geradas_agora"] is True
    prompt = json.dumps(fake.chamadas[-1], ensure_ascii=False)
    assert CPF not in prompt and "[CPF]" in prompt, "o sinal tinha de chegar mascarado"

    # ---- o DPO aperta: CPF nunca é parâmetro legítimo de otimização de cadência
    conteudo = _conservador(client)
    conteudo["dados_llm"]["acoes"]["cpf"] = "bloquear"
    assert _publicar(client, conteudo) == 1

    # zera pendentes (o sinal com CPF continua no banco). A contagem é tirada DEPOIS
    # desta rodada, senão ela incluiria a geração feita aqui dentro e o assert final
    # mediria a chamada errada.
    _rejeitar_todas("Sem ganho claro de conversão.")
    chamadas_antes = len(fake.chamadas)

    # ---- DEPOIS: a MESMA rota recusa, e o modelo não é chamado
    depois = client.get(f"/api/v1/os/{os_id}/propostas", headers=_h())
    assert depois.status_code == 422, depois.text
    assert depois.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "cpf" in depois.json()["detail"].lower()
    assert len(fake.chamadas) == chamadas_antes, (
        "a política BLOQUEIA: o sinal não podia chegar ao modelo"
    )

    # ---- e a recusa NÃO é o 200-degradado do hub fora: as duas formas de "não deu"
    # continuam distinguíveis, senão a decisão do DPO viraria indistinguível de queda
    # de infraestrutura e ninguém saberia que houve política.
    app.state.llm = LLMFake(disponivel=False)
    degradado = client.get(f"/api/v1/os/{os_id}/propostas", headers=_h())
    assert degradado.status_code == 422, (
        "com a política bloqueando, nem se chega a descobrir que o hub caiu"
    )


# ==================================================================== (b) retenção
def test_b_reter_prompt_false_redige_o_ledger_na_gravacao(client: TestClient, app: FastAPI) -> None:
    """Publicar `reter_prompt: false` e o texto do usuário deixa de ser GRAVADO.

    Enforcement na ESCRITA, não na leitura: nada depende de o purge §10.4 rodar. A
    prova é lida pela rota do Art. 20 (`POST /auditoria/reconstruir/{id}`), que é
    justamente o direito que a retenção existe para equilibrar — e a linha continua
    correlacionável (`invocacao_id`, `pagina`), senão a redação teria levado a
    auditoria junto com o dado.

    Este é o parâmetro em que a onda 3 errou a POLARIDADE: a versão anterior de
    `retencao.py` listava as chaves de TEXTO e retinha todo o resto, então o CPF
    sobrevivia com o carimbo `[SUPRIMIDO...]` ao lado. Por isso o teste não se contenta
    com "o marcador apareceu": ele cobra que o texto original SUMIU.
    """
    app.state.llm = LLMFake(resposta="resposta do guia")

    # ---- ANTES: default retém (Art. 20 exige reconstruir a decisão automatizada)
    assert _perguntar(client).status_code == 200
    reconstruida = _reconstruir(client, _ultima_invocacao(app))
    assert "[CPF]" in json.dumps(reconstruida, ensure_ascii=False), "o default RETÉM o prompt"

    conteudo = _conservador(client)
    conteudo["retencao"]["reter_prompt"] = False
    assert _publicar(client, conteudo) == 1

    # ---- DEPOIS: a mesma rota grava a linha SEM o texto
    assert _perguntar(client).status_code == 200
    invocacao_id = _ultima_invocacao(app)
    depois = _reconstruir(client, invocacao_id)
    corpo = json.dumps(depois, ensure_ascii=False)

    assert REDIGIDO in corpo, "o texto tinha de ter sido substituído pelo marcador"
    assert CPF not in corpo  # (já era verdade pelo C02)
    # O ASSERT QUE IMPORTA, e o motivo de ele existir: a onda 3 errou a POLARIDADE
    # desta função. A versão anterior listava as chaves de TEXTO e retinha todo o
    # resto, então o prompt mascarado sobrevivia com `[SUPRIMIDO...]` numa chave ao
    # lado — a auditoria via o carimbo e concluía que a supressão funcionou. "O
    # marcador apareceu" é compatível com o bug; "o texto sumiu" não é.
    assert "[CPF]" not in corpo, (
        "polaridade invertida: o prompt sobreviveu com o carimbo de suprimido ao lado"
    )
    assert "briefing" not in corpo.lower(), "texto livre do usuário não podia sobreviver"

    # …e a linha continua sendo PROVA: a correlação sobrevive, senão a redação teria
    # levado a auditoria junto com o dado (é o que `SUFIXO_ID` preserva).
    assert str(invocacao_id) in corpo

    # o ledger persistido conta a mesma história (a redação é na ESCRITA, não na saída)
    gravada = app.state.repositorio_os.listar_invocacoes(TENANT)[-1]
    assert gravada.input["pergunta"] == REDIGIDO
    # `contexto_chars` é int: valor não-textual atravessa intacto (métrica sem PII)
    assert gravada.input["contexto_chars"] == len(CONTEXTO)
    # `pagina` NÃO sobrevive, e isso é o deny-by-default de `CHAVES_TECNICAS`: chave
    # não declarada nasce redigida. Custa auditabilidade (qual tela gerou a linha) e
    # erra para o lado seguro — ver a EMENDA SUGERIDA no relatório desta onda.
    assert gravada.input["pagina"] == REDIGIDO


def _ultima_invocacao(app: FastAPI) -> uuid.UUID:
    invocacoes = app.state.repositorio_os.listar_invocacoes(TENANT)
    assert invocacoes, "a rota precisa ter gravado uma linha de ledger"
    return uuid.UUID(str(invocacoes[-1].id))


def _reconstruir(client: TestClient, invocacao_id: uuid.UUID) -> dict[str, Any]:
    """Art. 20 (§8-M12): input/evidências/output da época, pela rota do DPO."""
    resposta = client.post(f"/api/v1/auditoria/reconstruir/{invocacao_id}", headers=_h("dev-dpo"))
    assert resposta.status_code == 200, resposta.text
    return dict(resposta.json())


# ======================================================== (c) decisão automatizada
def test_c_decisao_automatizada_abre_o_caminho_que_o_codigo_fechava_na_mao(
    client: TestClient, app: FastAPI
) -> None:
    """LGPD Art. 20: quem decide se o twin aplica sozinho passa a ser a POLÍTICA.

    Até esta onda `aplicado: False` era um literal escrito na mão — o próximo commit
    podia trocá-lo por `True` sem que tela, log ou DPO ficassem sabendo. O teste prova
    a virada nos DOIS sentidos com a mesma requisição: com a allowlist vazia (default)
    o grafo persistido NÃO muda; com `jornada.ajustar` publicada, a MESMA chamada passa
    a gravar — e a trilha registra que ninguém clicou.
    """
    os_, corpo = _gerar_jornada(client, app)
    jornada = corpo["jornada"]
    grafo_original = jornada["grafo"]

    proposto = _grafo(os_["codigo"])
    for no in proposto["nodes"]:
        if no["id"] == "n2":
            no["data"]["braços"] = [{"id": "tratado", "pct": 80}, {"id": "holdout", "pct": 20}]
    app.state.llm = LLMFake(resposta=_resposta_flow(proposto))

    # ---- ANTES: allowlist VAZIA (default) → a IA PROPÕE e o banco não muda
    antes = client.post(
        f"/api/v1/jornadas/{jornada['id']}/ajustar",
        json={"instrucoes": "aumente o holdout para 20%"},
        headers=_h(),
    )
    assert antes.status_code == 200, antes.text
    assert antes.json()["aplicado"] is False
    assert antes.json()["valido"] is True, "a proposta precisa ser VÁLIDA, senão o teste é vazio"
    persistida = app.state.repositorio_os.obter_jornada(uuid.UUID(jornada["id"]))
    assert persistida.grafo == grafo_original, "sem autorização, o twin não pode ter mudado"

    # ---- o DPO autoriza a automação, por ato versionado e assinado
    conteudo = _conservador(client)
    conteudo["decisao_automatizada"]["pode_aplicar_sozinho"] = ["jornada.ajustar"]
    assert _publicar(client, conteudo) == 1

    # ---- DEPOIS: a MESMA requisição passa a APLICAR
    depois = client.post(
        f"/api/v1/jornadas/{jornada['id']}/ajustar",
        json={"instrucoes": "aumente o holdout para 20%"},
        headers=_h(),
    )
    assert depois.status_code == 200, depois.text
    assert depois.json()["aplicado"] is True, "a política autorizou: o caminho automático abre"

    # O QUE PROVA O ENFORCEMENT: o grafo PERSISTIDO mudou. Não é o booleano da resposta
    # — é escrita de verdade no twin, pelo mesmo `atualizar_grafo` do PUT humano
    # (§1.1.3), que valida o §5.3 de novo e recalcula o taxímetro. Um atalho que
    # gravasse direto teria menos gates que o clique, o oposto do que o Art. 20 pede.
    gravada = app.state.repositorio_os.obter_jornada(uuid.UUID(jornada["id"]))
    assert gravada.grafo != grafo_original, "a política autorizou: o twin tinha de ter mudado"
    bracos = next(n for n in gravada.grafo["nodes"] if n["id"] == "n2")["data"]["braços"]
    assert {b["id"]: b["pct"] for b in bracos} == {"tratado": 80, "holdout": 20}

    # …e a trilha diz a VERDADE sobre quem aplicou: NINGUÉM clicou (§2.3). Sem o
    # `actor` denunciando a automação, a linha do outbox seria indistinguível de um
    # humano tendo aplicado — e o Art. 20 se apoia justamente nessa distinção.
    eventos = [
        e for e in app.state.repositorio_os.listar_eventos() if e.type == "jornada.grafo_atualizado"
    ]
    assert eventos, "aplicar tem de emitir o MESMO evento do PUT humano"
    assert eventos[-1].actor.startswith("ia:flow:politica"), eventos[-1].actor


# ---- (c) a MEDIDA do que ainda não é governado: ação publicável sem consumidor
#
# O parâmetro (c) está fiado — `test_c_*` acima prova a virada por rota. Mas ele governa
# UMA das SETE ações que a política aceita publicar. Para as outras seis o DPO publica,
# recebe 201, a tela mostra versão/autor/data, e nada muda: é o achado 8 do UAT #5 na
# granularidade do vocabulário. A onda não fecha essa lacuna (cada ação exige um caminho
# automático de verdade, que é feature, não conserto de auditoria) — então ela fica
# MEDIDA e travada, em vez de descrita num relatório que ninguém relê.
ACOES_SEM_ENFORCEMENT_HOJE = frozenset(
    {
        "consultor.preencher_briefing",  # §8-M3
        "audiencia.montar_sql",  # §8-M5
        "criativo.gerar",  # §8-M6
        "insight.responder",  # §8-M10
        "otimizacao.propor",  # §8-M11 · serviço fiado em (a)/(b)/(f), não em (c)
        "ajuda.responder",  # §8-M-Guia
    }
)


def test_c_acao_publicavel_sem_consumidor_e_divida_medida() -> None:
    """Toda ação de `ACOES_VIA_AI` ou tem consumidor, ou está declarada como inerte.

    Comparação por igualdade, nos dois sentidos, pelo mesmo motivo dos guarda-corpos
    de portão: fiar uma ação obriga a tirá-la daqui (senão a dívida nunca encolhe), e
    ACRESCENTAR uma ação ao vocabulário obriga a declarar que ela nasce inerte — que é
    a decisão que ninguém quer tomar por escrito, e exatamente por isso tem de ser
    escrita.
    """
    inertes = set(ACOES_VIA_AI) - portao_ia.ACOES_FIADAS

    assert inertes == set(ACOES_SEM_ENFORCEMENT_HOJE), (
        f"ações publicáveis sem consumidor mudaram: {sorted(inertes)} "
        f"(declarado: {sorted(ACOES_SEM_ENFORCEMENT_HOJE)}). Se SUBIU, `ACOES_VIA_AI` "
        "ganhou um nome que o DPO pode publicar e nenhum serviço lê — autorização "
        "publicada e inerte é o achado 8 do UAT #5 (§10.2). Se DESCEU, a ação foi "
        "fiada: acrescente-a a `portao_ia.ACOES_FIADAS` e remova daqui."
    )


def test_c_publicar_acao_inerte_e_aceito_e_nao_muda_nada(client: TestClient, app: FastAPI) -> None:
    """A prova POR ROTA de que a dívida acima é real, e não pessimismo de comentário.

    `otimizacao.propor` é o caso mais afiado: o serviço FOI fiado nesta onda em (a),
    (b) e (f), então tudo indica que ele obedece à política — e obedece, menos em (c).
    O DPO publica a automação pela tela, recebe 201, e a rota continua exigindo que uma
    pessoa aprove cada proposta. O teste fixa esse fato para que ele seja encontrado por
    quem for fiar a ação, em vez de ser descoberto por um cliente.
    """
    jornada_id, os_id = _semear_jornada(client, app, experimento=EXPERIMENTO_14D)
    _simular_e_congelar(client, jornada_id)
    codigo = client.get(f"/api/v1/os/{os_id}", headers=_h()).json()["codigo"]

    conteudo = _conservador(client)
    conteudo["decisao_automatizada"]["pode_aplicar_sozinho"] = ["otimizacao.propor"]
    assert _publicar(client, conteudo) == 1, "a política ACEITA a ação — ela é do vocabulário"

    app.state.llm = LLMFake(resposta=_resposta_optimize(codigo))
    propostas = client.get(f"/api/v1/os/{os_id}/propostas", headers=_h())
    assert propostas.status_code == 200, propostas.text

    # A AUTORIZAÇÃO É INERTE: as propostas nascem `proposta`, esperando decisão humana,
    # exatamente como nasciam antes da publicação. Nenhuma vira `aceita` sozinha e
    # nenhuma jornada nova é escrita — compare com `test_c_*` do `jornada.ajustar`, em
    # que o grafo PERSISTIDO muda. Aqui não muda nada, e é esse "nada" que é a dívida.
    assert propostas.json()["propostas"], "o teste é vazio se o optimize não propôs"
    assert {p["estado"] for p in propostas.json()["propostas"]} == {"proposta"}
    versoes = app.state.repositorio_os.listar_jornadas(os_id=os_id)
    assert len(versoes) == 1, "nenhuma versão nova: ninguém aplicou, nem a IA nem humano"


# ======================================================= (f) modelos permitidos §7.2
def test_f_modelo_fora_da_politica_e_recusado_antes_da_chamada(
    client: TestClient, app: FastAPI
) -> None:
    """Publicar um roster que não contém o perfil da skill e a chamada é RECUSADA.

    O roster §7.2 vive no front-matter do SKILL.md: quem edita a skill troca o perfil e
    nada além da revisão de código percebe. "Qual modelo pode ver o dado deste tenant"
    é pergunta de governança, então quem responde passa a ser a política publicada.

    A prova é o `fake.chamadas` inalterado: recusar DEPOIS de chamar seria contabilizar
    o gasto e expor o dado ao modelo que a política acabou de proibir.
    """
    fake = LLMFake(resposta="resposta do guia")
    app.state.llm = fake

    # ---- ANTES: o default PINA o roster (`ajuda: 20b`) — a chamada acontece
    antes = _perguntar(client, "Como preencho o briefing desta tela?")
    assert antes.status_code == 200, antes.text
    assert len(fake.chamadas) == 1
    assert fake.chamadas[-1].get("perfil") == "20b", "o agente ajuda roda no 20b (§7.2)"

    # ---- o DPO restringe o agente `ajuda` ao 120b: o 20b deixa de ser autorizado
    conteudo = _conservador(client)
    conteudo["modelos_permitidos"]["ajuda"] = ["120b"]
    assert _publicar(client, conteudo) == 1

    # ---- DEPOIS: mesma rota, recusa explícita e NENHUMA chamada nova
    depois = _perguntar(client, "Como preencho o briefing desta tela?")
    assert depois.status_code == 409, depois.text
    assert depois.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    detalhe = depois.json()["detail"]
    assert "20b" in detalhe and "ajuda" in detalhe, detalhe

    assert len(fake.chamadas) == 1, "a política não autoriza o perfil: nada podia ser chamado"
    assert len(app.state.repositorio_os.listar_invocacoes(TENANT)) == 1


def test_f_restringir_um_agente_nao_derruba_os_outros(client: TestClient, app: FastAPI) -> None:
    """O aperto é POR AGENTE — restringir `ajuda` não pode calar o `flow`.

    Contraprova do teste acima: sem ela, um portão que recusasse tudo passaria no teste
    anterior e ninguém veria a diferença entre "governa" e "quebrou".
    """
    conteudo = _conservador(client)
    conteudo["modelos_permitidos"]["ajuda"] = ["120b"]
    assert _publicar(client, conteudo) == 1

    app.state.llm = LLMFake(resposta="resposta do guia")
    assert _perguntar(client, "Como preencho o briefing?").status_code == 409

    # o flow (120b, intocado na política) segue trabalhando na mesma requisição-irmã
    os_ = _criar_os_com_segmento(client, app)
    app.state.llm = LLMFake(resposta=_resposta_flow(_grafo(os_["codigo"])))
    gerada = client.post(f"/api/v1/os/{os_['id']}/jornada/gerar", headers=_h())
    assert gerada.status_code == 201, gerada.text


# ============================================ guarda-corpo: o SÉTIMO serviço não nasce mudo
#
# Serviços que chamam o LLM HOJE sem passar pelo portão de IA Responsável (§10.2).
#
# Esta lista é uma DÍVIDA declarada, não uma isenção: ela existe para que o teste
# abaixo possa falhar quando um serviço NOVO aparecer, em vez de simplesmente não
# existir. `portao_ia` documenta o modo de falha que ela cobre — "o sétimo serviço, o
# que ainda não existe, nasce sem nenhuma [checagem], em silêncio".
#
# `otimizacao_service` SAIU desta lista nesta onda: ele mandava ao modelo os `sinais`
# (`aprendizado.texto`) — TEXTO LIVRE escrito por gente, direto do `motivo` de rejeição —
# sem saneamento, sem conferência de perfil e sem retenção no ledger. A dívida foi
# quitada com a fiação do serviço MAIS o teste por rota que a regra abaixo exige
# (`test_a_otimizacao_*`), e a lista encolheu junto: a bidirecionalidade do assert é o
# que obriga as duas coisas a andarem juntas.
#
# Sobra `atelie_service`, que escolhe o `modelo_perfil` no front-matter da skill e chama
# o hub três vezes sem conferir o roster contra a política — o parâmetro (f) não alcança
# o harness. Ele é MENOS grave que o optimize era, e a diferença importa para priorizar:
# o Ateliê roda `harness_case.input` (golden dataset curado por quem edita a skill, não
# texto que um usuário digitou numa tela), então o vetor de PII é indireto. Não é
# isenção — é a ordem em que a dívida deve ser paga.
#
# Tirar um nome daqui é o trabalho; a regra da onda vale para ele como valeu para os
# sete: o serviço só sai desta lista junto com o teste por ROTA que prova a mudança de
# comportamento.
SEM_PORTAO_HOJE = frozenset({"atelie_service.py"})

# …e a dívida do parâmetro (f) medida por CALL SITE, que é a unidade em que ela existe.
#
# A primeira versão deste guarda-corpo contava ARQUIVOS ("tem `_llm.chat` e não importa
# `portao_ia`") e por isso não via o furo mais fácil de aparecer numa revisão: o arquivo
# JÁ fiado que ganha uma chamada NOVA sem conferência de perfil. O diff inteiro passa no
# teste porque o `import` continua lá em cima — que é o mesmo modo de falha do achado 8,
# só que dentro de um arquivo em vez de dentro da plataforma.
#
# `criativo_service.py` é esse caso HOJE, e ele não estava declarado em lugar nenhum
# fora de um comentário no próprio serviço: dos seus dois `chat`, o de avisos de
# compliance usa o perfil LITERAL `"20b"` atribuído ao `content` (cujo roster §7.2
# declara 120b). Conferir esse perfil recusaria a geração de criativo sob a política
# DEFAULT — e o default não muda nesta fiação. A correção é do ROSTER (entrada própria
# de 20b, como o `guard` já tem), registrada na EMENDA SUGERIDA do relatório.
#
# Contado sobre `portao.autorizar_modelo(` e não sobre `autorizar_modelo(`: o serviço do
# criativo CITA o nome da função em prosa para explicar por que não a chama, e a
# contagem ingênua lia essa menção como se fosse enforcement — um guarda-corpo que se
# deixa satisfazer por um comentário mede a documentação, não o código.
CHAMADAS_SEM_AUTORIZACAO_HOJE: dict[str, int] = {
    "atelie_service.py": 3,  # harness do Ateliê: perfil vem do front-matter da skill
    "criativo_service.py": 1,  # warn de compliance no 20b literal (divergência de roster)
}


def _servicos() -> list[Path]:
    pasta = Path(__file__).resolve().parents[2] / "application" / "services"
    return sorted(p for p in pasta.glob("*.py") if "_llm.chat" in p.read_text(encoding="utf-8"))


def test_todo_servico_que_chama_o_llm_passa_pelo_portao() -> None:
    """Serviço que fala com o modelo e não conhece o portão é parâmetro inerte de novo.

    Checagem ESTÁTICA de propósito: um teste de comportamento só cobre a rota que
    alguém lembrou de escrever, e o furo aqui é exatamente o que ninguém lembrou. O
    conjunto é comparado nos DOIS sentidos — um serviço que ganhe o portão precisa sair
    de `SEM_PORTAO_HOJE`, senão a dívida vira ficção que nunca diminui.
    """
    sem_portao = {
        arquivo.name
        for arquivo in _servicos()
        if "portao_ia" not in arquivo.read_text(encoding="utf-8")
    }

    novos = sem_portao - SEM_PORTAO_HOJE
    assert novos == set(), (
        f"{sorted(novos)} chamam o LLM sem passar pelo portão de IA Responsável (§10.2). "
        "Os quatro parâmetros publicados pelo DPO não governam esta chamada: o texto do "
        "usuário sai sem saneamento, o perfil não é conferido e o ledger não respeita a "
        "retenção. Injete `PublicacoesIaPort` e use `portao_ia.de(...)`."
    )
    quitados = SEM_PORTAO_HOJE - sem_portao
    assert quitados == set(), (
        f"{sorted(quitados)} já passam pelo portão — remova de `SEM_PORTAO_HOJE`. "
        "Dívida declarada que não encolhe deixa de ser dívida e vira desculpa."
    )


def test_toda_chamada_ao_llm_confere_o_perfil_contra_a_politica() -> None:
    """O parâmetro (f) é por CALL SITE — o teste acima, por arquivo, não bastava.

    Um `chat` novo dentro de um serviço já fiado é o furo barato: o `import portao_ia`
    segue no topo, o teste por arquivo continua verde, e a chamada nova manda o dado a
    um modelo que a política do tenant não autorizou. Aqui a conta é `chat` menos
    `autorizar_modelo` por arquivo, e a diferença tem de bater EXATAMENTE com a dívida
    declarada — nos dois sentidos, para que quitar uma dívida obrigue a declarar isso.
    """
    medido = {
        arquivo.name: (
            (texto := arquivo.read_text(encoding="utf-8")).count("_llm.chat(")
            - texto.count("portao.autorizar_modelo(")
        )
        for arquivo in _servicos()
    }
    desprotegidas = {nome: n for nome, n in medido.items() if n}

    assert desprotegidas == CHAMADAS_SEM_AUTORIZACAO_HOJE, (
        f"chamadas ao LLM sem `portao.autorizar_modelo` mudaram: {desprotegidas} "
        f"(declarado: {CHAMADAS_SEM_AUTORIZACAO_HOJE}). Se SUBIU, um call site novo "
        "escolhe o modelo sem passar pela política do tenant (§7.2 · parâmetro (f)) — "
        "chame `portao.autorizar_modelo(skill.nome, skill.modelo_perfil)` imediatamente "
        "antes do `chat`. Se DESCEU, a dívida foi quitada: atualize o dicionário, senão "
        "ela deixa de encolher de verdade e vira desculpa permanente."
    )
