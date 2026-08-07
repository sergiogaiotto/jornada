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
from tests.acceptance.test_M6 import CELULAS_CONFORMES
from tests.acceptance.test_M6 import _criar_os as _criar_os_m6
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
from tests.acceptance.test_M12 import (
    NOTAS_VERDES,
    _agentes,
    _criar_candidata,
    _judge,
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


# ------------------------------------ as duas rotas cujo ledger carrega EVIDÊNCIAS
#
# Texto exatamente na forma que a auditoria mediu saindo por `GET /auditoria` e por
# `POST /auditoria/reconstruir` com `reter_prompt: false, reter_resposta: false`
# publicado: a `resposta` vinha `[SUPRIMIDO...]` e isto vinha inteiro ao lado.
EVIDENCIA_LIVRE = "Solicitante Joao (contato joao@acme.com.br) pediu 500k na conversa"


def _conversar_com_o_consultor(client: TestClient, app: FastAPI) -> None:
    """`POST /pedidos/{id}/mensagem` — aqui a evidência é TRECHO DA CONVERSA.

    Escolhida porque é o pior caso do campo: `agents/consultor.py` monta `evidencias`
    com `str(e).strip()` do que o modelo devolveu, e o modelo é instruído a citar a
    conversa do solicitante. "Ref versionada" é o que o comentário de `CHAVES_TECNICAS`
    afirmava; isto é o que o campo carrega.
    """
    app.state.llm = LLMFake(
        resposta=json.dumps(
            {
                "resposta": "Com base em campanhas anteriores, sugiro verba e janela.",
                "inferencias": [
                    {"campo": "verba", "valor": "R$ 500.000", "evidencias": [EVIDENCIA_LIVRE]}
                ],
            },
            ensure_ascii=False,
        )
    )
    pedido = client.post(
        "/api/v1/pedidos",
        json={
            "solicitante": {"nome": "Ana Lima", "area": "Marketing"},
            "conteudo": {
                "objetivo": "Upgrade de pós-pago para 5G",
                "publico": "Pós-pago ativo há 12+ meses",
                "oferta": "20GB de bônus por 6 meses",
            },
        },
        headers=_h("portal-dev"),
    )
    assert pedido.status_code == 201, pedido.text
    resposta = client.post(
        f"/api/v1/pedidos/{pedido.json()['id']}/mensagem",
        json={"mensagem": "Pode usar a campanha de upgrade do ano passado como referência."},
        headers=_h("portal-dev"),
    )
    assert resposta.status_code == 200, resposta.text


def _gerar_sql_com_o_engineer(client: TestClient, app: FastAPI) -> None:
    """`POST /os/{id}/segmento/gerar-sql` — aqui a evidência vem do corpus RAG."""
    os_ = client.post(
        "/api/v1/os",
        json={
            "nome": "Upgrade Pós-Pago 5G",
            "tshirt": "G",
            "briefing": {"publico": {"valor": "Pós-pago sem 5G", "inferido": False}},
        },
        headers=_h(),
    )
    assert os_.status_code == 201, os_.text
    app.state.llm = LLMFake(
        resposta=json.dumps(
            {
                "sql": "SELECT contato_hash FROM clientes",
                "explicacao": [{"clausula": "WHERE", "explicacao": "listas de supressão"}],
                "evidencias": [EVIDENCIA_LIVRE],
            },
            ensure_ascii=False,
        )
    )
    gerado = client.post(
        f"/api/v1/os/{os_.json()['id']}/segmento/gerar-sql",
        json={"instrucoes": "Pós-pago elegível a upgrade 5G, todos os canais com opt-in."},
        headers=_h(),
    )
    assert gerado.status_code == 201, gerado.text


def test_b_reter_false_redige_tambem_a_coluna_evidencias(client: TestClient, app: FastAPI) -> None:
    """A auditoria lia `[SUPRIMIDO...]` no `output` e o texto INTACTO na coluna ao lado.

    Dois furos numa linha só de ledger, e nenhum deles alcançável por configuração:

    1. `invocacao.evidencias` é COLUNA (§4.1), não parte de `input`/`output` — os
       serviços atribuíam `evidencias=` fora do `portao.reter_output(...)`, então
       nenhum valor de política mudava aquele campo. Publicar `reter_prompt: false` E
       `reter_resposta: false` deixava o texto do solicitante legível.
    2. dentro do `output`, `evidencias` estava em `CHAVES_TECNICAS` com a justificativa
       de ser "id e ref `nome@versao`" — premissa falsa em todos os produtores.

    O teste cobra os dois pelas ROTAS: a de usuário que grava e a do DPO que lê
    (`POST /auditoria/reconstruir`, o próprio direito do Art. 20 que a retenção
    equilibra). Assim como no teste do prompt, "o marcador apareceu" é compatível com o
    bug — o que separa supressão de carimbo é o texto ter SUMIDO.
    """
    # ---- ANTES: o default retém, e a evidência é a prova do Art. 20 por inteiro
    _conversar_com_o_consultor(client, app)
    antes = _reconstruir(client, _ultima_invocacao(app))
    assert EVIDENCIA_LIVRE in json.dumps(antes, ensure_ascii=False), (
        "com o default, a evidência TEM de estar lá — é o que explica a inferência"
    )
    assert antes["evidencias"] == [EVIDENCIA_LIVRE]

    # ---- o DPO desliga os dois lados
    conteudo = _conservador(client)
    conteudo["retencao"]["reter_prompt"] = False
    conteudo["retencao"]["reter_resposta"] = False
    assert _publicar(client, conteudo) == 1

    # ---- DEPOIS: a mesma rota, e o texto não chega a ser gravado em NENHUM dos dois
    for rota in (_conversar_com_o_consultor, _gerar_sql_com_o_engineer):
        rota(client, app)
        invocacao_id = _ultima_invocacao(app)
        corpo = json.dumps(_reconstruir(client, invocacao_id), ensure_ascii=False)

        assert REDIGIDO in corpo, f"{rota.__name__}: nada foi suprimido"
        assert "joao@acme.com.br" not in corpo, f"{rota.__name__}: contato do titular sobreviveu"
        assert "pediu 500k" not in corpo, (
            f"{rota.__name__}: a coluna `evidencias` devolveu o texto que o `output` "
            "diz ter suprimido — é o furo com o carimbo ao lado"
        )
        # a linha continua sendo PROVA: correlação intacta (é o que `SUFIXO_ID` guarda)
        assert str(invocacao_id) in corpo

        # o ledger persistido conta a mesma história — a redação é na ESCRITA
        gravada = app.state.repositorio_os.listar_invocacoes(TENANT)[-1]
        assert gravada.evidencias == [REDIGIDO], f"{rota.__name__}: coluna fora da política"

        # a OUTRA rota de leitura do mesmo ledger: `GET /auditoria` embute o detalhe
        # completo da invocação no evento via_ai (o "clicável" da T16). Redigir na
        # ESCRITA é o que faz as duas rotas contarem a mesma história sem nenhuma
        # delas precisar filtrar nada na saída.
        trilha = client.get("/api/v1/auditoria?via_ai=true", headers=_h("dev-dpo"))
        assert trilha.status_code == 200, trilha.text
        embutida = [
            e["invocacao"]
            for e in trilha.json()["eventos"]
            if e.get("invocacao", {}).get("invocacao_id") == str(invocacao_id)
        ]
        assert embutida, f"{rota.__name__}: a trilha tem de embutir a invocação via_ai"
        na_trilha = json.dumps(embutida[0], ensure_ascii=False)
        assert "pediu 500k" not in na_trilha and "joao@acme.com.br" not in na_trilha
        assert REDIGIDO in na_trilha

    # e a mesma evidência ANINHADA dentro do `output` do consultor (a chave que estava
    # declarada como técnica) também some — os dois caminhos do mesmo texto.
    inferidas = [
        i
        for i in app.state.repositorio_os.listar_invocacoes(TENANT)
        if i.output and "inferencias" in i.output and i.output["inferencias"]
    ]
    assert inferidas, "o consultor tem de ter gravado inferências para o teste valer"
    assert inferidas[-1].output["inferencias"][0]["evidencias"] == [REDIGIDO]


# PII do titular na forma em que ela chega de verdade num tenant de telco: nome composto
# com preposição (sem âncora sintática que detector nenhum pegue com confiança), CPF
# pontuado e celular com DDI. Nenhum destes é o CPF do topo do arquivo de propósito — o
# que se mede aqui é o campo em que a PII entra, não a capacidade do mascarador.
TITULAR = "Maria da Conceicao dos Santos"
CONTATO_TITULAR = "maria.da.conceicao@vivo.com.br"


def test_b_reter_false_nao_deixa_pii_sobreviver_em_chave_de_id_do_kv_master(
    client: TestClient, app: FastAPI
) -> None:
    """`*_id` preservava QUALQUER escalar — e no `kv_master` quem nomeia é o USUÁRIO.

    Este teste é a terceira encenação do MESMO modo de falha, e a razão de ele existir
    na camada de rota é que as duas anteriores foram fechadas no domínio e a terceira
    continuou de pé mesmo assim:

    * onda 3 — `evidencias` preservada por estar em `CHAVES_TECNICAS`;
    * onda 4 — chave preservada com dicionário embaixo atravessando inteira;
    * aqui   — chave preservada com ESCALAR embaixo, onde o nome da chave vem do corpo
      da requisição. `POST /os/{id}/criativos/gerar` recebe `kv_master: dict[str, Any]`,
      grava-o no `input` do ledger CRU (só `instrucoes` passa por `portao.sanear`), e
      `validar_kv_master` só olha termos proibidos de marketing — não nomes de campo.

    Medido pela rota, com `reter_prompt: false` + `reter_resposta: false` publicados:

        "kv_master": {"produto":    "[SUPRIMIDO POR POLITICA DE RETENCAO]",
                      "cliente_id": "Maria da Conceicao dos Santos - <CPF>",
                      "contato_id": "maria.da.conceicao@vivo.com.br",
                      "documento":  11144477735}

    O marcador ao lado do titular intacto — a supressão em que a auditoria acredita e
    que não aconteceu, agora sem adversário nenhum: basta o analista de campanha nomear
    um campo de KV `cliente_id`, que é como campos de KV se chamam.

    E `documento` mostra a outra metade: CPF cabe num JSON number, e valor não-textual
    atravessava a redação por não ser `str`.
    """
    conteudo = _conservador(client)
    conteudo["retencao"]["reter_prompt"] = False
    conteudo["retencao"]["reter_resposta"] = False
    assert _publicar(client, conteudo) == 1

    # ATENÇÃO — a `evidencias` deste fake é deliberadamente SEM PII, e isso é uma
    # dívida declarada, não um descuido. A coluna `evidencias` do criativo NÃO passa
    # pelo portão: `criativo_service.py` grava `evidencias=list(evidencias)` no
    # construtor e ainda sobrescreve com `invocacoes[-1].evidencias = list(saida.
    # evidencias)` depois. Com PII aqui, este teste falharia — e falharia pelo furo do
    # M6, que é de outro arquivo, escondendo o que ele veio medir (o `kv_master`).
    # Enquanto `portao.reter_evidencias` não entrar naquele serviço, `reter_* = false`
    # continua vazando pela rota do criativo. Ver VEREDITO/EMENDA desta rodada.
    app.state.llm = LLMFake(
        respostas_por_perfil={
            "120b": json.dumps(
                {
                    "celulas": CELULAS_CONFORMES,
                    "evidencias": ["criativos: KV master aprovado na campanha 5G (T6)"],
                    "resposta": "Matriz montada.",
                },
                ensure_ascii=False,
            ),
            "20b": json.dumps({"avisos": []}),
        }
    )
    os_ = _criar_os_m6(client)
    gerado = client.post(
        f"/api/v1/os/{os_['id']}/criativos/gerar",
        json={
            "kv_master": {
                "produto": "5G",
                "cliente_id": f"{TITULAR} - {CPF}",  # chave do USUÁRIO, valor com PII
                "contato_id": CONTATO_TITULAR,
                "documento": 11144477735,  # CPF como JSON number
            },
            "canais": ["email", "sms"],
            "variantes": ["A", "B"],
        },
        headers=_h(),
    )
    assert gerado.status_code == 201, gerado.text

    # Todas as linhas que a rota gravou, lidas pela rota do DPO (Art. 20).
    invocacoes = app.state.repositorio_os.listar_invocacoes(TENANT)
    assert invocacoes, "a rota do criativo tem de ter gravado ledger"
    for invocacao in invocacoes:
        corpo = json.dumps(_reconstruir(client, invocacao.id), ensure_ascii=False)
        assert TITULAR not in corpo, f"nome do titular sobreviveu em {corpo}"
        assert CONTATO_TITULAR not in corpo, f"contato do titular sobreviveu em {corpo}"
        assert CPF not in corpo, f"CPF sobreviveu em {corpo}"
        assert "11144477735" not in corpo, f"CPF como número sobreviveu em {corpo}"

    # ...e a linha continua correlacionável: `os_id` é UUID, tem FORMA de id e fica.
    com_kv = [i for i in invocacoes if i.input and "kv_master" in i.input]
    assert com_kv, "o teste precisa de uma linha com `kv_master` para valer"
    assert com_kv[-1].input["os_id"] == os_["id"]
    assert com_kv[-1].input["kv_master"]["cliente_id"] == REDIGIDO


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


# ============================ o Ateliê (§8-M12): o serviço que estava INTEIRO fora
#
# Os três testes abaixo são o "antes e depois" do único serviço da plataforma que não
# conhecia o portão. A auditoria mediu, com a política MAIS restritiva publicada:
#
#   [DRY-RUN]  200 | CPF em claro no prompt? True | EMAIL em claro? True
#   [DRY-RUN]  perfis usados = ['120b']        <- `modelos_permitidos` ignorado
#   [DRY-RUN]  invocacoes gravadas = 0         <- o Art. 20 não alcançava o caminho
#
# Cada linha daquela medição vira um teste por ROTA aqui, com o "antes" preservado: sem
# o antes, os asserts não distinguiriam política que governa de coincidência de valores.
#
# O Ateliê é a rota MAIS exposta a esse tipo de furo, e não a menos: o `modelo_perfil`
# está no front-matter do SKILL.md que o analista DIGITA na tela do T16 (§7.1). Nos
# outros sete serviços a skill é arquivo de disco revisado em PR; aqui é entrada de
# usuário escolhendo com qual modelo o dado do tenant vai conversar.
EMAIL_ATELIE = "joao.silva@acme.com.br"
ENTRADA_COM_PII = {
    "pedido": f"Cliente {EMAIL_ATELIE}, CPF {CPF}, quer upgrade para 5G",
    "canal": "email",
}


def _candidata_do_engineer(client: TestClient) -> str:
    """Skill 1.1 do `engineer` em `em_revisao` (helpers do M12 — nada redigitado aqui).

    `engineer` porque é o agente com golden dataset E com a v1.0 publicada nas seeds
    (§11.4): o dry-run precisa dos DOIS lados para que a contagem de chamadas signifique
    alguma coisa, e o harness precisa dos casos.
    """
    return _criar_candidata(client, _agentes(client)["engineer"]["id"])


def test_a_atelie_dry_run_saneia_a_entrada_digitada_na_tela(
    client: TestClient, app: FastAPI
) -> None:
    """`POST /skills/{id}/dry-run`: a `entrada` é corpo de POST, não golden dataset.

    O guarda-corpo estático desta frente declarava o Ateliê como dívida "menos grave"
    porque ele rodaria `harness_case.input` curado. Metade da rota é isso; a outra
    metade é este endpoint, em que o texto vem inteiro do navegador — e era por ele que
    o CPF saía em claro.
    """
    skill_id = _candidata_do_engineer(client)
    fake = LLMFake(resposta='{"sql": "SELECT contato_hash FROM clientes"}')
    app.state.llm = fake

    # ---- ANTES: o default MASCARA (piso do C02) e os DOIS lados recebem o texto marcado
    antes = client.post(
        f"/api/v1/skills/{skill_id}/dry-run", json={"entrada": ENTRADA_COM_PII}, headers=_h()
    )
    assert antes.status_code == 200, antes.text
    assert len(fake.chamadas) == 2, "lado a lado: versão publicada atual + candidata"
    prompt = json.dumps(fake.chamadas, ensure_ascii=False)
    assert CPF not in prompt and EMAIL_ATELIE not in prompt
    assert "[CPF]" in prompt and "[EMAIL]" in prompt
    # …e a tela devolve o que REALMENTE foi ao modelo: um lado a lado que exibisse o
    # texto original faria o revisor comparar duas saídas de um prompt que não existiu.
    assert CPF not in json.dumps(antes.json(), ensure_ascii=False)

    # ---- o DPO aperta: CPF em pedido de segmentação nunca é parâmetro legítimo
    conteudo = _conservador(client)
    conteudo["dados_llm"]["acoes"]["cpf"] = "bloquear"
    assert _publicar(client, conteudo) == 1

    # ---- DEPOIS: mesma requisição, recusa explícita, e NENHUMA chamada nova
    depois = client.post(
        f"/api/v1/skills/{skill_id}/dry-run", json={"entrada": ENTRADA_COM_PII}, headers=_h()
    )
    assert depois.status_code == 422, depois.text
    assert depois.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    assert "cpf" in depois.json()["detail"].lower()
    assert len(fake.chamadas) == 2, "a política BLOQUEIA: o texto não podia chegar ao modelo"

    # e segue sendo régua, não trava: entrada sem CPF passa sob a MESMA versão
    limpa = client.post(
        f"/api/v1/skills/{skill_id}/dry-run",
        json={"entrada": {"pedido": "Pós-pago elegível a upgrade 5G"}},
        headers=_h(),
    )
    assert limpa.status_code == 200, limpa.text
    assert len(fake.chamadas) == 4


# Cadastro de telco como ele chega de verdade: o sinal do titular está na CHAVE, não no
# formato do valor. Nenhuma destas linhas casa com um regex de CPF/e-mail — é justamente
# por isso que a versão anterior desta rota as mandava inteiras ao modelo.
ENTRADA_COM_PII_DE_CADASTRO: dict[str, Any] = {
    "nome do titular": "Maria da Conceição Souza",
    "cliente_id": "Maria Aparecida da Silva - 529.982.247-25",
    "dados do titular": {"nome completo": "João dos Santos", "cep": "01310100"},
    f"contato {EMAIL_ATELIE}": "preferencial",
}


def test_a_atelie_a_arvore_do_dry_run_e_DIGITACAO_e_a_chave_ancora(
    client: TestClient, app: FastAPI
) -> None:
    """A `entrada` do dry-run é `dict[str, Any]` ABERTO — o analista escolhe a CHAVE.

    A primeira fiação desta rota saneou a árvore com `mascarar_estrutura`, que por
    contrato ignora a chave e não a mascara (o certo para payload de evento e trace,
    §4.1). Só que aqui a chave é DIGITAÇÃO, igual ao `pedido.conteudo` do intake — e a
    auditoria mediu o preço: nome, CEP, RG e data de nascimento cujo único sinal é a
    chave (`{"nome do titular": "Maria da Conceição Souza"}`) chegavam INTEIROS ao
    prompt, e PII escrita na PRÓPRIA chave (`{"contato joao@x.com.br": ...}`) também —
    o achado 9 do UAT #5 renascido nesta rota.

    O teste cobra as duas metades porque elas falham por motivos diferentes: âncora na
    chave (que só `mascarar_campos` usa) e chave como dado (que só `mascarar_campos`
    mascara). Um nome SEM âncora nenhuma continua saindo em claro — é limite declarado
    de `domain/privacidade/mascarar.py`, não promessa desta rota.
    """
    skill_id = _candidata_do_engineer(client)
    fake = LLMFake(resposta='{"sql": "SELECT contato_hash FROM clientes"}')
    app.state.llm = fake

    resposta = client.post(
        f"/api/v1/skills/{skill_id}/dry-run",
        json={"entrada": ENTRADA_COM_PII_DE_CADASTRO},
        headers=_h(),
    )
    assert resposta.status_code == 200, resposta.text
    prompt = json.dumps(fake.chamadas, ensure_ascii=False)

    # o dado do titular não chegou ao modelo…
    for vazamento in ("Conceição", "Aparecida", "dos Santos", "01310100", EMAIL_ATELIE, CPF):
        assert vazamento not in prompt, f"{vazamento!r} saiu em claro no prompt do Ateliê"
    # …e os marcadores provam que foi mascaramento, não uma entrada que se perdeu
    for marcador in ("[NOME]", "[CEP]", "[EMAIL]", "[CPF]"):
        assert marcador in prompt, f"{marcador} ausente: a árvore não passou pelo portão"
    # a tela mostra o mesmo texto que foi ao modelo (senão o lado a lado mentiria)
    assert "Conceição" not in json.dumps(resposta.json(), ensure_ascii=False)

    # ---- e o `bloquear` do DPO alcança a ÁRVORE, não só o texto corrido.
    #
    # Esta é a metade que faltava e que ninguém veria: mascarar e bloquear são o MESMO
    # parâmetro (a), e a rota mascarava `nome` sem honrar `nome: bloquear` — seguia
    # adiante quando o DPO mandara recusar. Menos estrito que o publicado, em silêncio.
    conteudo = _conservador(client)
    conteudo["dados_llm"]["acoes"]["nome"] = "bloquear"
    assert _publicar(client, conteudo) == 1
    chamadas = len(fake.chamadas)

    bloqueado = client.post(
        f"/api/v1/skills/{skill_id}/dry-run",
        json={"entrada": {"nome_do_titular": "Maria da Conceição Souza"}},
        headers=_h(),
    )
    assert bloqueado.status_code == 422, bloqueado.text
    assert "nome" in bloqueado.json()["detail"].lower()
    assert len(fake.chamadas) == chamadas, "bloqueado: o texto não podia chegar ao modelo"

    # segue régua, não trava: a MESMA versão deixa passar árvore de negócio inteira
    limpa = client.post(
        f"/api/v1/skills/{skill_id}/dry-run",
        json={
            "entrada": {
                "pergunta": "quantos clientes Fibra Residencial em churn?",
                "nome_da_campanha": "Black Friday 2026",
                "os_id": "OS-2026-0457",
                "verba": 480000,
                "janela": "01/10 a 15/10",
                "contato_hash": "a3f5b8c2d1e4f6a7b8c9d0e1f2a3b4c5",
            }
        },
        headers=_h(),
    )
    assert limpa.status_code == 200, limpa.text
    # NADA do texto de negócio foi destruído: o controle que come briefing é desligado,
    # e controle desligado protege zero.
    assert limpa.json()["entrada"] == {
        "pergunta": "quantos clientes Fibra Residencial em churn?",
        "nome_da_campanha": "Black Friday 2026",
        "os_id": "OS-2026-0457",
        "verba": 480000,
        "janela": "01/10 a 15/10",
        "contato_hash": "a3f5b8c2d1e4f6a7b8c9d0e1f2a3b4c5",
    }


def test_f_atelie_recusa_o_perfil_que_o_front_matter_escolheu(
    client: TestClient, app: FastAPI
) -> None:
    """O perfil vem do SKILL.md DIGITADO na tela; quem autoriza é a política publicada.

    Este é o teste que fecha "perfis usados = ['120b']" com `modelos_permitidos` pinado
    em 20b. Vale para os DOIS caminhos, por motivos diferentes:

    * dry-run e execução do harness usam o `modelo_perfil` do front-matter — entrada
      não confiável escolhendo modelo;
    * o JUDGE usa a constante `PERFIL_JUDGE` (120b), mas lê o dado do agente julgado,
      então é conferido contra o roster DESSE agente. Restringir o `engineer` a 20b tem
      de derrubar o harness inteiro — deixá-lo passar mandaria ao 120b, para julgar, o
      dado que o DPO acabou de proibir de ir ao 120b.
    """
    skill_id = _candidata_do_engineer(client)
    fake = LLMFake(resposta=_judge(NOTAS_VERDES))
    app.state.llm = fake
    entrada = {"entrada": {"pedido": "SQL de pós-pago elegível a 5G"}}

    # ---- ANTES: o default PINA o roster (`engineer: 120b`) e tudo roda
    antes = client.post(f"/api/v1/skills/{skill_id}/dry-run", json=entrada, headers=_h())
    assert antes.status_code == 200, antes.text
    assert {c["perfil"] for c in fake.chamadas} == {"120b"}, "o engineer roda no 120b (§7.2)"

    # ---- o DPO restringe o `engineer` ao 20b (custo, soberania — o motivo é dele)
    conteudo = _conservador(client)
    conteudo["modelos_permitidos"]["engineer"] = ["20b"]
    assert _publicar(client, conteudo) == 1
    chamadas = len(fake.chamadas)

    # ---- DEPOIS: as duas rotas recusam ANTES de falar com o modelo
    recusado = client.post(f"/api/v1/skills/{skill_id}/dry-run", json=entrada, headers=_h())
    assert recusado.status_code == 409, recusado.text
    assert recusado.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    detalhe = recusado.json()["detail"]
    assert "120b" in detalhe and "engineer" in detalhe, detalhe

    harness = client.post(f"/api/v1/skills/{skill_id}/harness", headers=_h())
    assert harness.status_code == 409, harness.text

    assert len(fake.chamadas) == chamadas, (
        "a política não autoriza o perfil: nem a execução nem o judge podiam ser chamados"
    )
    # nenhum `harness_run` nasceu da tentativa recusada — publicar (A1) segue sem base
    assert app.state.repositorio_os.listar_harness_runs(uuid.UUID(skill_id)) == []


def test_b_atelie_grava_invocacao_e_redige_a_saida_do_modelo(
    client: TestClient, app: FastAPI
) -> None:
    """Art. 20 + §10.4 no Ateliê: o ledger deixa de ser zero e a saída obedece à política.

    Duas coisas que só existem juntas. Gravar a invocação sem retenção seria criar, no
    caminho que não tinha ledger nenhum, uma cópia perene do que o modelo respondeu;
    aplicar retenção sem gravar seria continuar sem Art. 20 nesta rota.

    O último assert é o que impede o conserto de quebrar o portão da publicação: a
    redação alcança a SAÍDA do modelo e não o `skill_md_hash`. Se alcançasse, todo run
    passaria a parecer obsoleto sob `reter_resposta: false` e ninguém publicaria skill
    nenhuma — um controle de privacidade derrubando um controle de qualidade em
    silêncio, que é como se perde a confiança nos dois.
    """
    skill_id = _candidata_do_engineer(client)
    app.state.llm = LLMFake(resposta=_judge(NOTAS_VERDES))
    antes = len(app.state.repositorio_os.listar_invocacoes(TENANT))

    assert client.post(f"/api/v1/skills/{skill_id}/harness", headers=_h()).status_code == 201
    dry = client.post(
        f"/api/v1/skills/{skill_id}/dry-run",
        json={"entrada": {"pedido": "SQL de pós-pago elegível a 5G"}},
        headers=_h(),
    )
    assert dry.status_code == 200, dry.text

    invocacoes = app.state.repositorio_os.listar_invocacoes(TENANT)
    assert len(invocacoes) - antes == 3, "1 do harness + 1 por lado do dry-run (era 0)"
    # a linha é PROVA: a rota do Art. 20 reconstrói a invocação do Ateliê como qualquer
    # outra — sem isso o ledger seria só volume, e não direito à explicação.
    assert _reconstruir(client, invocacoes[-1].id)["output"]

    # ---- o DPO desliga a retenção da resposta
    conteudo = _conservador(client)
    conteudo["retencao"]["reter_resposta"] = False
    assert _publicar(client, conteudo) == 1

    verde = client.post(f"/api/v1/skills/{skill_id}/harness", headers=_h())
    assert verde.status_code == 201 and verde.json()["passou"] is True, verde.text

    run = app.state.repositorio_os.listar_harness_runs(uuid.UUID(skill_id))[-1]
    saidas = [caso["saida"] for caso in run.resultados["casos"]]
    assert saidas and set(saidas) == {REDIGIDO}, (
        "`harness_run.resultados` guardava a saída do modelo sem passar por retenção"
    )
    # o ledger conta a MESMA história pelo outro caminho: o `output` do dry-run é a
    # saída do modelo, e ela também nasce redigida (a redação é na ESCRITA, §10.4).
    assert (
        client.post(
            f"/api/v1/skills/{skill_id}/dry-run",
            json={"entrada": {"pedido": "SQL de pós-pago elegível a 5G"}},
            headers=_h(),
        ).status_code
        == 200
    )
    assert app.state.repositorio_os.listar_invocacoes(TENANT)[-1].output["saida"] == REDIGIDO
    # a invocação do HARNESS não tem `saida` no `output` de propósito: o que ela guarda
    # é o veredito consolidado (score/passou), que é número, não texto de titular — a
    # saída do modelo daquele caminho vive em `harness_run.resultados`, conferida acima.
    do_harness = next(
        i for i in reversed(app.state.repositorio_os.listar_invocacoes(TENANT)) if i.judge
    )
    assert set(do_harness.output) == {"harness_run_id", "score", "passou"}

    # …e o portão A1 da publicação continua de pé: o hash não é texto de titular e
    # sobrevive à redação, senão a privacidade teria derrubado a qualidade sem avisar.
    publicada = client.post(f"/api/v1/skills/{skill_id}/publicar", headers=_h("dev-lider"))
    assert publicada.status_code == 200, publicada.text


# ============================================ guarda-corpo: o SÉTIMO serviço não nasce mudo
#
# Serviços que chamam o LLM HOJE sem passar pelo portão de IA Responsável (§10.2).
#
# Esta lista é uma DÍVIDA declarada, não uma isenção: ela existe para que o teste
# abaixo possa falhar quando um serviço NOVO aparecer, em vez de simplesmente não
# existir. `portao_ia` documenta o modo de falha que ela cobre — "o sétimo serviço, o
# que ainda não existe, nasce sem nenhuma [checagem], em silêncio".
#
# `otimizacao_service` saiu desta lista na onda anterior e `atelie_service` sai NESTA,
# que era o único serviço da plataforma inteiramente fora do portão: ele escolhia o
# `modelo_perfil` no front-matter do SKILL.md (texto que o analista digita na tela do
# T16), chamava o hub três vezes sem conferir nada contra a política e gravava saída de
# modelo em `harness_run.resultados` sem passar por retenção — com zero linhas no ledger
# `invocacao`, então o Art. 20 nem alcançava o caminho. A auditoria mediu os três
# controles caindo juntos com a política mais restritiva PUBLICADA.
#
# A lista está VAZIA, e é aqui que ela é mais útil: o próximo serviço com `LLMPort.chat`
# nasce em vermelho até alguém injetar `PublicacoesIaPort`. Esvaziá-la NÃO é motivo para
# apagar o teste — um guarda-corpo só protege o futuro enquanto continua rodando.
SEM_PORTAO_HOJE: frozenset[str] = frozenset()

# A dívida do parâmetro (f) medida por CALL SITE mudou de casa nesta onda: ela agora
# vive em `tests/unit/test_F03_vigia_portao_llm.py`, que lê a ÁRVORE em vez de contar
# ocorrências. A contagem que morava aqui (`_llm.chat(` menos `portao.autorizar_modelo(`
# por arquivo) empatava com três furos reais — autorizar DEPOIS do `chat`, autorizar um
# perfil e chamar com outro, autorizar num método e chamar em outro — e o segundo deles
# era, ironicamente, a própria divergência do `criativo_service` que ela declarava.
#
# A lista de exceções é UMA só, e é a de lá: manter duas listas de isenção de portão em
# dois arquivos é como a plataforma chegou a ter duas fontes de política (achado 8).


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
