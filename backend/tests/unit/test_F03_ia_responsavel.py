"""Emenda F03 · IA Responsável — ENFORCEMENT dos parâmetros (achado 8 do UAT #5).

Todo teste aqui tem a MESMA forma, que é a única que prova governança:

    mesma entrada + política A  →  comportamento A
    mesma entrada + política B  →  comportamento B

Um teste que só verifica que `validar_conteudo` aceita um dicionário não prova nada
sobre governo — foi exatamente o que existia no M12 enquanto os portões liam a
constante. Por isso cada parâmetro do módulo tem, obrigatoriamente, um par A/B abaixo;
parâmetro sem par não entrou no conjunto FECHADO (`teto_tokens` e `rotulo_ia` ficaram
de fora justamente por não terem como ter um).

Puro: nenhum app, nenhum banco, nenhum LLM (§1.3.5) — as regras são código.
"""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from domain.ia_responsavel import (
    DadoBloqueadoParaLlm,
    DecisaoAutomatizadaNegada,
    ModeloNaoPermitido,
    aplicar_retencao,
    categorias_detectadas,
    exigir_perfil_autorizado,
    exigir_revisao_humana,
    expira_em,
    modo_de_decisao,
    perfis_permitidos,
    politica_ia_seed,
    sanear_para_llm,
    validar_conteudo,
)
from domain.ia_responsavel.modelos import PoliticaIa
from domain.ia_responsavel.retencao import (
    CHAVES_TECNICAS,
    REDIGIDO,
    aplicar_retencao_evidencias,
)

RAIZ = Path(__file__).resolve().parents[3]

# CPF com dígitos verificadores VÁLIDOS: o mascarador desempata CPF × celular por DV
# (§10.2), então um número inventado testaria outro caminho que não o pretendido.
CPF_VALIDO = "529.982.247-25"
TEXTO_COM_CPF = f"O cliente {CPF_VALIDO} reclamou da fatura"
TEXTO_COM_EMAIL = "Falar com joao.silva@exemplo.com.br sobre a oferta"


def _politica(**ajustes: object) -> dict:
    """Seed v1 com os ajustes pedidos — o resto fica no default conservador."""
    conteudo = politica_ia_seed()
    for campo, valor in ajustes.items():
        conteudo[campo] = valor
    return conteudo


def _com_acao(categoria: str, acao: str) -> dict:
    """Política igual à v1, mudando UMA categoria de PII — o A/B do parâmetro (a)."""
    conteudo = politica_ia_seed()
    conteudo["dados_llm"]["acoes"][categoria] = acao
    return conteudo


# ===================================================================== (a) dados_llm


def test_a_mesma_entrada_muda_de_destino_quando_a_politica_muda() -> None:
    """O par A/B do parâmetro (a): mascarar deixa seguir, bloquear IMPEDE a chamada.

    Este é o teste que separa governança de teatro. Se ele passar com as duas
    políticas produzindo o mesmo resultado, o parâmetro não governa nada.
    """
    # A — política v1 (cpf: mascarar): o texto segue, com o CPF trocado por marcador.
    saneado = sanear_para_llm(TEXTO_COM_CPF, _com_acao("cpf", "mascarar"))
    assert CPF_VALIDO not in saneado.texto
    assert "[CPF]" in saneado.texto
    assert saneado.categorias == ("cpf",)

    # B — mesma frase, política com cpf: bloquear: a chamada NÃO acontece.
    with pytest.raises(DadoBloqueadoParaLlm) as erro:
        sanear_para_llm(TEXTO_COM_CPF, _com_acao("cpf", "bloquear"))
    assert erro.value.categorias == ("cpf",)
    # A mensagem é lida por quem digitou o texto: precisa dizer que o dado NÃO saiu.
    assert "não foi feita" in erro.value.motivo


def test_a_bloqueio_de_uma_categoria_nao_bloqueia_texto_de_outra() -> None:
    """Bloquear cartão não pode transformar todo e-mail em erro (falso positivo custa
    o produto: o consultor pararia de responder a briefing legítimo)."""
    conteudo = _com_acao("cartao", "bloquear")
    saneado = sanear_para_llm(TEXTO_COM_EMAIL, conteudo)
    assert "[EMAIL]" in saneado.texto
    assert saneado.categorias == ("email",)


def test_a_bloqueio_vence_quando_ha_categoria_mascarada_junto() -> None:
    """Texto com e-mail (mascarar) + CPF (bloquear): bloqueia. O que sairia do
    perímetro é o texto INTEIRO, então basta uma categoria bloqueada."""
    conteudo = _com_acao("cpf", "bloquear")
    with pytest.raises(DadoBloqueadoParaLlm) as erro:
        sanear_para_llm(f"{TEXTO_COM_EMAIL} — CPF {CPF_VALIDO}", conteudo)
    assert erro.value.categorias == ("cpf",)


def test_a_marcador_digitado_pelo_usuario_nao_forja_deteccao() -> None:
    """Detecção é por DELTA de marcadores, não por presença.

    Sem isso, digitar "[CPF]" no briefing dispararia bloqueio (negação de serviço
    trivial) e, pior, o caminho inverso viraria oráculo: dava para descobrir a política
    do tenant testando strings.
    """
    assert categorias_detectadas("o campo [CPF] do formulário está vazio") == ()
    saneado = sanear_para_llm("o campo [CPF] do formulário", _com_acao("cpf", "bloquear"))
    assert saneado.texto == "o campo [CPF] do formulário"


