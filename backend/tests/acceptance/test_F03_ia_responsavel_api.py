"""F03 · A política de IA Responsável passa a EXISTIR no banco e a ter DONO (§10.2).

A onda 3 entregou quatro parâmetros com enforcement provado por inversão — e nada fora
do próprio teste importava o módulo. Eram quatro funções puras que ninguém chamava: a
um commit de virarem o achado 8 do UAT #5 (tela publica, portão ignora), que é o achado
que aquela onda existiu para curar.

Este arquivo é o aceite da primeira metade do conserto: a política tem tabela, rota,
autor e data, e o DEFAULT conservador governa desde o primeiro boot **sem linha nenhuma
no banco** — com a origem dita em voz alta, nunca por fallback silencioso (a lição do
achado crítico da onda 3).

Cada teste que cobra mudança passa pelo estado ANTES da publicação. Sem esse "antes", o
teste não distingue política que governa de coincidência de valores — foi exatamente
assim que o achado 8 sobreviveu a uma suíte verde.
"""

import copy
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import DEV_TOKENS, Usuario
from app.errors import PROBLEM_CONTENT_TYPE
from application.ports.publicacoes import ORIGEM_PUBLICADA, ORIGEM_SEED
from tests.conftest import TENANT_ALHEIO

TENANT = "torre-movel"
MOTIVO = "Aperto pedido pelo comitê de privacidade após revisão trimestral."


def _h(token: str = "dev-dpo", tenant: str = TENANT) -> dict[str, str]:
    return {"X-Tenant": tenant, "Authorization": f"Bearer {token}"}


def _vigente(client: TestClient, token: str = "dev-dpo", tenant: str = TENANT) -> dict[str, Any]:
    resposta = client.get("/api/v1/ia-responsavel/politica", headers=_h(token, tenant))
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _conservador(
    client: TestClient, token: str = "dev-dpo", tenant: str = TENANT
) -> dict[str, Any]:
    """O default de fábrica servido pela própria API — nunca redigitado no teste.

    Copiar o conteúdo esperado para dentro do teste faria o teste passar a validar a
    memória de quem o escreveu, não o default que a aplicação usa.
    """
    return copy.deepcopy(_vigente(client, token, tenant)["default_conservador"])


@pytest.fixture()
def dpo_outro_tenant(monkeypatch: pytest.MonkeyPatch) -> str:
    """DPO REAL de `outra-torre` (mesmo padrão do `tokens_outro_tenant` do conftest).

    Forjar `X-Tenant` não serve: o header é conferido contra o portador desde o achado
    5 do UAT #5. Provar isolamento exige uma segunda identidade de verdade.
    """
    token = "dev-dpo-outra-torre"
    monkeypatch.setitem(
        DEV_TOKENS,
        token,
        Usuario(
            id=uuid.uuid5(uuid.NAMESPACE_URL, "jornada/dev/dpo/outra-torre"),
            tenant_id=TENANT_ALHEIO,
            nome="Dev DPO (outra torre)",
            email="dpo@outra-torre.local",
            papeis=("dpo",),
        ),
    )
    return token


# --------------------------------------------------------------------------- default
def test_sem_publicacao_o_default_conservador_governa(client: TestClient) -> None:
    """Primeiro boot, banco vazio: existe governo, e ele é o conservador do domínio.

    O ponto NÃO é o conteúdo — é que a resposta diz de onde ele vem. `origem=seed`
    responde à pergunta que uma auditoria faz: *alguém decidiu isto, ou é o que veio de
    fábrica?* Uma resposta sem origem seria indistinguível de "o DPO publicou a v1".
    """
    lista = client.get("/api/v1/ia-responsavel/politicas", headers=_h())
    assert lista.status_code == 200, lista.text
    assert lista.json()["politicas"] == []  # nada foi semeado: seed de política de IA não existe

    vigente = _vigente(client)
    assert vigente["origem"] == ORIGEM_SEED
    assert vigente["nunca_publicada"] is True
    assert vigente["versao"] == 0  # versão RESERVADA: publicação começa em 1, nunca colide
    assert vigente["publicado_por_nome"] is None  # ninguém assinou — e a tela diz isso

    conteudo = vigente["conteudo"]
    # Conservador (§10.2): mascara tudo (piso do C02), não bloqueia nada, e a IA PROPÕE.
    assert set(conteudo["dados_llm"]["acoes"].values()) == {"mascarar"}
    assert conteudo["decisao_automatizada"]["pode_aplicar_sozinho"] == []
    assert conteudo["retencao"]["reter_prompt"] is True  # Art. 20 exige reconstruir


