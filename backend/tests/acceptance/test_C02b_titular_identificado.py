"""Aceite C02b · o titular IDENTIFICADO também não sai do perímetro (§10.2 + F03).

O C02 fechou CPF, e-mail, telefone e cartão. A auditoria da onda 3c mediu o que sobrou,
e é o pior pedaço para uma base de telco: **titular identificado — nome, endereço, data
de nascimento, RG e CEP — saía INTACTO**. Não só para o prompt do hub (terceiro fora do
perímetro): também para a coluna `input` do ledger, para o índice `agente_evidence`
(§7.4/A11), de onde REAPARECE como precedente na resposta a outro usuário, e para o
trace do Langfuse (§10.8).

E havia o segundo buraco, mais silencioso: `CATEGORIAS_PII` era um conjunto FECHADO de
seis, então **o DPO não conseguia publicar `nome: bloquear` nem que quisesse**. A tela
da onda 3b oferecia governança sobre um vocabulário que não sabia dizer "nome".

Este arquivo prova as duas metades pelo COMPORTAMENTO:
- (I) o dado entra pela porta HTTP real e não aparece em prompt, ledger nem embedding;
- (II) a política publicada GOVERNA as categorias novas — o par A/B que o F03 exige de
  todo parâmetro (mesma entrada + política A → comportamento A; política B → B);
- (III) política já publicada com o vocabulário ANTIGO continua válida (retroativa).
"""

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from adapters.llm.fake import LLMFake
from domain.ia_responsavel import (
    CATEGORIAS_PII,
    DadoBloqueadoParaLlm,
    categorias_detectadas,
    politica_ia_seed,
    sanear_para_llm,
    validar_conteudo,
)
from domain.ia_responsavel.politica import CATEGORIAS_PII_TITULAR, CATEGORIAS_PII_V1

TENANT = "torre-movel"

# Titular identificado como ele aparece de verdade numa caixa de texto de telco.
NOME = "Maria Aparecida da Silva Santos"
MAE = "Joana Silva"
NASCIMENTO = "14/03/1987"
ENDERECO = "Rua das Flores 123"
CEP = "01310-100"
RG = "12.345.678-9"
TITULAR = (NOME, MAE, NASCIMENTO, ENDERECO, CEP, RG)

MENSAGEM = (
    f"Cliente {NOME}, mae {MAE}, nascida em {NASCIMENTO}. "
    f"{ENDERECO}, apto 42, Vila Mariana, Sao Paulo/SP, CEP {CEP}. RG {RG} orgao SSP/SP. "
    "A verba é de R$ 480.000 para 847.312 clientes na janela de 01/10 a 15/10."
)


def _h(token: str = "portal-dev") -> dict[str, str]:
    return {"X-Tenant": TENANT, "Authorization": f"Bearer {token}"}


def _resposta_consultor() -> str:
    return json.dumps({"resposta": "Anotado.", "inferencias": []}, ensure_ascii=False)


# O briefing é a porta REAL (achado 9 do UAT #5): quem digita escolhe o nome do campo,
# e a ÂNCORA do dado costuma estar na CHAVE, não no valor — `{"nome do titular": "..."}`.
CONTEUDO_COM_TITULAR: dict[str, Any] = {
    "objetivo": f"Falar com {NOME} sobre a renovação",
    "nome do titular": NOME,
    "endereco": f"{ENDERECO}, apto 42",
    "data de nascimento": NASCIMENTO,
    "rg": RG,
    "cep": CEP,
    "publico": "Pós-pago 12+ meses",
    "verba": 480_000.0,
}


# ================================================== (I) o caminho real, ponta a ponta