def test_a_politica_corrompida_cai_no_piso_do_c02_em_vez_de_afrouxar() -> None:
    """Conteúdo sem `dados_llm` (linha antiga, JSON truncado) mascara mesmo assim.

    A direção do fallback é a decisão de segurança: falhar mascarando custa um
    marcador a mais; falhar liberando custa PII no prompt do modelo.
    """
    saneado = sanear_para_llm(TEXTO_COM_CPF, {})
    assert CPF_VALIDO not in saneado.texto
    assert "[CPF]" in saneado.texto


# ====================================================================== (b) retencao


def test_b_reter_prompt_governa_o_que_e_gravado_no_ledger() -> None:
    """Par A/B do parâmetro (b): o MESMO payload é gravado inteiro ou redigido."""
    payload = {"os_id": UUID_CORRELACAO, "instrucoes": "aumentar frequência no fim de semana"}

    # A — v1 (reter_prompt: true): a prova do Art. 20 continua no ledger.
    conteudo_a = politica_ia_seed()
    assert (
        aplicar_retencao(payload, conteudo_a, tipo="input")["instrucoes"] == payload["instrucoes"]
    )

    # B — tenant que abre mão da reconstrução: o texto não é gravado.
    conteudo_b = politica_ia_seed()
    conteudo_b["retencao"]["reter_prompt"] = False
    gravado = aplicar_retencao(payload, conteudo_b, tipo="input")
    assert gravado["instrucoes"] == REDIGIDO
    # A CHAVE sobrevive: a auditoria precisa ver que houve conteúdo suprimido, e não
    # um campo que aparenta nunca ter existido.
    assert "instrucoes" in gravado
    assert gravado["os_id"] == UUID_CORRELACAO  # correlação com FORMA de id não é tocada


def test_b_retencao_de_input_e_output_sao_independentes() -> None:
    """Desligar prompt não pode arrastar a resposta junto (e vice-versa) — são duas
    decisões legais distintas: uma é dado do titular, outra é decisão sobre ele."""
    conteudo = politica_ia_seed()
    conteudo["retencao"]["reter_prompt"] = False
    entrada = aplicar_retencao({"instrucoes": "x"}, conteudo, tipo="input")
    saida = aplicar_retencao({"resposta": "y"}, conteudo, tipo="output")
    assert entrada["instrucoes"] == REDIGIDO
    assert saida["resposta"] == "y"


def test_b_prazo_do_trace_muda_com_o_parametro() -> None:
    """`dias_trace` governa a janela do trace: mesma linha, política nova, data nova."""
    criada = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    conteudo = politica_ia_seed()
    assert expira_em(criada, conteudo).date() == datetime(2026, 9, 5, tzinfo=UTC).date()

    conteudo["retencao"]["dias_trace"] = 7
    assert expira_em(criada, conteudo).date() == datetime(2026, 8, 13, tzinfo=UTC).date()


def test_b_dias_ledger_e_recusado_porque_o_prazo_do_ledger_e_do_m12() -> None:
    """Achado do auditor: `dias_ledger` era um SEGUNDO relógio de retenção, inerte.

    Quem apaga o ledger é o `purge_service` (§10.4), e ele lê `retencao_dias` da
    política do M12 pela `PublicacoesPort` — `tests/acceptance/test_D01_purge.py` prova
    que publicar `retencao_dias: 30` muda o que some. Nada lia `dias_ledger`: o DPO
    publicaria 30, a tela confirmaria, e o purge seguiria em 180. É o achado 8 do UAT #5
    reencenado dentro do módulo criado para acabar com ele.

    Não basta remover do seed — tem de ser REJEITADO, senão volta pela API calado.
    """
    conteudo = politica_ia_seed()
    conteudo["retencao"]["dias_ledger"] = 30
    erros = validar_conteudo(conteudo)
    assert any("dias_ledger" in e and "retencao_dias" in e for e in erros)
    # E o seed não pode reintroduzir o campo pela porta dos fundos.
    assert "dias_ledger" not in politica_ia_seed()["retencao"]


def test_b_bloco_retencao_e_fechado_como_o_conteudo() -> None:
    """Sub-bloco fechado: parâmetro inerte não entra nem um nível abaixo."""
    conteudo = politica_ia_seed()
    conteudo["retencao"]["dias_embedding"] = 90
    assert any("dias_embedding" in e and "FECHADO" in e for e in validar_conteudo(conteudo))


def _sem_reter() -> dict:
    """Política do tenant que desligou a retenção dos dois lados."""
    conteudo = politica_ia_seed()
    conteudo["retencao"]["reter_prompt"] = False
    conteudo["retencao"]["reter_resposta"] = False
    return conteudo


# Correlação REAL do §4.1: os serviços gravam `str(pedido.id)`, `str(os_.id)`,
# `str(run.id)`, `str(skill.id)` — sempre UUID. Os testes usavam "b1"/"abc"/"e1", e essa
# licença poética era carregada: ela fazia passar uma preservação por NOME de chave que
# nenhum payload de produção precisa. Um id de mentira num teste de privacidade prova o
# que o teste inventou, não o que o serviço grava.
UUID_CORRELACAO = "3f1a0c2e-0000-4000-8000-000000000001"
UUID_OUTRO = "7c2b91f4-0000-4000-8000-0000000000a2"