def test_default_e_o_mesmo_objeto_que_a_tela_oferece_no_formulario(client: TestClient) -> None:
    """`default_conservador` acompanha a resposta MESMO depois de publicar — é a régua
    contra a qual o DPO lê o que está valendo, e o preenchimento inicial do formulário."""
    conteudo = _conservador(client)
    conteudo["decisao_automatizada"]["pode_aplicar_sozinho"] = ["otimizacao.propor"]
    assert (
        client.post(
            "/api/v1/ia-responsavel/politicas",
            json={"conteudo": conteudo, "motivo": MOTIVO},
            headers=_h(),
        ).status_code
        == 201
    )
    depois = _vigente(client)
    assert depois["origem"] == ORIGEM_PUBLICADA
    assert depois["default_conservador"]["decisao_automatizada"]["pode_aplicar_sozinho"] == []


# ------------------------------------------------------------------------- publicação
def test_publicar_muda_o_vigente(client: TestClient) -> None:
    """O aceite central da frente: publicar MUDA o que governa — com autor e data.

    Passa pelo ANTES de propósito: sem ele, o teste não distingue "a política passou a
    valer" de "o valor já era esse".
    """
    antes = _vigente(client)
    assert antes["conteudo"]["dados_llm"]["acoes"]["cartao"] == "mascarar"
    assert antes["origem"] == ORIGEM_SEED

    conteudo = _conservador(client)
    # O primeiro aperto recomendado ao DPO: cartão em briefing de marketing nunca é
    # parâmetro legítimo — é sempre erro de quem pediu.
    conteudo["dados_llm"]["acoes"]["cartao"] = "bloquear"
    resposta = client.post(
        "/api/v1/ia-responsavel/politicas",
        json={"conteudo": conteudo, "motivo": MOTIVO},
        headers=_h(),
    )
    assert resposta.status_code == 201, resposta.text

    depois = _vigente(client)
    assert depois["conteudo"]["dados_llm"]["acoes"]["cartao"] == "bloquear"
    assert depois["origem"] == ORIGEM_PUBLICADA
    assert depois["versao"] == 1
    assert depois["nunca_publicada"] is False
    assert depois["publicado_por_nome"] == "Dev Dpo"  # a linha tem DONO, não só o outbox
    assert depois["motivo"] == MOTIVO
    assert depois["publicada_em"] is not None

    # O efeito é dito em português, no presente do indicativo — o DPO não lê código.
    efeito_cartao = next(
        item
        for bloco in depois["efeitos"]
        if bloco["parametro"] == "dados_llm"
        for item in bloco["itens"]
        if item["chave"] == "cartao"
    )
    assert "INTERROMPE" in efeito_cartao["efeito"]

    historico = client.get("/api/v1/ia-responsavel/politicas", headers=_h()).json()
    assert [(p["versao"], p["estado"]) for p in historico["politicas"]] == [(1, "publicada")]
    assert historico["politicas"][0]["autor_nome"] == "Dev Dpo"


def test_versao_e_sequencial_e_a_ultima_publicada_governa(client: TestClient) -> None:
    for esperado, acao in ((1, "otimizacao.propor"), (2, "insight.responder")):
        conteudo = _conservador(client)
        conteudo["decisao_automatizada"]["pode_aplicar_sozinho"] = [acao]
        resposta = client.post(
            "/api/v1/ia-responsavel/politicas",
            json={"conteudo": conteudo, "motivo": MOTIVO},
            headers=_h(),
        )
        assert resposta.status_code == 201, resposta.text
        assert resposta.json()["versao"] == esperado

    vigente = _vigente(client)
    assert vigente["versao"] == 2
    assert vigente["conteudo"]["decisao_automatizada"]["pode_aplicar_sozinho"] == [
        "insight.responder"
    ]
    # Histórico PRESERVADO: versão nova não apaga a anterior (auditoria precisa das duas).
    historico = client.get("/api/v1/ia-responsavel/politicas", headers=_h()).json()
    assert [p["versao"] for p in historico["politicas"]] == [1, 2]