def test_C02b_titular_identificado_nao_chega_ao_prompt_nem_ao_ledger_nem_ao_rag(
    client: TestClient, app: FastAPI
) -> None:
    """A frase que a auditoria mediu saindo em claro entra pela porta HTTP e não sai.

    Inspeciona o que o LLMFake REALMENTE recebeu, o que o repositório REALMENTE gravou e
    o que o EmbeddingPort REALMENTE consultou — não a implementação do sanitizador (isso
    é `tests/unit/test_titular_identificado.py`).
    """
    fake = LLMFake(resposta=_resposta_consultor())
    app.state.llm = fake  # §1.3.5: nenhuma rede

    pedido = client.post(
        "/api/v1/pedidos",
        json={
            "solicitante": {"nome": "Ana Lima", "area": "Marketing"},
            "conteudo": CONTEUDO_COM_TITULAR,
        },
        headers=_h(),
    )
    assert pedido.status_code == 201, pedido.text
    resposta = client.post(
        f"/api/v1/pedidos/{pedido.json()['id']}/mensagem",
        json={"mensagem": MENSAGEM},
        headers=_h(),
    )
    assert resposta.status_code == 200, resposta.text

    assert fake.chamadas, "o consultor precisa ter chamado o LLM"
    prompt = json.dumps(fake.chamadas, ensure_ascii=False)
    invocacoes = app.state.repositorio_os.listar_invocacoes(TENANT)
    ledger = json.dumps(
        [{"input": i.input, "output": i.output} for i in invocacoes],
        ensure_ascii=False,
        default=str,
    )
    consultas = json.dumps(app.state.embedding.chamadas, ensure_ascii=False)
    assert app.state.embedding.chamadas, "o retriever precisa ter consultado o embedding"
    persistido = json.dumps(
        [p.conteudo for p in app.state.repositorio_os.listar_pedidos(TENANT)],
        ensure_ascii=False,
        default=str,
    )

    for sensivel in TITULAR:
        for onde, texto in (
            ("prompt", prompt),
            ("ledger", ledger),
            ("embedding", consultas),
            ("pedido persistido", persistido),
        ):
            assert sensivel not in texto, f"{sensivel!r} vazou para o {onde} (§10.2)"

    # e o pedido de NEGÓCIO sobreviveu: o agente ainda entende o que foi pedido
    gravado = invocacoes[0].input["mensagem"]
    assert "[NOME]" in gravado and "[ENDERECO]" in gravado and "[CEP]" in gravado
    assert "[DATA_NASCIMENTO]" in gravado and "[RG]" in gravado
    for negocio in ("R$ 480.000", "847.312", "01/10 a 15/10"):
        assert negocio in gravado, f"{negocio!r} não é PII e não podia ser mascarado"


def test_C02b_ancora_na_CHAVE_do_briefing_mascara_o_valor(client: TestClient) -> None:
    """`{"nome do titular": "Maria Aparecida da Silva Santos"}` — a forma que um
    formulário produz: âncora na chave, dado no valor. Mascarar cada string isolada
    perderia o sinal, e era assim que o titular saía inteiro do perímetro."""
    criado = client.post(
        "/api/v1/pedidos",
        json={
            "solicitante": {"nome": "Ana Lima", "area": "Marketing"},
            "conteudo": CONTEUDO_COM_TITULAR,
        },
        headers=_h(),
    )
    assert criado.status_code == 201, criado.text
    conteudo = criado.json()["conteudo"]
    assert conteudo["nome do titular"]["valor"] == "[NOME]"
    assert conteudo["data de nascimento"]["valor"] == "[DATA_NASCIMENTO]"
    assert conteudo["rg"]["valor"] == "[RG]"
    assert conteudo["cep"]["valor"] == "[CEP]"
    assert conteudo["endereco"]["valor"] == "[ENDERECO]"
    # número de negócio continua número, e o campo de negócio continua legível
    assert conteudo["verba"]["valor"] == 480_000.0
    assert conteudo["publico"]["valor"] == "Pós-pago 12+ meses"


def test_C02b_LIMITE_nome_sem_ancora_no_briefing_AINDA_sai_em_claro(
    client: TestClient, app: FastAPI
) -> None:
    """O buraco que a onda 3c NÃO fecha, medido pela mesma porta que os testes acima.

    A detecção de nome é por CONTEXTO. Num campo cujo nome não ancora nada
    (`"objetivo": "Reativar Maria Aparecida da Silva Santos"`) não há sinal algum: a
    string é indistinguível de "Reativar Torre Móvel Brasil". Um detector por lista de
    nomes próprios não resolveria — erraria o nome fora da lista e comeria palavra
    comum. Este teste existe para que o buraco esteja NO CÓDIGO, verde e visível, em vez
    de virar uma frase esquecida num relatório: quem ler o aceite vê o que ele não
    cobre. Quando o sinal existir (ver EMENDA SUGERIDA), este teste morre junto.
    """
    app.state.llm = LLMFake(resposta=_resposta_consultor())
    criado = client.post(
        "/api/v1/pedidos",
        json={
            "solicitante": {"nome": "Ana Lima", "area": "Marketing"},
            "conteudo": {"objetivo": f"Reativar {NOME}", "publico": "Pós-pago"},
        },
        headers=_h(),
    )
    assert criado.status_code == 201, criado.text
    assert criado.json()["conteudo"]["objetivo"]["valor"] == f"Reativar {NOME}"


# ============================== (II) a política GOVERNA as categorias novas (par A/B)


TEXTO_DA_CATEGORIA: dict[str, str] = {
    "nome": f"Cliente {NOME} reclamou",
    "endereco": f"Entrega em {ENDERECO}",
    "cep": f"Entrega no CEP {CEP}",
    "data_nascimento": f"Titular nascida em {NASCIMENTO}",
    "rg": f"Documento {RG} anexado",
}
MARCADOR_DA_CATEGORIA_ESPERADO: dict[str, str] = {
    "nome": "[NOME]",
    "endereco": "[ENDERECO]",
    "cep": "[CEP]",
    "data_nascimento": "[DATA_NASCIMENTO]",
    "rg": "[RG]",
}


