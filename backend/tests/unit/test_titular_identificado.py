"""Unit do titular IDENTIFICADO — nome, endereço, CEP, data de nascimento e RG (§10.2).

A auditoria da onda 3c mediu o buraco com três frases, e as três estão aqui palavra por
palavra (`MEDIDO_*`): o detector só via run de dígito e e-mail, então titular
identificado — que numa base de telco é a PII MAIS comum da caixa de texto livre — saía
INTACTO para o hub LLM (terceiro fora do perímetro), para a coluna `input` do ledger,
para o índice `agente_evidence` (de onde REAPARECE como precedente de outro usuário) e
para o Langfuse.

Este arquivo tem três obrigações, e a terceira é a que costuma faltar:

1. **detectar** o que a auditoria mediu saindo em claro;
2. **não estragar** o texto de negócio — verba, volume, janela e código de OS continuam
   intactos (há aceite provando isso, e ele não pode ser afrouxado);
3. **provar o LIMITE**. Nome e endereço não têm formato: o detector é por CONTEXTO e
   erra por baixo de propósito. Os `test_limite_*` fixam por código onde ele para. São
   testes que passam AFIRMANDO que algo NÃO é detectado — se um deles quebrar porque
   alguém apertou o detector, ótimo: apaga-se o teste junto com a limitação. O que não
   pode acontecer é o limite existir e não estar escrito em lugar nenhum (§1.3.5).
"""

import pytest

from domain.privacidade.mascarar import mascarar_pii, mascarar_pii_em_campo
from domain.privacidade.sanitizar import mascarar_campos

# As TRÊS frases medidas pela auditoria, que saíam intactas.
MEDIDO_NOME = "Cliente Maria Aparecida da Silva Santos, mae Joana Silva, nascida em 14/03/1987."
MEDIDO_ENDERECO = "Rua das Flores 123, apto 42, Vila Mariana, Sao Paulo/SP, CEP 01310-100."
MEDIDO_RG = "RG 12.345.678-9 orgao SSP/SP."


# ============================================================ 1. o que a auditoria mediu