# PII BRASILEIRA que o mascarador de texto não pega por FORMA e que o ledger, mesmo
# assim, não pode guardar quando o DPO manda não guardar: nome composto com preposição,
# caixa alta, logradouro sem "Rua", CEP sem hífen, data por extenso, RG de outro estado.
# Nenhuma delas tem âncora sintática — é justamente por isso que a retenção precisa ser
# deny-by-default em vez de depender de detector.
PII_BR = {
    "nome_composto": "Maria da Conceicao dos Santos",
    "nome_caixa_alta": "JOAO PEDRO DA SILVA JUNIOR",
    "endereco_sem_rua": "Av. Paulista 1000, ap 52",
    "cep_sem_hifen": "01310100",
    "nascimento_por_extenso": "14 de marco de 1987",
    "rg_de_minas": "MG-14.567.890",
}


# Payloads REAIS gravados hoje em `invocacao` (§4.1) — copiados dos `_registrar_invocacao`
# de cada serviço. O teste vale porque usa as chaves que os serviços de fato escrevem: uma
# redação testada só contra payload inventado prova que a função redige o que ela mesma
# escolheu redigir, que é precisamente o vício do achado 8.
#
# A matriz cobre os SEIS serviços que gravam ledger (nenhum pode ficar de fora: o furo
# desta rodada estava em dois deles) e mais quatro FORMAS adversariais que a auditoria
# usou para medir — aninhamento, lista de dicionários, chave nova, JSON dentro de string
# e chave preservada com estrutura embaixo.
PAYLOADS_REAIS_DO_LEDGER: tuple[tuple[str, str, dict], ...] = (
    # ajuda_service.py:92 — a rota mais curta que chega ao LLM
    (
        "ajuda.input",
        "input",
        {
            "pagina": "cockpit",
            "pergunta": f"Meu CPF é {CPF_VALIDO}, como preencho?",
            "contexto_chars": 120,
            "historico_len": 2,
        },
    ),
    ("ajuda.output", "output", {"resposta": f"Vi o CPF {CPF_VALIDO} no seu texto."}),
    # audiencia_service.py:402 — NENHUMA chave de texto tem nome "de prompt"
    (
        "audiencia.input",
        "input",
        {"os_id": UUID_CORRELACAO, "instrucoes": f"segmentar quem parece o titular {CPF_VALIDO}"},
    ),
    (
        "audiencia.output",
        "output",
        {
            "sql": f"SELECT * FROM clientes WHERE cpf = '{CPF_VALIDO}'",
            "explicacao": [{"clausula": "WHERE", "explicacao": f"filtrei por {CPF_VALIDO}"}],
            # FURO 2 desta rodada: `evidencias` era CHAVE TÉCNICA e atravessava inteira,
            # com o teor vindo do corpus RAG (`agents/engineer.py` só faz `str().strip()`).
            "evidencias": [f"dicionario_dados: titular {CPF_VALIDO} — §4.1"],
        },
    ),
    # criativo_service.py:115 — `kv_master` é dicionário ANINHADO derivado do briefing
    (
        "criativo.input",
        "input",
        {
            "kv_master": {"headline": f"Fale com {CPF_VALIDO}", "cta": "ligue já"},
            "instrucoes": "tom informal",
        },
    ),
    # criativo_service.py:305 — o warn de compliance grava o TEXTO analisado de volta
    ("criativo.warn.output", "output", {"avisos": [f"o criativo cita {CPF_VALIDO}"]}),
    # consultor_service.py:465 — a conversa do portal, já mascarada na fronteira (C02),
    # mas a retenção é a segunda barreira e não pode depender da primeira
    (
        "consultor.input",
        "input",
        {"pedido_id": UUID_CORRELACAO, "mensagem": f"o solicitante é o {CPF_VALIDO}"},
    ),
    (
        "consultor.output",
        "output",
        {
            "resposta": "ok",
            # `inferencias` é LISTA de dicionários, e cada um carrega `evidencias` —
            # o FURO 2 uma camada abaixo, que é onde ele foi medido.
            "inferencias": [
                {
                    "campo": "publico",
                    "valor": "clientes pós-pago",
                    "evidencias": [f"Solicitante {CPF_VALIDO} pediu 500k"],
                }
            ],
            "compliance_bypass_tentado": ["ignore_compliance"],
        },
    ),
    # insight_service.py:209 — `parametros` é dicionário vindo do modelo
    (
        "insight.output",
        "output",
        {
            "consulta": "vw_metricas_jornada",
            "parametros": {"filtro": f"cpf = {CPF_VALIDO}"},
            "resposta": "5 envios",
            "recusa": None,
        },
    ),
    # jornada_service.py:376 — `valido` é veredito, `resumo` é texto do modelo
    ("jornada.output", "output", {"resumo": f"ajuste para {CPF_VALIDO}", "valido": True}),
    # otimizacao_service.py:254 — `propostas` é LISTA de uuids; `sinais`, dicionário
    (
        "otimizacao.input",
        "input",
        {"jornada_base_id": UUID_CORRELACAO, "sinais": {"nota": f"titular {CPF_VALIDO} reclamou"}},
    ),
    (
        "otimizacao.output",
        "output",
        {
            "propostas": ["3f1a0c2e-0000-4000-8000-000000000001"],
            "descartadas": 2,
            "resumo": f"proposta para {CPF_VALIDO}",
        },
    ),
    # FURO 3 (latente até aqui): chave PRESERVADA com estrutura embaixo. `_preservar`
    # devolvia o valor inteiro sem olhar, então bastava um dicionário sob `*_id` ou sob
    # chave técnica para o texto atravessar em qualquer profundidade.
    (
        "adversarial.preservada_com_estrutura",
        "output",
        {
            "os_id": {"nota": f"titular {CPF_VALIDO}"},
            "pedido_id": [f"anotação sobre {CPF_VALIDO}"],
            "consulta": {"where": f"cpf = {CPF_VALIDO}"},
            "textos": [{"trecho": CPF_VALIDO}],
        },
    ),
    # JSON serializado DENTRO de uma string: a redação é por valor, não por parse —
    # a string inteira vira marcador, então o conteúdo não escapa por dentro dela.
    (
        "adversarial.json_em_string",
        "input",
        {"payload_bruto": f'{{"titular": "{CPF_VALIDO}", "verba": 500000}}'},
    ),
)