@pytest.mark.parametrize("categoria", CATEGORIAS_PII_TITULAR)
def test_C02b_categoria_nova_e_de_fato_DETECTADA(categoria: str) -> None:
    """Antes do vocabulário vir a regra: categoria que a política nomeia mas o detector
    não encontra seria parâmetro inerte — o achado 8 do UAT #5 outra vez."""
    assert categorias_detectadas(TEXTO_DA_CATEGORIA[categoria]) == (categoria,)


@pytest.mark.parametrize("categoria", CATEGORIAS_PII_TITULAR)
def test_C02b_categoria_nova_honra_mascarar_e_bloquear(categoria: str) -> None:
    """O par A/B do parâmetro (a) para cada categoria nova: mesma entrada, política
    diferente, comportamento diferente. Sem isso a categoria seria tela, não governo."""
    texto = TEXTO_DA_CATEGORIA[categoria]

    mascara = politica_ia_seed()
    mascara["dados_llm"]["acoes"][categoria] = "mascarar"
    saneado = sanear_para_llm(texto, mascara)
    assert MARCADOR_DA_CATEGORIA_ESPERADO[categoria] in saneado.texto
    assert saneado.categorias == (categoria,)

    bloqueia = politica_ia_seed()
    bloqueia["dados_llm"]["acoes"][categoria] = "bloquear"
    with pytest.raises(DadoBloqueadoParaLlm) as erro:
        sanear_para_llm(texto, bloqueia)
    assert erro.value.categorias == (categoria,)

    # ...e as OUTRAS categorias não foram arrastadas junto pelo bloqueio de uma
    assert sanear_para_llm(TEXTO_DA_CATEGORIA["nome" if categoria != "nome" else "rg"], bloqueia)


def test_C02b_default_de_fabrica_e_conservador_e_declara_TODAS_as_categorias() -> None:
    """A v1 de fábrica mascara tudo e bloqueia nada — publicar a v1 não pode mudar o
    comportamento de nenhuma OS em voo (é a doutrina do `politica.py`). O que ela ganha
    na 3c é DECLARAR as categorias novas, para o formulário do DPO nascer com elas."""
    acoes = politica_ia_seed()["dados_llm"]["acoes"]
    assert set(acoes) == set(CATEGORIAS_PII)
    assert set(acoes.values()) == {"mascarar"}
    assert validar_conteudo(politica_ia_seed()) == []


def test_C02b_politica_silenciosa_sobre_categoria_nova_cai_no_piso_mascarar() -> None:
    """Omissão nunca vira permissão: sem a categoria declarada, o piso do C02 vale.

    É o que torna a compatibilidade retroativa SEGURA — a política antiga não perde
    proteção, perde só o direito de apertar."""
    conteudo = politica_ia_seed()
    del conteudo["dados_llm"]["acoes"]["nome"]
    assert "[NOME]" in sanear_para_llm(TEXTO_DA_CATEGORIA["nome"], conteudo).texto


# ================================ (III) compatibilidade retroativa do conjunto FECHADO


def test_C02b_politica_publicada_com_o_vocabulario_ANTIGO_continua_valida() -> None:
    """Somar categoria a um conjunto FECHADO que exige declaração invalidaria, de um
    deploy para o outro, toda política já publicada.

    O efeito seria silencioso e ruim: a tela do DPO abriria o conteúdo vigente, o
    formulário nasceria inválido, e enquanto isso a linha antiga continuaria governando
    (validação é ato de PUBLICAÇÃO, não de leitura). Por isso a obrigatoriedade ficou
    congelada no conjunto V1 e as novas entraram OPCIONAIS.
    """
    v1_como_estava_publicada = politica_ia_seed()
    v1_como_estava_publicada["dados_llm"]["acoes"] = dict.fromkeys(CATEGORIAS_PII_V1, "mascarar")
    assert validar_conteudo(v1_como_estava_publicada) == []


def test_C02b_omitir_categoria_ANTIGA_continua_sendo_erro() -> None:
    """A compatibilidade retroativa não pode virar frouxidão geral: o que já era
    obrigatório continua obrigatório."""
    conteudo = politica_ia_seed()
    del conteudo["dados_llm"]["acoes"]["cpf"]
    assert any("cpf" in e for e in validar_conteudo(conteudo))


def test_C02b_categoria_inexistente_continua_recusada() -> None:
    """O conjunto cresceu, não abriu: `biometria` não tem detector, logo não é
    publicável (regra sem detector é exatamente o teatro que o F03 proíbe)."""
    conteudo = politica_ia_seed()
    conteudo["dados_llm"]["acoes"]["biometria"] = "bloquear"
    assert any("biometria" in e and "desconhecida" in e for e in validar_conteudo(conteudo))


def test_C02b_toda_categoria_do_vocabulario_tem_detector() -> None:
    """Trava de deriva: categoria publicável sem marcador correspondente quebraria
    `categorias_detectadas` — e uma ação publicada sobre ela nunca dispararia."""
    from domain.ia_responsavel.dados import MARCADOR_DA_CATEGORIA

    assert set(CATEGORIAS_PII) == set(MARCADOR_DA_CATEGORIA)