def test_titular_identificado_medido_pela_auditoria_nao_sai_mais_em_claro() -> None:
    """As três frases da auditoria, com o resultado EXATO — não `assert contem_pii`.

    Comparar a string inteira é o que impede o teste de virar carimbo: ele fixa
    simultaneamente o que foi mascarado, o que sobrou e a âncora que foi preservada
    (`mae [NOME]` continua dizendo ao agente que havia uma filiação no pedido).
    """
    assert mascarar_pii(MEDIDO_NOME) == "Cliente [NOME], mae [NOME], nascida em [DATA_NASCIMENTO]."
    assert mascarar_pii(MEDIDO_ENDERECO) == "[ENDERECO], Vila Mariana, Sao Paulo/SP, CEP [CEP]."
    assert mascarar_pii(MEDIDO_RG) == "RG [RG] orgao SSP/SP."


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        # --- nome por âncora FORTE (1 token basta; caixa alta aceita)
        ("Sra. Oliveira ligou ontem", "Sra. [NOME] ligou ontem"),
        ("Sr. Joao Carlos de Almeida reclamou", "Sr. [NOME] reclamou"),
        ("titular MARIA SILVA em atraso", "titular [NOME] em atraso"),
        ("mae: Joana Aparecida", "mae: [NOME]"),
        ("nome do cliente Ricardo Nunes", "nome do cliente [NOME]"),
        # --- nome por âncora FRACA (exige CONECTIVO na cadeia — ver a auditoria 3c)
        ("falar com Ana Paula de Ferreira sobre a oferta", "falar com [NOME] sobre a oferta"),
        ("ligar para Carlos Eduardo dos Anjos amanha", "ligar para [NOME] amanha"),
        (
            "o assinante Pedro Henrique de Souza pediu portabilidade",
            "o assinante [NOME] pediu portabilidade",
        ),
        # CAIXA ALTA sob âncora FRACA: era limite declarado, o conectivo tornou seguro.
        # É a forma que um export de CRM de telco produz.
        ("cliente MARIA APARECIDA DA SILVA em atraso", "cliente [NOME] em atraso"),
        # --- endereço: âncora de logradouro + TOPÔNIMO + número (+ complemento colado)
        ("entrega na Avenida Paulista 1578, apto 91", "entrega na [ENDERECO]"),
        ("Rua das Flores, 123 - conferir", "[ENDERECO] - conferir"),
        ("mora na Travessa do Ouvidor 45 desde 2019", "mora na [ENDERECO] desde 2019"),
        # ABREVIADO — as alternativas que existiam no padrão e NUNCA casavam, porque o
        # `\b` final do grupo não podia valer depois do ponto de `av.` (auditoria 3c).
        ("entrega na Av. Paulista 1000", "entrega na [ENDERECO]"),
        ("Av Paulista 1000", "[ENDERECO]"),
        ("AV. PAULISTA 1000", "[ENDERECO]"),
        ("Av. Brig. Faria Lima 3477, conj. 51", "[ENDERECO], conj. 51"),
        ("R. Augusta 1200", "[ENDERECO]"),
        ("Al. Santos 45", "[ENDERECO]"),
        ("Rod. Raposo Tavares 12000", "[ENDERECO]"),
        ("Av. das Nacoes Unidas, 14401", "[ENDERECO]"),
        # --- CEP: forma canônica 5-3 sozinha, e sem pontuação com âncora
        ("entrega no 01310-100 amanha", "entrega no [CEP] amanha"),
        ("CEP 01310100 confirmado", "CEP [CEP] confirmado"),
        ("cep: 04538-133", "cep: [CEP]"),
        # --- RG: pontuado sozinho, e cru com âncora
        ("documento 12.345.678-9 anexado", "documento [RG] anexado"),
        ("RG 123456789 emitido em 2010", "RG [RG] emitido em 2010"),
        ("RG nº 12.345.678-X", "RG nº [RG]"),
        # CEP e RG nas formas de OUTROS ESTADOS / com `nº` (auditoria 3c)
        ("Cep n 01310100 confirmado", "Cep n [CEP] confirmado"),
        ("CEP 01.310-100", "CEP [CEP]"),
        ("RG 1.234.567 SSP/MG", "RG [RG] SSP/MG"),
        ("RG MG-12.345.678", "RG MG-[RG]"),
        ("RG M 1234567", "RG M [RG]"),
        ("RG: 20.123.456-7 DETRAN/RJ", "RG: [RG] DETRAN/RJ"),
        # --- data de nascimento: SÓ com âncora de nascimento
        ("nascido em 14/03/1987", "nascido em [DATA_NASCIMENTO]"),
        ("data de nascimento 1987-03-14", "data de nascimento [DATA_NASCIMENTO]"),
        ("nascimento: 14 de marco de 1987", "nascimento: [DATA_NASCIMENTO]"),
        ("nascida em 14 de marco de 1987", "nascida em [DATA_NASCIMENTO]"),
    ],
)
def test_mascara_titular_identificado(entrada: str, esperado: str) -> None:
    assert mascarar_pii(entrada) == esperado


# ====================================================== 2. não estragar o texto de negócio