@pytest.mark.parametrize(("nome", "tipo", "payload"), PAYLOADS_REAIS_DO_LEDGER)
def test_b_reter_false_nao_deixa_pii_sobrar_em_payload_real(
    nome: str, tipo: str, payload: dict
) -> None:
    """Achado do auditor: a redação tinha a POLARIDADE errada e vazava.

    A versão anterior listava chaves de texto (`instrucoes`, `resposta`...) e retinha
    todo o resto — medido contra estes payloads reais, o CPF sobrevivia: o `output` do
    audiencia não tinha uma chave em comum com a lista, o `kv_master` do criativo era
    dicionário e as `inferencias` do consultor eram lista. Desligar a retenção suprimia
    o campo VISÍVEL e deixava o dado ao lado — a pior falha possível para um controle de
    privacidade, porque a auditoria acredita na supressão.

    A rodada seguinte mediu o mesmo modo de falha sobrevivendo na LISTA DE EXCEÇÕES
    (`evidencias`, e qualquer chave técnica ou `*_id` com estrutura embaixo). Daí os
    dois últimos casos da matriz: eles são a forma, não um payload de serviço.
    """
    assert CPF_VALIDO in str(payload), f"{nome}: payload sem PII não prova redação nenhuma"
    gravado = aplicar_retencao(payload, _sem_reter(), tipo=tipo)
    assert CPF_VALIDO not in str(gravado), f"{nome}: PII sobreviveu à redação em {gravado}"
    # e a CHAVE continua lá: a auditoria precisa ver que houve conteúdo suprimido
    assert set(gravado) == set(payload), f"{nome}: a redação apagou campo em vez de suprimir"


def test_b_redacao_e_deny_by_default_para_chave_nova() -> None:
    """Chave que ninguém previu nasce REDIGIDA, não retida.

    É o mesmo antídoto do conjunto FECHADO de `politica.py`: o serviço que amanhã
    acrescentar `{"anotacao_do_analista": ...}` ao ledger não pode criar um vazamento
    por omissão de quem escreveu esta lista meses antes.
    """
    gravado = aplicar_retencao(
        {"chave_que_ninguem_previu": "texto livre com dado do titular"},
        _sem_reter(),
        tipo="input",
    )
    assert gravado["chave_que_ninguem_previu"] == REDIGIDO


def test_b_redacao_preserva_correlacao_e_metrica() -> None:
    """Redigir não pode cegar a auditoria: id ESCALAR, nome canônico e número ficam.

    Suprimir `os_id` junto com o texto trocaria um problema por outro — a linha viraria
    impossível de correlacionar, e o Art. 20 pede o oposto disso.

    Os ids aqui são UUID porque é o que os serviços gravam (`str(os_.id)`). O teste
    usava `"OS-2026-0457"` e `"b1"`, e com isso afirmava uma garantia mais larga do que
    a plataforma precisa — ver `test_b_sufixo_id_preserva_pela_forma_do_valor`.
    """
    gravado = aplicar_retencao(
        {
            "os_id": UUID_CORRELACAO,
            "jornada_base_id": UUID_OUTRO,
            "consulta": "vw_metricas_jornada",
            "descartadas": 2,
            "valido": True,
            "resumo": "texto que sai",
        },
        _sem_reter(),
        tipo="output",
    )
    assert gravado["os_id"] == UUID_CORRELACAO
    assert gravado["jornada_base_id"] == UUID_OUTRO
    assert gravado["consulta"] == "vw_metricas_jornada"
    assert gravado["descartadas"] == 2
    assert gravado["valido"] is True
    assert gravado["resumo"] == REDIGIDO


def test_b_sufixo_id_preserva_pela_forma_do_valor_nao_pelo_nome_da_chave() -> None:
    """FURO 4 · `*_id` é padrão ABERTO e preservava QUALQUER escalar string.

    `CHAVES_TECNICAS` é lista fechada e curada — cada nome foi conferido contra quem
    produz o campo, então ali o nome basta. `SUFIXO_ID` não: ele casa com qualquer chave
    que qualquer um invente, e no `kv_master` quem inventa é o USUÁRIO (o corpo de
    `POST /os/{id}/criativos/gerar` é `dict[str, Any]`, e só `instrucoes` passa por
    `portao.sanear`). A auditoria mediu, pela rota, com `reter_* = false` publicado:

        "kv_master": {"produto":    "[SUPRIMIDO POR POLITICA DE RETENCAO]",
                      "cliente_id": "Maria da Conceicao dos Santos - 111.444.777-35",
                      "contato_id": "maria.da.conceicao@vivo.com.br"}

    É o furo do `evidencias` uma camada abaixo — preservar pelo NOME — e desta vez sem
    adversário: basta o analista nomear um campo de KV `cliente_id`. A correção olha a
    FORMA: correlação no §4.1 é UUID, e nome/e-mail/RG não são.
    """
    gravado = aplicar_retencao(
        {
            "kv_master": {
                "cliente_id": f"{PII_BR['nome_composto']} - {CPF_VALIDO}",
                "contato_id": "maria.da.conceicao@vivo.com.br",
                "documento_id": PII_BR["rg_de_minas"],
            },
            "os_id": UUID_CORRELACAO,
        },
        _sem_reter(),
        tipo="input",
    )
    assert gravado["kv_master"] == {
        "cliente_id": REDIGIDO,
        "contato_id": REDIGIDO,
        "documento_id": REDIGIDO,
    }
    # e a correlação de verdade continua inteira: a redação não cegou a auditoria
    assert gravado["os_id"] == UUID_CORRELACAO
    # UUID em maiúsculas também é UUID — recusá-lo cegaria a auditoria por formatação
    assert (
        aplicar_retencao({"pedido_id": UUID_CORRELACAO.upper()}, _sem_reter(), tipo="input")[
            "pedido_id"
        ]
        == UUID_CORRELACAO.upper()
    )