def test_publicar_deixa_rastro_na_trilha_de_auditoria(client: TestClient) -> None:
    """Autoria na LINHA **e** evento no outbox (§2.3): a pergunta "quem autorizou a IA a
    decidir sozinha, e quando?" tem de ser respondível pelos dois caminhos."""
    conteudo = _conservador(client)
    conteudo["decisao_automatizada"]["pode_aplicar_sozinho"] = ["jornada.ajustar"]
    client.post(
        "/api/v1/ia-responsavel/politicas",
        json={"conteudo": conteudo, "motivo": MOTIVO},
        headers=_h(),
    )
    trilha = client.get("/api/v1/auditoria?tipo=politica_ia.publicada", headers=_h("dev-analista"))
    assert trilha.status_code == 200, trilha.text
    eventos = trilha.json()["eventos"]
    assert len(eventos) == 1
    assert eventos[0]["payload"]["versao"] == 1
    assert eventos[0]["payload"]["motivo"] == MOTIVO
    # O que ficou automatizado SEM humano vai no corpo do evento: quem lê a trilha não
    # deveria ter de baixar dois JSONs e comparar à mão.
    assert eventos[0]["payload"]["apertos"]["automatizadas_sem_humano"] == ["jornada.ajustar"]


# ------------------------------------------------------------------- conjunto FECHADO
@pytest.mark.parametrize(
    ("mutacao", "trecho_esperado"),
    [
        pytest.param(
            lambda c: c.update({"teto_custo": {"por_dia": 500.0}}),
            "teto_custo",
            id="campo-de-topo-desconhecido",
        ),
        pytest.param(
            lambda c: c.update({"teto_tokens": 10_000}),  # J02: o campo existe, a FORMA não
            "teto_tokens",
            id="teto-tokens-sem-o-sub-bloco",
        ),
        pytest.param(
            lambda c: c.update({"teto_tokens": {"tokens_por_dia": -5}}),
            "inteiro positivo",
            id="teto-tokens-negativo",
        ),
        pytest.param(
            lambda c: c["retencao"].update({"dias_ledger": 30}),
            "dias_ledger",
            id="retencao-dias_ledger-tem-dono-no-M12",
        ),
        pytest.param(
            lambda c: c["dados_llm"]["acoes"].update({"cpf": "permitir"}),
            "permitir",
            id="acao-permitir-nao-existe",
        ),
        pytest.param(
            lambda c: c["decisao_automatizada"]["pode_aplicar_sozinho"].append("jornada.ajusta"),
            "jornada.ajusta",
            id="typo-na-allowlist-do-art-20",
        ),
        pytest.param(
            lambda c: c["modelos_permitidos"].update({"enginer": ["120b"]}),
            "enginer",
            id="typo-no-nome-do-agente",
        ),
    ],
)
def test_campo_fora_do_conjunto_fechado_e_422_apontando_o_campo(
    client: TestClient, mutacao: Any, trecho_esperado: str
) -> None:
    """Publicar parâmetro que não governa é REJEITADO, e o erro NOMEIA o campo.

    Os dois typos (`jornada.ajusta`, `enginer`) são o caso que mais importa: aceitos em
    silêncio, o DPO acreditaria ter autorizado/restringido algo que segue como estava —
    falha silenciosa na direção errada da auditoria, o pior modo de errar num controle
    de governança. `teto_tokens` ENTROU na J02 (com enforcement no portão — os aceites
    `test_d_*` do enforcement provam), então o exemplo de campo desconhecido virou
    `teto_custo`, que segue sem consumidor; a forma torta do bloco novo também é 422.
    """
    conteudo = _conservador(client)
    mutacao(conteudo)
    resposta = client.post(
        "/api/v1/ia-responsavel/politicas",
        json={"conteudo": conteudo, "motivo": MOTIVO},
        headers=_h(),
    )
    assert resposta.status_code == 422, resposta.text
    assert resposta.headers["content-type"].startswith(PROBLEM_CONTENT_TYPE)
    erros = resposta.json()["erros"]
    assert any(trecho_esperado in erro for erro in erros), erros

    # E o vigente NÃO mudou: publicação recusada não deixa versão pela metade.
    vigente = _vigente(client)
    assert vigente["origem"] == ORIGEM_SEED
    assert client.get("/api/v1/ia-responsavel/politicas", headers=_h()).json()["politicas"] == []