@pytest.mark.parametrize(
    "texto",
    [
        # O trio do aceite C02 — se algum destes for mascarado, o briefing perde o pedido
        "A verba é de R$ 480.000 para 847.312 clientes na janela de 01/10 a 15/10.",
        "verba de R$ 480.000 para 847.312 clientes",
        # data SEM âncora de nascimento continua sendo data de campanha
        "janela de 01/10 a 15/10 de 2026",
        "publicado em 2026-08-06 às 14:30",
        "campanha 06/08/2026",
        "resultado consolidado em 14/03/1987 (base histórica)",
        # marca/área/segmento depois de âncora FRACA não é pessoa
        "cliente Vivo aprovou a proposta",
        "falar com Marketing sobre o criativo",
        "ligar para Suporte antes de subir",
        "contato de teste no ambiente",
        # rótulos de SEGMENTO depois de "clientes" — o caso mais comum deste domínio,
        # cortado por `_NAO_SEGMENTO` (lista de palavras comuns, não de nomes)
        "clientes Alto Valor em churn",
        "clientes Base Ouro na campanha",
        "clientes Pré Pago migrados",
        # códigos e números da plataforma (§11.4)
        "OS-2026-0457 aprovada",
        "compare OS-2025-0311 com OS-2026-0457",
        "1.234.567 envios com ROAS 18,5x",
        "12345678 impressões no período",
        "lift de 24,1% e CPM 0,0018",
        # ------------------------------------------------------------------------
        # As linhas abaixo são o CORPUS DE FALSO POSITIVO da auditoria da onda 3c.
        # Nenhuma tem PII. Na primeira medição, 35% delas eram destruídas — 16 de 16
        # frases com âncora fraca viravam `[NOME]`, e toda figura de linguagem com um
        # ano virava `[ENDERECO]`. Esse número é o que faz o analista DESLIGAR o
        # controle, e controle desligado protege zero; por isso ele é aceite, não nota
        # de rodapé. Se uma destas quebrar, o detector apertou onde não devia.
        # ------------------------------------------------------------------------
        # produto/segmento/marca depois de âncora fraca (o desempate é o CONECTIVO)
        "clientes Fibra Residencial da regiao Sul entram na onda 2",
        "clientes Movel Controle migrados",
        "assinantes Banda Larga Ultra",
        "usuario Portal Meu Vivo reclamou do login",
        "Cliente Vivo Empresas pediu antecipacao",
        "cliente Claro Controle",
        "clientes Tim Black Familia",
        "beneficiario Programa Fidelidade",
        "consumidor Classe Media",
        "cliente PRE PAGO e cliente ALTO VALOR",
        # ÁREA/EQUIPE com conectivo — o conectivo sozinho não a separa de pessoa
        # ("Central de Relacionamento" tem a mesma forma de "Maria da Silva"); quem
        # separa é a CABEÇA da locução, em `_NAO_SEGMENTO`
        "contato Central de Relacionamento para escalar",
        "Contatar Gestao de Base sobre o corte",
        "falar com Diretoria de Marketing antes de subir",
        "ligar para Central de Atendimento ao Cliente",
        "atender Carteira de Grandes Contas primeiro",
        "contato Gerencia de Produto sobre o roadmap",
        "Ligar para Suporte Tecnico Nivel 2 se houver incidente",
        "Falar com Recursos Humanos antes",
        # figura de linguagem com ANO/CONTAGEM: o número NÃO basta para ser endereço —
        # é o topônimo em Caixa Alta Inicial que separa
        "A avenida de crescimento 2026 depende desta acao",
        "A estrada da transformacao digital 2026",
        "Rodovia da inovacao 2026",
        "Quadra de indicadores 2026",
        "Praca de midia com 3 canais",
        "Estrada de dados: 12 fontes integradas",
        "Alameda de parceiros com 15 marcas",
        "Largo prazo de 12 meses",
        "Rua principal do funil, etapa 2",
        "Travessa de campanhas, versao 3",
        "Rua das tarifas: revisar politica de preco",
        # qualificador de contrato/cadastro depois de âncora FORTE
        "titular unico por conta, pessoa juridica",
        "titulares Empresariais da carteira Sul",
        "nome completo obrigatorio no formulario",
        "nome do cliente deve ser validado no CRM",
        "portador de deficiencia visual precisa de acessibilidade",
        # nome de AGENTE/colaborador: mascará-lo apagaria a trilha de quem pediu (§2.3)
        "Analista responsavel: Carlos Eduardo Lima",
        "Aprovado por Ana Paula Souza em 2026-08-06",
        "solicitante Pedro Henrique Alves",
        "Atendido pelo consultor Marcos Vinicius Rocha",
        # hash de contato é o dado JÁ pseudonimizado — o oposto de PII em claro
        "Hash de contato a3f5c9d1e2b4a6c8d0f2e4b6a8c0d2e4 usado no match",
        "Nome da campanha: Reativa Sul 2026",
        "nome do segmento: Alto Valor",
    ],
)
def test_nao_mascara_texto_legitimo_de_negocio(texto: str) -> None:
    """Falso positivo é bug: apagar verba/volume/janela/marca destrói o briefing."""
    assert mascarar_pii(texto) == texto