def test_b_documento_escrito_como_numero_nao_atravessa_a_redacao() -> None:
    """FURO 5 · valor não-textual atravessava intacto, e CPF cabe num JSON number.

    `kv_master` aceita `dict[str, Any]`: `{"documento": 11144477735}` chegava ao ledger
    inteiro sob `reter_* = false`, porque `isinstance(valor, str)` era falso. Um titular
    não fica menos identificado por ter sido escrito sem aspas.

    O custo do falso positivo é o que torna a régua aceitável, e ele é medido: nenhuma
    métrica do ledger chega a 11 dígitos, então nada de legítimo é destruído. Se este
    teste começar a apagar métrica, é a régua que está errada — não a métrica.
    """
    gravado = aplicar_retencao(
        {
            "documento": 11144477735,  # CPF
            "cnpj": 11222333000181,  # CNPJ
            "celular": 5511988776655,  # MSISDN com DDI
            # ...e tudo que é métrica de verdade sobrevive:
            "latencia_ms": 812,
            "contexto_chars": 1204,
            "verba_reais": 500000,
            "volume_disparos": 1200000,
            "cep": 1310100,
            "descartadas": 2,
            "valido": True,
            "recusa": None,
            "score": 0.87,
        },
        _sem_reter(),
        tipo="output",
    )
    assert gravado["documento"] == REDIGIDO
    assert gravado["cnpj"] == REDIGIDO
    assert gravado["celular"] == REDIGIDO
    assert gravado["latencia_ms"] == 812
    assert gravado["contexto_chars"] == 1204
    assert gravado["verba_reais"] == 500000
    assert gravado["volume_disparos"] == 1200000
    assert gravado["cep"] == 1310100
    assert gravado["descartadas"] == 2
    # `True` é `int` em Python: sem a exclusão explícita de bool o veredito passaria por
    # acidente em vez de por decisão, e um dia um veredito de 11 dígitos não passaria.
    assert gravado["valido"] is True
    assert gravado["recusa"] is None
    assert gravado["score"] == 0.87


def test_b_o_custo_do_falso_positivo_e_limitado_a_quem_desligou_a_retencao() -> None:
    """Um controle que destrói o trabalho do analista é um controle que ele desliga.

    A redação é agressiva de propósito (deny by default), então o preço tem de estar
    medido e ter limite. Ele tem dois:

    1. **Só existe com `reter_* = false`**, que é escolha explícita, versionada e
       assinada do DPO. No default do Art. 20 o payload sai byte a byte igual — inclusive
       o texto de negócio que um detector de PII poderia confundir com endereço
       ("Rua das tarifas" é nome de campanha) ou com nome próprio (o nome do AGENTE).
    2. **Sob `false`, ele não é seletivo e não pretende ser**: some o texto, ficam a
       correlação e as métricas. Não há julgamento sobre QUAL texto é PII, então não há
       falso positivo de detector — há uma decisão de política, que é o que o DPO
       assinou. É a diferença entre um controle previsível e um adivinho.
    """
    negocio = {
        "os_id": UUID_CORRELACAO,
        "verba": "R$ 500.000 aprovados para o trimestre",
        "janela": "de 01/03 a 15/03",
        "logradouro_da_campanha": "Rua das tarifas",  # NOME de campanha, não endereço
        "agente": "engineer",  # nome próprio de AGENTE, e é chave técnica
        "consulta": "vw_metricas_jornada",
        "latencia_ms": 812,
        "descartadas": 2,
        "valido": True,
    }

    # 1 — no default do Art. 20 nada é tocado: zero custo para quem não desligou nada
    assert aplicar_retencao(negocio, politica_ia_seed(), tipo="output") == negocio

    # 2 — desligado, o que sobrevive é exatamente correlação + métrica + vocabulário
    #     fechado. O resto é texto, e texto foi o que o DPO mandou não gravar.
    gravado = aplicar_retencao(negocio, _sem_reter(), tipo="output")
    sobrevivem = {k for k, v in gravado.items() if v != REDIGIDO}
    assert sobrevivem == {
        "os_id",
        "agente",
        "consulta",
        "latencia_ms",
        "descartadas",
        "valido",
    }, f"o custo da redação mudou sem ninguém declarar: sobrou {sorted(sobrevivem)}"


def test_b_pii_brasileira_sem_ancora_sintatica_e_redigida_por_ser_texto() -> None:
    """Nome com preposição, CAIXA ALTA, "Av." sem "Rua", CEP sem hífen, data por extenso.

    Nenhuma dessas formas tem âncora que um detector pegue com confiança — e é por isso
    que a retenção NÃO é um detector. Ela não pergunta "isto parece PII?"; ela suprime
    todo texto que não esteja declarado como técnico. O limite que sobra é declarado no
    teste seguinte, não escondido.
    """
    payload = {f"campo_{nome}": valor for nome, valor in PII_BR.items()}
    gravado = aplicar_retencao(payload, _sem_reter(), tipo="input")
    assert set(gravado) == set(payload), "a redação apagou campo em vez de suprimir"
    assert all(v == REDIGIDO for v in gravado.values()), gravado