def test_motivo_e_obrigatorio(client: TestClient) -> None:
    """Política de privacidade que muda sem justificativa escrita é o que a auditoria
    pede para ver e não encontra."""
    resposta = client.post(
        "/api/v1/ia-responsavel/politicas",
        json={"conteudo": _conservador(client), "motivo": "  "},
        headers=_h(),
    )
    assert resposta.status_code == 422, resposta.text


# --------------------------------------------------------------------------- RBAC
@pytest.mark.parametrize("token", ["dev-analista", "dev-lider", "dev-aprovador"])
def test_publicar_exige_dpo(client: TestClient, token: str) -> None:
    """`lider` publica a política do M12 (conteúdo da campanha) e NÃO esta.

    Um líder de campanha autorizando a IA a aplicar mudanças sozinha, sem o DPO, é o
    desenho que a LGPD não aceita — por isso o papel aqui é o mesmo do purge (§10.4) e
    da reconstrução do Art. 20.
    """
    conteudo = _conservador(client)
    conteudo["dados_llm"]["acoes"]["cpf"] = "bloquear"
    resposta = client.post(
        "/api/v1/ia-responsavel/politicas",
        json={"conteudo": conteudo, "motivo": MOTIVO},
        headers=_h(token),
    )
    assert resposta.status_code == 403, resposta.text
    assert _vigente(client)["origem"] == ORIGEM_SEED  # e nada foi publicado


@pytest.mark.parametrize("token", ["dev-dpo", "dev-admin"])
def test_dpo_e_admin_publicam(client: TestClient, token: str) -> None:
    conteudo = _conservador(client)
    conteudo["dados_llm"]["acoes"]["cpf"] = "bloquear"
    resposta = client.post(
        "/api/v1/ia-responsavel/politicas",
        json={"conteudo": conteudo, "motivo": MOTIVO},
        headers=_h(token),
    )
    assert resposta.status_code == 201, resposta.text


def test_leitura_e_de_qualquer_autenticado_mas_nao_de_anonimo(client: TestClient) -> None:
    """Saber sob que política de IA a plataforma opera não é privilégio de ninguém —
    mas continua sendo informação do tenant, não do mundo."""
    assert (
        client.get("/api/v1/ia-responsavel/politica", headers=_h("dev-analista")).status_code == 200
    )
    anonimo = client.get("/api/v1/ia-responsavel/politica", headers={"X-Tenant": TENANT})
    assert anonimo.status_code in (401, 403)


# ------------------------------------------------------------------- isolamento §3
def test_isolamento_por_tenant(client: TestClient, dpo_outro_tenant: str) -> None:
    """Política de privacidade de um cliente NUNCA governa outro.

    O tenant sem publicação não herda o aperto do vizinho e também não fica sem
    governo: cai no conservador, com `origem=seed` dizendo exatamente isso.
    """
    conteudo = _conservador(client, dpo_outro_tenant, TENANT_ALHEIO)
    conteudo["dados_llm"]["acoes"]["cpf"] = "bloquear"
    conteudo["decisao_automatizada"]["pode_aplicar_sozinho"] = ["insight.responder"]
    publicada = client.post(
        "/api/v1/ia-responsavel/politicas",
        json={"conteudo": conteudo, "motivo": MOTIVO},
        headers=_h(dpo_outro_tenant, TENANT_ALHEIO),
    )
    assert publicada.status_code == 201, publicada.text

    alheio = _vigente(client, dpo_outro_tenant, TENANT_ALHEIO)
    assert alheio["conteudo"]["dados_llm"]["acoes"]["cpf"] == "bloquear"
    assert alheio["origem"] == ORIGEM_PUBLICADA

    nosso = _vigente(client)
    assert nosso["origem"] == ORIGEM_SEED
    assert nosso["conteudo"]["dados_llm"]["acoes"]["cpf"] == "mascarar"
    assert nosso["conteudo"]["decisao_automatizada"]["pode_aplicar_sozinho"] == []
    assert client.get("/api/v1/ia-responsavel/politicas", headers=_h()).json()["politicas"] == []