def test_o_aceite_C02_continua_valendo_letra_por_letra() -> None:
    """Trava anti-afrouxamento: a frase exata do unit do C02, com o mesmo resultado.

    Se um detector novo comesse "Cliente" ou o "R$ 480.000" desta frase, o aceite C02
    quebraria em outro arquivo e a causa ficaria longe da mudança. Aqui ela fica perto.
    """
    entrada = (
        "Cliente joao@x.com.br, CPF 529.982.247-25, fone (11) 98765-4321 — "
        "verba R$ 480.000 na janela 01/10 a 15/10."
    )
    assert mascarar_pii(entrada) == (
        "Cliente [EMAIL], CPF [CPF], fone [TELEFONE] — verba R$ 480.000 na janela 01/10 a 15/10."
    )


@pytest.mark.parametrize("texto", [MEDIDO_NOME, MEDIDO_ENDERECO, MEDIDO_RG])
def test_idempotente_e_deterministico(texto: str) -> None:
    """Marcador não vira outro marcador: `[NOME]` reprocessado continua `[NOME]`.

    Vale mais do que parece: `categorias_detectadas` (§10.2) conta o DELTA de marcadores
    antes/depois, e um mascarador não idempotente faria a contagem mentir.
    """
    uma = mascarar_pii(texto)
    assert mascarar_pii(uma) == uma
    assert mascarar_pii(texto) == uma


# =========================================== 3. a chave do formulário como ÂNCORA (3c)


@pytest.mark.parametrize(
    ("chave", "valor", "esperado"),
    [
        # É a forma REAL do dado num briefing: âncora na chave, dado no valor.
        ("nome do titular", "Maria Aparecida da Silva Santos", "[NOME]"),
        ("titular", "Joana Silva", "[NOME]"),
        ("cep", "01310100", "[CEP]"),
        ("rg", "123456789", "[RG]"),
        ("data de nascimento", "14/03/1987", "[DATA_NASCIMENTO]"),
        # ...e o valor que já traz a própria âncora continua funcionando
        ("observacao", "Rua das Flores 123", "[ENDERECO]"),
        ("observacao", "CPF 529.982.247-25", "CPF [CPF]"),
        # snake_case e kebab-case: a forma DOMINANTE de chave em JSON, e a que a
        # auditoria da onda 3c mediu saindo em claro. `_` é caractere de PALAVRA, então
        # em `nome_do_titular` nem `\btitular` existia para as âncoras enxergarem.
        ("nome_do_titular", "Maria Aparecida da Silva Santos", "[NOME]"),
        ("nome_titular", "Maria Aparecida da Silva Santos", "[NOME]"),
        ("nome_completo", "MARIA APARECIDA DA SILVA", "[NOME]"),
        ("nome-do-titular", "Maria Aparecida da Silva Santos", "[NOME]"),
        ("data_de_nascimento", "14/03/1987", "[DATA_NASCIMENTO]"),
        ("endereco_completo", "Av. Paulista 1000, apto 51", "[ENDERECO]"),
        # sufixo `_id`: é como um CRM nomeia a coluna, e o que colam ali nem sempre é
        # id — medido numa sonda por ROTA com `kv_master` de `POST /criativos/gerar`
        ("cliente_id", "Maria da Conceicao dos Santos", "[NOME]"),
        ("titular_id", "Joana Silva", "[NOME]"),
        # ...e um id de VERDADE na mesma chave continua intacto (o sufixo não cria
        # falso positivo: id não tem forma de nome)
        ("cliente_id", "CL-88213", "CL-88213"),
        ("cliente_id", "12345", "12345"),
    ],
)
def test_chave_do_campo_funciona_como_ancora_do_valor(
    chave: str, valor: str, esperado: str
) -> None:
    assert mascarar_pii_em_campo(chave, valor) == esperado