def test_b_limite_declarado_a_chave_do_dicionario_nao_e_redigida() -> None:
    """LIMITE INTRANSPONÍVEL nesta camada, fixado aqui para não virar surpresa.

    A redação é dos VALORES. Se a PII estiver no NOME da chave — e o `kv_master` aceita
    chaves do usuário — ela sobrevive ao lado do valor suprimido. Não há conserto
    honesto aqui: apagar a chave mentiria sobre o campo ter existido, e redigi-la
    colidiria várias chaves numa só, destruindo a forma que esta função preserva de
    propósito. O conserto é a montante (o `kv_master` chegar saneado ao ledger, como
    `instrucoes` já chega) e está na EMENDA SUGERIDA.

    Este teste existe para que o limite seja um FATO VERSIONADO, e não a descoberta de
    um DPO lendo o ledger. Se alguém sanear a montante, este teste é o que avisa que a
    afirmação da tela pode mudar.
    """
    gravado = aplicar_retencao(
        {"kv_master": {f"{PII_BR['nome_composto']} {CPF_VALIDO}": "elegivel"}},
        _sem_reter(),
        tipo="input",
    )
    chaves = list(gravado["kv_master"])
    assert gravado["kv_master"][chaves[0]] == REDIGIDO  # o VALOR some
    assert CPF_VALIDO in chaves[0]  # a CHAVE não — e é isso que a tela precisa dizer


def test_b_evidencias_nao_e_referencia_tecnica_e_por_isso_e_redigida() -> None:
    """FURO 2 · a lista de exceções afirmava uma premissa FALSA sobre `evidencias`.

    O comentário de `CHAVES_TECNICAS` justificava a preservação dizendo que evidência é
    "id e ref `nome@versao`". Nenhum produtor faz isso: os três intérpretes de saída de
    agente montam a lista com `str(e).strip()` do que o MODELO escreveu, e no audiencia
    o teor vem do corpus RAG. Com `reter_* = false` a auditoria lia `[SUPRIMIDO...]` na
    `resposta` e o texto do titular intacto na chave ao lado — dentro da lista que
    existe para impedir exatamente isso.

    Este teste morre se alguém devolver `evidencias` a `CHAVES_TECNICAS` sem antes
    mudar quem PRODUZ o campo. Preservar ref versionada continua sendo desejável, mas
    exige olhar a FORMA do valor, nunca o nome da chave.
    """
    assert "evidencias" not in CHAVES_TECNICAS, (
        "preservar `evidencias` pelo NOME devolve texto livre do modelo ao ledger"
    )
    livre = "Solicitante Joao (contato joao@acme.com.br) pediu 500k"
    gravado = aplicar_retencao({"evidencias": [livre]}, _sem_reter(), tipo="output")
    assert gravado["evidencias"] == [REDIGIDO]
    # também no formato ESCALAR — é aqui que a saída da lista de exceções é a ÚNICA
    # coisa que segura o texto: a regra de container não alcança uma string solta.
    escalar = aplicar_retencao({"evidencias": livre}, _sem_reter(), tipo="output")
    assert escalar["evidencias"] == REDIGIDO

    # e o default (reter=true) continua entregando a prova do Art. 20 inteira
    retido = aplicar_retencao({"evidencias": [livre]}, politica_ia_seed(), tipo="output")
    assert retido["evidencias"] == [livre]


def test_b_chave_preservada_com_estrutura_embaixo_nao_atravessa() -> None:
    """FURO 3 · `*_id`/chave técnica com dicionário ou lista embaixo passava INTEIRA.

    `_preservar` decidia só pelo NOME e devolvia o valor sem olhar, então
    `{"os_id": {...}}` era um bolso onde qualquer texto sobrevivia em qualquer
    profundidade. A correção desce na estrutura em vez de devolvê-la: o texto some e os
    `*_id` ESCALARES lá dentro continuam correlacionáveis, que é o ponto do `SUFIXO_ID`.
    """
    gravado = aplicar_retencao(
        {
            "os_id": {"nota": "texto do titular", "pedido_id": UUID_OUTRO},
            "consulta": ["SELECT texto livre"],
            "propostas": ["3f1a0c2e-0000-4000-8000-000000000001"],
        },
        _sem_reter(),
        tipo="output",
    )
    assert gravado["os_id"] == {"nota": REDIGIDO, "pedido_id": UUID_OUTRO}
    assert gravado["consulta"] == [REDIGIDO]
    # Custo declarado: lista de uuids também é redigida — uma lista de escalares não se
    # distingue, PELA CHAVE, de `evidencias`. A correlação das propostas com a invocação
    # está no evento `proposta.criada` (§2.3), que a retenção não toca.
    assert gravado["propostas"] == [REDIGIDO]

    # o escalar sob a MESMA chave segue preservado — a correção é sobre estrutura
    escalar = aplicar_retencao({"os_id": UUID_CORRELACAO}, _sem_reter(), tipo="output")
    assert escalar["os_id"] == UUID_CORRELACAO


def test_b_coluna_evidencias_passa_pela_retencao() -> None:
    """FURO 1 · a COLUNA `invocacao.evidencias` (§4.1) nunca era oferecida à retenção.

    `reter_output` embrulha o dicionário `output`; os serviços atribuíam `evidencias=`
    ao lado, fora do portão. Nenhuma configuração de política alcançava o campo —
    `reter_prompt: false` + `reter_resposta: false` publicados e o texto continuava lá,
    legível por `GET /auditoria` e por `POST /auditoria/reconstruir`.

    As DUAS flags governam a coluna, e a conjunção é a decisão: a evidência é eco do
    PROMPT (no consultor é o trecho da conversa) e saída do MODELO (no audiencia é o que
    ele citou do corpus). Preservá-la com um dos lados desligado devolveria pela coluna
    o texto que o DPO mandou não gravar.
    """
    livre = ["Solicitante Joao (contato joao@acme.com.br) pediu 500k"]

    # A — default do Art. 20: a prova fica inteira
    assert aplicar_retencao_evidencias(livre, politica_ia_seed()) == livre

    # B — qualquer lado desligado redige a coluna
    for campo in ("reter_prompt", "reter_resposta"):
        conteudo = politica_ia_seed()
        conteudo["retencao"][campo] = False
        assert aplicar_retencao_evidencias(livre, conteudo) == [REDIGIDO], (
            f"com {campo}=false a coluna `evidencias` devolveria o texto suprimido"
        )

    # tupla (é o que `SaidaEngineer.evidencias` de fato é) e estrutura aninhada também
    aninhada = aplicar_retencao_evidencias(
        ({"trecho": "texto livre", "evidencia_id": UUID_OUTRO},), _sem_reter()
    )
    assert aninhada == [{"trecho": REDIGIDO, "evidencia_id": UUID_OUTRO}]

    # não muta a entrada: a rota e o evento ainda usam as evidências originais
    original = ["texto"]
    aplicar_retencao_evidencias(original, _sem_reter())
    assert original == ["texto"]


def test_b_redacao_nao_muta_o_payload_original() -> None:
    """O serviço ainda precisa do texto original para a chamada em curso — redigir a
    estrutura recebida (agora que a função é recursiva) corromperia o prompt."""
    original = {"kv_master": {"headline": "texto"}, "instrucoes": "x"}
    aplicar_retencao(original, _sem_reter(), tipo="input")
    assert original == {"kv_master": {"headline": "texto"}, "instrucoes": "x"}


def test_b_default_retem_porque_o_art20_exige_reconstruir() -> None:
    """Guarda-corpo de doutrina: se alguém "minimizar" o default para não reter, este
    teste morre e obriga a discussão — reconstrução do Art. 20 depende do ledger."""
    conteudo = politica_ia_seed()
    assert conteudo["retencao"]["reter_prompt"] is True
    assert conteudo["retencao"]["reter_resposta"] is True


# ========================================================== (c) decisao_automatizada


def test_c_allowlist_governa_propor_versus_aplicar() -> None:
    """Par A/B do parâmetro (c): a MESMA ação muda de modo conforme a política."""
    # A — v1: allowlist vazia. Tudo propõe (é o comportamento de hoje do `ajustar`).
    conteudo_a = politica_ia_seed()
    assert modo_de_decisao("jornada.ajustar", conteudo_a) == "propor"
    with pytest.raises(DecisaoAutomatizadaNegada) as erro:
        exigir_revisao_humana("jornada.ajustar", conteudo_a)
    assert erro.value.acao == "jornada.ajustar"
    assert "Art. 20" in erro.value.motivo

    # B — DPO autoriza explicitamente: a mesma ação passa a poder aplicar sozinha.
    conteudo_b = _politica(decisao_automatizada={"pode_aplicar_sozinho": ["jornada.ajustar"]})
    assert modo_de_decisao("jornada.ajustar", conteudo_b) == "aplicar"
    exigir_revisao_humana("jornada.ajustar", conteudo_b)  # não levanta


def test_c_autorizar_uma_acao_nao_autoriza_as_vizinhas() -> None:
    """Allowlist é por ação: liberar o twin não pode liberar o otimizador."""
    conteudo = _politica(decisao_automatizada={"pode_aplicar_sozinho": ["jornada.ajustar"]})
    assert modo_de_decisao("otimizacao.propor", conteudo) == "propor"


def test_c_acao_desconhecida_nunca_e_automatizada() -> None:
    """Typo na allowlist falha para o lado SEGURO (segue propondo), e a validação
    recusa a publicação — o DPO descobre na hora, não na auditoria."""
    conteudo = _politica(decisao_automatizada={"pode_aplicar_sozinho": ["jornada.ajusta"]})
    assert modo_de_decisao("jornada.ajusta", conteudo) == "propor"
    assert any("ação desconhecida" in e for e in validar_conteudo(conteudo))


def test_c_conteudo_corrompido_nao_libera_automacao() -> None:
    assert modo_de_decisao("jornada.ajustar", {}) == "propor"
    assert modo_de_decisao("jornada.ajustar", {"decisao_automatizada": {}}) == "propor"


# =========================================================== (f) modelos_permitidos


def test_f_perfil_fora_da_lista_do_agente_e_recusado() -> None:
    """Par A/B do parâmetro (f): o mesmo agente+perfil passa ou é barrado."""
    # A — v1 pina o roster §7.2: engineer é 120b.
    conteudo_a = politica_ia_seed()
    exigir_perfil_autorizado("engineer", "120b", conteudo_a)  # não levanta
    assert perfis_permitidos("engineer", conteudo_a) == ("120b",)

    # B — tenant restringe o engineer ao modelo pequeno.
    conteudo_b = politica_ia_seed()
    conteudo_b["modelos_permitidos"]["engineer"] = ["20b"]
    with pytest.raises(ModeloNaoPermitido) as erro:
        exigir_perfil_autorizado("engineer", "120b", conteudo_b)
    assert erro.value.agente == "engineer"
    assert erro.value.perfil == "120b"