def test_ancora_da_chave_desce_para_o_dicionario_ANINHADO() -> None:
    """`conteudo` é `dict[str, Any]` ABERTO: quem digita escolhe a forma, e um cadastro
    de telco aninha (`{"dados do titular": {"nome completo": "..."}}`).

    Delegar o valor aninhado a `mascarar_estrutura` — que por contrato ignora a chave,
    porque roda sobre payload de evento e trace — perdia a âncora no PRIMEIRO nível de
    profundidade, e o titular saía inteiro. Vale também dentro de lista: o item herda a
    chave do campo que o contém, que é justamente a âncora certa.
    """
    assert mascarar_campos(
        {"dados do titular": {"nome completo": "Maria Aparecida da Silva Santos"}}
    ) == {"dados do titular": {"nome completo": "[NOME]"}}
    assert mascarar_campos({"titulares": ["Maria Aparecida da Silva", "Joao de Souza"]}) == {
        "titulares": ["[NOME]", "[NOME]"]
    }
    # e o negócio aninhado continua inteiro — inclusive o número, que não é texto
    assert mascarar_campos(
        {"campanha": {"nome": "Reativa Sul 2026", "verba": "R$ 480.000", "volume": 847_312}}
    ) == {"campanha": {"nome": "Reativa Sul 2026", "verba": "R$ 480.000", "volume": 847_312}}


def test_chave_nunca_e_reescrita_dentro_do_valor() -> None:
    """`mascarar_pii_em_campo` devolve SÓ o valor — a chave é responsabilidade do
    chamador (`mascarar_campos`), que a mascara à parte (achado 9 do UAT #5)."""
    assert mascarar_pii_em_campo("objetivo", "Pós-pago 12+ meses") == "Pós-pago 12+ meses"
    assert mascarar_pii_em_campo("verba", "480000") == "480000"
    assert mascarar_pii_em_campo("qualquer", "") == ""


# ================================================================ 4. LIMITES DECLARADOS


def test_limite_nome_sem_ancora_nao_e_detectado() -> None:
    """Nome solto não tem sinal: "Maria Aparecida da Silva Santos" é indistinguível de
    "Vale do Silício" ou de uma razão social sem semântica. Detectar por lista de nomes
    próprios daria falso negativo garantido e comeria palavra comum — o §1.3.5 manda
    declarar o limite em vez de prometer o que não se cumpre."""
    solto = "Maria Aparecida da Silva Santos ligou hoje"
    assert mascarar_pii(solto) == solto


def test_limite_nome_sem_conectivo_apos_ancora_fraca_nao_e_detectado() -> None:
    """O limite mais caro da lista, e o que a auditoria da onda 3c comprou de propósito.

    A régua anterior era "2+ tokens em Caixa Alta Inicial" e ela NÃO sustentava o peso:
    16 de 16 frases de negócio deste domínio viravam `[NOME]` (`clientes Fibra
    Residencial`, `Cliente Vivo Empresas`, `assinantes Banda Larga Ultra`), 35% de um
    briefing sem PII nenhuma. O desempate passou a ser o CONECTIVO de nome português,
    que é sinal de FORMA e não lista de nomes próprios.

    O preço: sob âncora FRACA, nome sem conectivo sai em claro. Continua coberto por
    outros caminhos — âncora FORTE, chave de formulário, e qualquer nome ao lado de
    CPF/telefone/e-mail (que saem por FORMA). É falso negativo NOMEADO, não descuido.
    """
    assert mascarar_pii("ligar para Joao amanha") == "ligar para Joao amanha"
    assert mascarar_pii("cliente Joana Silva ligou") == "cliente Joana Silva ligou"
    # com conectivo o mesmo texto JÁ é detectado — é onde a linha foi traçada
    assert mascarar_pii("ligar para Joana da Silva") == "ligar para [NOME]"
    # e a âncora FORTE não precisa de conectivo nenhum: é o caminho que fica
    assert mascarar_pii("titular Joana Silva ligou") == "titular [NOME] ligou"


def test_limite_endereco_sem_numero_e_bairro_solto_nao_sao_detectados() -> None:
    """O número é o que separa endereço de figura de linguagem e de bairro solto.
    Sem ele, "Rua das Flores, próximo ao mercado" sai em claro; "Vila Mariana, São
    Paulo/SP" também (cidade/UF sozinhos não identificam ninguém)."""
    sem_numero = "Rua das Flores, proximo ao mercado"
    assert mascarar_pii(sem_numero) == sem_numero
    bairro = "cobertura em Vila Mariana, Sao Paulo/SP"
    assert mascarar_pii(bairro) == bairro


def test_caixa_alta_apos_ancora_fraca_DEIXOU_de_ser_limite() -> None:
    """Era limite declarado; o conectivo obrigatório o eliminou, e isso é ganho de fato.

    A justificativa antiga ("depois de `cliente`, CAIXA ALTA é quase sempre segmento")
    estava certa sobre o RISCO e errada sobre a solução: recusar a caixa alta inteira
    também recusava `cliente MARIA APARECIDA DA SILVA`, que é exatamente a forma que um
    export de CRM de telco produz — o pior caso possível para um falso negativo. Com o
    conectivo, os dois lados são atendidos ao mesmo tempo: plano/segmento não tem
    conectivo, nome completo tem.
    """
    assert mascarar_pii("cliente PRE PAGO em churn") == "cliente PRE PAGO em churn"
    assert mascarar_pii("cliente ALTO VALOR") == "cliente ALTO VALOR"
    assert mascarar_pii("cliente MARIA APARECIDA DA SILVA") == "cliente [NOME]"


def test_limite_falso_positivo_aceito_razao_social_apos_ancora_de_pessoa() -> None:
    """Erro conhecido na direção SEGURA: razão social COM CONECTIVO vira `[NOME]`.

    Apaga um termo de negócio; não vaza titular. Está aqui para ser visto, não para ser
    defendido — se um dia doer, a correção é distinguir razão social, não afrouxar.

    A auditoria da onda 3c encolheu bastante este buraco sem afrouxar nada: sem
    conectivo ("cliente Torre Movel") já não é mais tocado, e as cabeças de locução de
    área ("Central de", "Gestão de", "Diretoria de") estão em `_NAO_SEGMENTO`.
    """
    assert mascarar_pii("o cliente Casa de Carnes renovou") == "o cliente [NOME] renovou"
    # sem conectivo, o falso positivo antigo desapareceu
    assert mascarar_pii("o cliente Torre Movel renovou") == "o cliente Torre Movel renovou"


def test_limite_endereco_todo_em_minuscula_nao_e_detectado() -> None:
    """O topônimo em Caixa Alta Inicial é o que separa endereço de figura de linguagem.

    Sem ele, `rua das flores 123` e `estrada de dados: 12 fontes` são a MESMA sequência
    de tokens, e a versão anterior — "logradouro + qualquer coisa + número" — mascarava
    as duas: 35% do briefing legítimo morria. CAIXA ALTA é aceita, que é a forma de
    export de CRM; minúscula integral é o preço, e é falso negativo declarado.
    """
    minuscula = "rua das flores 123"
    assert mascarar_pii(minuscula) == minuscula
    assert mascarar_pii("Rua das Flores 123") == "[ENDERECO]"


def test_limite_idade_e_orgao_emissor_nao_sao_mascarados() -> None:
    """Idade e órgão emissor não identificam sozinhos; mascará-los custaria segmentação
    ("clientes de 38 anos" é público-alvo legítimo) sem ganho de privacidade."""
    assert mascarar_pii("clientes de 38 anos na base") == "clientes de 38 anos na base"
    assert mascarar_pii("orgao emissor SSP/SP") == "orgao emissor SSP/SP"