def test_f_typo_no_nome_do_agente_e_recusado_na_publicacao() -> None:
    """Achado do auditor: agente fora do roster §7.2 passava calado na validação.

    O DPO escrevia `enginer: ["20b"]` achando que restringira o engineer. A entrada
    virava letra morta, `perfis_permitidos("engineer", ...)` caía no roster e o 120b
    seguia liberado — restrição publicada, assinada e sem efeito. Mesma classe do typo
    em `ACOES_VIA_AI`, que o módulo já recusava; faltava a simetria aqui.
    """
    conteudo = politica_ia_seed()
    conteudo["modelos_permitidos"]["enginer"] = ["20b"]
    assert any("agente desconhecido" in e and "enginer" in e for e in validar_conteudo(conteudo))
    # A prova de que era inerte: o agente de verdade continua com o roster aberto.
    assert perfis_permitidos("engineer", conteudo) == ("120b",)


def test_f_agente_desconhecido_nao_ganha_modelo_por_omissao() -> None:
    """Agente que não está na política NEM no roster §7.2 não é liberado por silêncio."""
    conteudo = politica_ia_seed()
    assert perfis_permitidos("agente_novo_sem_roster", conteudo) == ()
    with pytest.raises(ModeloNaoPermitido):
        exigir_perfil_autorizado("agente_novo_sem_roster", "20b", conteudo)


# =================================================== conjunto FECHADO e anti-inércia


def test_conjunto_fechado_recusa_parametro_sem_enforcement() -> None:
    """O antídoto do achado 8 aplicado ao próprio módulo.

    `teto_tokens` é o exemplo VIVO: parece responsável, e seria inerte, porque
    `invocacao.tokens` é sempre NULL (`LLMPort.chat` devolve `str` e descarta o
    `usage`). Enquanto a medição não existir, publicar o campo é proibido pela
    validação — não por convenção, por código.
    """
    conteudo = politica_ia_seed()
    conteudo["teto_tokens"] = {"por_os": 100_000}
    erros = validar_conteudo(conteudo)
    assert any("teto_tokens" in e and "conjunto FECHADO" in e for e in erros)


def test_nao_existe_acao_permitir_para_pii() -> None:
    """O piso do C02 não é configurável: nenhuma política pode DESLIGAR o mascaramento.

    Se um dia `permitir` for aceito, este teste morre — e é para morrer barulhento: a
    tela de IA Responsável viraria o maior vetor de vazamento da plataforma.
    """
    conteudo = _com_acao("email", "permitir")
    erros = validar_conteudo(conteudo)
    assert any("permitir" in e for e in erros)
    # E, mais importante que a validação: o caminho de execução continua mascarando.
    assert "[EMAIL]" in sanear_para_llm(TEXTO_COM_EMAIL, conteudo).texto


def test_validacao_acumula_erros_em_vez_de_parar_no_primeiro() -> None:
    """Padrão do parser §7.1 — quem edita é o DPO pela tela, não um dev com stack trace."""
    erros = validar_conteudo({"dados_llm": {"acoes": {"cpf": "permitir"}}, "desconhecido": 1})
    assert len(erros) >= 3  # campos obrigatórios faltando + ação inválida + campo estranho


def test_seed_v1_passa_na_propria_validacao() -> None:
    """Trava de deriva: default e validação não podem divergir (um campo novo no seed
    sem entrada em CAMPOS_CONTEUDO tornaria a v1 impublicável)."""
    assert validar_conteudo(politica_ia_seed()) == []


def test_seed_devolve_estrutura_nova_a_cada_chamada() -> None:
    """É função, não constante: um teste que mexe no default não pode envenenar outro."""
    primeira = politica_ia_seed()
    primeira["retencao"]["dias_trace"] = 1
    assert politica_ia_seed()["retencao"]["dias_trace"] == 30


def test_entidade_nasce_draft_e_guarda_autoria() -> None:
    """Auditabilidade: a linha responde "quem e quando" sem correlacionar log."""
    politica = PoliticaIa(
        id=uuid.uuid4(),
        tenant_id="torre-movel",
        versao=1,
        conteudo=politica_ia_seed(),
        autor_id=uuid.uuid4(),
        autor_nome="DPO da Torre",
        motivo="v1 — espelha o comportamento vigente",
    )
    assert politica.estado == "draft"
    assert politica.publicada is False


# ============================================================ guarda-corpo do achado 8


def test_nenhum_servico_importa_a_seed_direto() -> None:
    """A regra que o achado 8 do UAT #5 cobrou, agora vigiada no CI para ESTE módulo.

    Irmão do `test_achado8_guarda_corpo_politica` (M12): serviço que importa a semente
    lê uma constante compilada, e a tela volta a publicar no vazio. A fonte em runtime
    tem de ser a política PUBLICADA, lida por porta e injetada.
    """
    servicos = RAIZ / "backend" / "application" / "services"
    ofensores = [
        arquivo.name
        for arquivo in servicos.glob("*.py")
        if "politica_ia_seed" in arquivo.read_text(encoding="utf-8")
        or "ia_responsavel.politica import" in arquivo.read_text(encoding="utf-8")
    ]
    assert ofensores == [], (
        f"{ofensores} importam a SEMENTE da política de IA Responsável. "
        "Em runtime a política vem da linha PUBLICADA, injetada por porta (achado 8)."
    )
