"""Sanitizador ÚNICO de PII (§10.2 — emenda C02).

Regra do contrato: **PII nunca entra em prompt de LLM, log ou ledger `invocacao`**.
O UAT #3 adversarial (docs/UAT3-VPS-2026-08-06-adversarial.md) provou o vazamento na
VPS: CPF/telefone/e-mail digitados pelo solicitante chegavam EM CLARO ao prompt e
eram gravados em claro no ledger. Este módulo é o único ponto de verdade do
mascaramento — os serviços o aplicam na FRONTEIRA de entrada do texto livre, e o
texto mascarado é o que segue para prompt, RAG e ledger (nenhum caminho recebe o
original).

Propriedades exigidas (testadas por comportamento — robustez é lei):
- **determinístico e puro**: mesma entrada ⇒ mesma saída, sem I/O, sem estado;
- **preserva o resto do texto**: substitui só o trecho sensível por um marcador
  estável (`[CPF]`, `[EMAIL]`, `[TELEFONE]`...), nunca reescreve o entorno — o
  agente continua entendendo o pedido do usuário;
- **falso positivo é bug**: números de negócio (`480.000` de verba, `847.312` de
  audiência, datas `2026-08-06`, IDs curtos) NÃO são PII. Onde o formato é
  ambíguo o desempate é por CÓDIGO verificável — dígitos verificadores de
  CPF/CNPJ e Luhn de cartão — nunca por chute.

Cobertura ESTRUTURADA (o formato basta): CPF, CNPJ, e-mail, telefone/MSISDN brasileiro
(com e sem DDI +55, com e sem DDD, com e sem 9º dígito), cartão, CEP e RG — cada um com
e sem pontuação.

Cobertura por CONTEXTO (o formato NÃO basta): nome do titular, endereço e data de
nascimento. Ver "O titular IDENTIFICADO" abaixo — e, principalmente, os LIMITES
DECLARADOS, que são parte do contrato deste módulo tanto quanto o que ele detecta.
"""

import re

MARCADOR_CPF = "[CPF]"
MARCADOR_CNPJ = "[CNPJ]"
MARCADOR_EMAIL = "[EMAIL]"
MARCADOR_TELEFONE = "[TELEFONE]"
MARCADOR_CARTAO = "[CARTAO]"
MARCADOR_DOCUMENTO = "[DOCUMENTO]"  # identificador longo não classificável
# Titular IDENTIFICADO (§10.2) — a PII mais comum de uma base de telco na caixa de
# texto livre, e a que este módulo não via até a auditoria da onda 3c.
MARCADOR_NOME = "[NOME]"
MARCADOR_ENDERECO = "[ENDERECO]"
MARCADOR_CEP = "[CEP]"
MARCADOR_DATA_NASCIMENTO = "[DATA_NASCIMENTO]"
MARCADOR_RG = "[RG]"

# ------------------------------------------------------------------ padrões
# `(?<!\d)`/`(?!\d)` evitam casar PEDAÇO de um número maior (um run de 20 dígitos
# não pode ser lido como "um cartão de 19 + sobra").
_EMAIL = r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
_CNPJ_FMT = r"(?<!\d)\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}(?!\d)"
_CPF_FMT = r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)"
# Cartão em grupos de 4 (o agrupamento é o sinal); confirmado por Luhn no dispatch
# — sem isso "2024 2025 2026 2027" viraria cartão (falso positivo inaceitável).
_CARTAO_FMT = r"(?<!\d)\d{4}[ .\-]\d{4}[ .\-]\d{4}[ .\-]\d{3,4}(?!\d)"
# Telefone com DDI explícito: +55 (11) 98765-4321 / +5511987654321
_TEL_DDI = r"(?<!\d)\+\s?55[ .\-]?\(?\d{2}\)?[ .\-]?9?\d{4}[ .\-]?\d{4}(?!\d)"
# Telefone com DDD entre parênteses: (11) 98765 4321
_TEL_PAREN = r"(?<!\d)\(\d{2}\)[ .\-]?9?\d{4}[ .\-]?\d{4}(?!\d)"
# Telefone com hífen no local (4-4): 98765-4321 / 11 98765-4321 / 3456-7890.
# O hífen entre dois grupos de 4 é o que separa telefone de número de negócio —
# datas ("2026-08-06") não casam porque exigem \d{4}-\d{4}. As bordas `[-\w]`
# protegem CÓDIGOS da plataforma: em `OS-2026-0457` o "2026-0457" vem colado a um
# hífen/letra, logo NÃO é telefone (falso positivo pego no unit do C02).
_TEL_HIFEN = r"(?<![-\w])(?:(?:\+?55[ .\-]?)?(?:\(\d{2}\)|\d{2})[ .\-]?)?9?\d{4}-\d{4}(?![-\w])"
# CEP na forma canônica 5-3 (`01310-100`). É estruturado o bastante para dispensar
# âncora: nenhum número de negócio deste domínio tem essa forma (verba usa `480.000`,
# volume usa `847.312`, data usa `01/10`, telefone exige 4-4). As bordas `[-\w]` são as
# mesmas do telefone e protegem código da plataforma (`OS-12345-678` não é CEP).
_CEP_FMT = r"(?<![-\w])\d{5}-\d{3}(?![-\w])"
# RG na forma com pontuação (`12.345.678-9`): 2-3-3 + 1 dígito verificador (ou X/K).
# NÃO colide com CPF (3-3-3 + 2) nem com CNPJ (2-3-3/4-2, que traz `/`), e o
# `(?<![\d.])` impede casar o MIOLO de um CPF. O DV do RG não tem regra nacional
# (cada SSP emite a sua), então aqui não há verificador para desempatar — o que
# desempata é a FORMA, e por isso o RG só é reconhecido pontuado ou com âncora `RG`.
_RG_FMT = r"(?<![\d.])\d{1,2}\.\d{3}\.\d{3}-[\dXxKk](?![\w.])"
# Run de dígitos sem pontuação: classificado por comprimento + verificadores.
_DIGITOS = r"(?<!\d)\d{8,}(?!\d)"

_PADRAO = re.compile(
    "|".join(
        (
            f"(?P<email>{_EMAIL})",
            f"(?P<cnpj_fmt>{_CNPJ_FMT})",
            f"(?P<cpf_fmt>{_CPF_FMT})",
            f"(?P<rg_fmt>{_RG_FMT})",
            f"(?P<cartao_fmt>{_CARTAO_FMT})",
            f"(?P<tel_ddi>{_TEL_DDI})",
            f"(?P<tel_paren>{_TEL_PAREN})",
            f"(?P<cep_fmt>{_CEP_FMT})",
            f"(?P<tel_hifen>{_TEL_HIFEN})",
            f"(?P<digitos>{_DIGITOS})",
        )
    )
)

# --------------------------------------------- o titular IDENTIFICADO (§10.2)
#
# Nome, endereço e data de nascimento NÃO têm forma. Um "detector de nome" por lista de
# nomes próprios é a tentação óbvia e é falso em duas direções ao mesmo tempo: erra o
# nome que não está na lista (falso negativo GARANTIDO numa base de telco real) e come
# palavra comum que também é sobrenome ("Silva" em razão social, "Rua" em endereço).
# Aqui o sinal é o CONTEXTO — como o dado de fato aparece na caixa de texto — e o que o
# contexto não alcança fica DECLARADO no fim deste bloco em vez de prometido.
#
# Consequência de projeto: este bloco roda numa passada PRÓPRIA, antes de `_PADRAO`.
# São duas gramáticas diferentes (uma casa formato, a outra casa frase) e misturá-las
# numa alternação só faria a ordem das alternativas decidir coisas que a leitura não
# revela. A passada de contexto preserva a ÂNCORA e troca só o dado ("mae Joana Silva"
# vira "mae [NOME]"): o agente continua sabendo QUE havia uma filiação no pedido, que é
# o que ele precisa para conversar, sem nunca receber QUEM é.
_MAIUSC = "A-ZÁÀÂÃÄÉÊËÍÎÏÓÔÕÖÚÛÜÇÑ"
_MINUSC = "a-zàáâãäéêëíîïóôõöúûüçñ"
_TOKEN_TITULO = rf"[{_MAIUSC}][{_MINUSC}]+"  # "Maria", "Aparecida"
_TOKEN_CAIXA_ALTA = rf"[{_MAIUSC}]{{2,}}"  # "MARIA" (CRM de telco grita)
_TOKEN_NOME = rf"(?:{_TOKEN_TITULO}|{_TOKEN_CAIXA_ALTA})"
# Conectivos de nome em português: "Maria Aparecida DA Silva", "João E Maria".
_CONECTIVO = r"(?:(?i:d[aeoi]s?|e|del|van|von))"
# Cadeia livre de 1+ token — usada só sob âncora FORTE, onde a palavra anterior já
# garante que o que vem é pessoa.
_NOME_1 = rf"{_TOKEN_NOME}(?:\s+(?:{_CONECTIVO}\s+)?{_TOKEN_NOME})*"
# Cadeia que CONTÉM um conectivo — a exigida sob âncora fraca (ver `_ANCORA_CONTEXTO`).
# O conectivo precisa estar no MEIO: "Maria da Conceição" sim, "Vivo Empresas" não.
_NOME_COM_CONECTIVO = (
    rf"{_TOKEN_NOME}(?:\s+{_TOKEN_NOME})*\s+{_CONECTIVO}\s+"
    rf"{_TOKEN_NOME}(?:\s+(?:{_CONECTIVO}\s+)?{_TOKEN_NOME})*"
)

# ÂNCORA FORTE — a palavra só faz sentido antes de uma PESSOA. Aceita 1 token e aceita
# CAIXA ALTA: "Sra. Oliveira", "titular MARIA SILVA", "mae: Joana".
#
# `nome` SOZINHO ficou de fora de propósito, e é a exclusão mais importante daqui:
# "nome da campanha", "nome da OS", "nome do segmento" são o uso dominante da palavra
# nesta plataforma, e no intake `solicitante.nome` é o COLABORADOR que abriu o pedido —
# mascará-lo apagaria a trilha de quem pediu (§2.3) para proteger um dado que já é
# interno. Só entra qualificado: "nome completo", "nome do cliente/titular/assinante".
_ANCORA_PESSOA = (
    r"(?i:srta\.?|sra\.?|sr\.?|dra\.?|dr\.?|titular(?:es)?|portador(?:a)?|"
    r"m[ãa]e|pai|filia[çc][ãa]o|nome\s+completo|"
    r"nome\s+d[oa]\s+(?:cliente|titular|assinante|contato|respons[áa]vel))"
)
# ÂNCORA FRACA — a palavra vem antes de pessoa MAS também antes de marca, área e
# produto ("cliente Vivo", "clientes Fibra Residencial", "assinantes Banda Larga").
#
# A régua de "2+ tokens em Caixa Alta Inicial" NÃO sustenta esse peso, e a auditoria da
# onda 3c mediu quanto: 16 de 16 frases de negócio deste domínio viravam `[NOME]` —
# `clientes Fibra Residencial`, `Cliente Vivo Empresas`, `usuario Portal Meu Vivo`,
# `assinantes Banda Larga Ultra`, `beneficiario Programa Fidelidade`. Num briefing real
# 35% das linhas SEM PII nenhuma eram destruídas. Esse é o número que desliga o
# controle, e controle desligado protege zero.
#
# O desempate passa a ser ESTRUTURAL, não lexical: sob âncora fraca o nome só é nome se
# a cadeia contiver um CONECTIVO de nome português ("da/de/do/dos/e"). Nome completo de
# base de telco quase sempre traz um ("Maria Aparecida DA Silva", "João DOS Santos");
# nome de produto/segmento quase nunca ("Fibra Residencial", "Vivo Empresas", "Alto
# Valor", "Pré Pago"). É um sinal de FORMA, não uma lista de nomes próprios — não pode
# envelhecer com o catálogo comercial nem com o cartório.
#
# Ganho colateral que importa: com o conectivo obrigatório, CAIXA ALTA fica segura sob
# âncora fraca ("cliente MARIA APARECIDA DA SILVA" é detectado; "cliente PRE PAGO" e
# "cliente ALTO VALOR" não têm conectivo e passam). O CRM de telco grita, e era
# justamente a caixa alta que a régua antiga tinha de recusar.
#
# `falar com|ligar para|contatar|contato|atender` SAÍRAM da âncora fraca. Nesta
# plataforma esses verbos regem ÁREA, não titular ("falar com Marketing", "ligar para
# Suporte Técnico", "contato de teste") — e nomes de área em português carregam
# conectivo ("Central de Relacionamento", "Gestão de Base"), então o conectivo sozinho
# não os protegeria. Quem quiser mascarar o contato tem a âncora forte
# ("nome do contato"). Ver LIMITES.
_ANCORA_CONTEXTO = (
    r"(?i:clientes?|assinantes?|consumidor(?:a)?|usu[áa]ri[oa]s?|benefici[áa]ri[oa]s?|"
    r"contratantes?|pacientes?|falar\s+com|ligar\s+para|contatar|contato|atender)"
)
_SEP = r"[\s:\-–—]{1,3}"

# Qualificadores de SEGMENTO, não lista de nomes — e a diferença é o ponto.
#
# "clientes Alto Valor em churn" é a frase mais comum deste domínio, e a regra de 2+
# tokens a pegava inteira: o briefing perdia o segmento. Uma lista de NOMES PRÓPRIOS
# resolveria pelo lado errado (falso negativo garantido no nome que não está nela);
# esta lista é o inverso — palavras comuns que rotulam base, plano e faixa, e que
# nenhuma delas é prenome brasileiro. Por construção ela só pode causar falso NEGATIVO
# se alguém se chamar "Ouro" ou "Premium", e só reduz falso positivo.
#
# É incompleta de propósito e para sempre: "clientes Faixa Diamante" continua virando
# `[NOME]`. Guarda apenas o primeiro token porque é ele que decide o resto da cadeia.
_NAO_SEGMENTO = (
    r"(?!(?i:alt[oa]|baix[oa]|m[ée]di[oa]|nov[oa]|antig[oa]|grande|pequen[oa]|"
    r"primeir[oa]|[úu]ltim[oa]|total|base|plano|perfil|p[úu]blico|segmento|faixa|"
    r"ticket|churn|renda|ouro|prata|bronze|premium|black|gold|silver|top|vip|"
    r"pr[ée]|p[óo]s|tod[oa]s|ativ[oa]s|inativ[oa]s|"
    # Qualificadores que seguem âncora FORTE em texto de contrato/cadastro, não pessoa:
    # "titular único por conta", "titular pessoa jurídica", "portador residencial".
    r"[úu]nic[oa]|principal|secund[áa]ri[oa]|pessoa|jur[íi]dic[oa]|f[íi]sic[oa]|"
    r"empresaria(?:l|is)|residencia(?:l|is)|corporativ[oa]|comercia(?:l|is)|"
    r"deficientes?|portador(?:a|es)?|idos[oa]s?|men(?:or|ores)|"
    # Substantivos de ORGANIZAÇÃO. Entram porque a exigência de conectivo (única coisa
    # que separa "Maria da Silva" de "Fibra Residencial") não separa nome de pessoa de
    # nome de ÁREA: em português a área também leva conectivo — "Central de
    # Relacionamento", "Gestão de Base", "Diretoria de Marketing". Medido: eram 6 dos 6
    # falsos positivos que sobravam. Bloquear a CABEÇA da locução resolve os seis, e a
    # lista só pode causar falso negativo se alguém se chamar "Gerência".
    r"centra(?:l|is)|gest[ãa]o|diretoria|ger[êe]ncia|coordena[çc][ãa]o|supervis[ãa]o|"
    r"superintend[êe]ncia|departamento|setor|[áa]rea|n[úu]cleo|c[ée]lula|comit[êe]|"
    r"conselho|carteira|time|equipe|squad|portal|programa|plataforma|produto|projeto|"
    r"campanha|canal|unidade|filial|matriz|secretaria|ouvidoria|central)\b)"
)

# ENDEREÇO — logradouro + NOME PRÓPRIO do logradouro + número.
#
# Duas correções da auditoria da onda 3c, e as duas eram mensuráveis:
#
# (1) As abreviações estavam na lista mas eram ALTERNATIVAS MORTAS. O padrão antigo era
#     `\b(?:rua|...|av\.|trav\.|rod\.)\b\.?`: o `\b` FINAL exige limite de palavra, e
#     depois do ponto de `av\.` vem espaço — ponto e espaço são ambos não-palavra, logo
#     não há limite ali e a alternativa NUNCA casava. Resultado medido: `Av. Paulista
#     1000`, `R. Augusta 1200`, `Al. Santos 45`, `Rod. Raposo Tavares 12000` e
#     `Av. das Nações Unidas, 14401` saíam TODOS em claro — e "Av." é a segunda forma
#     mais comum de endereço brasileiro. O teste do autor só usava "Rua" por extenso.
#     Agora extenso e abreviado são ramos separados, cada um com a sua borda.
#
# (2) "qualquer coisa + número" comia figura de linguagem. O comentário antigo dizia que
#     o número separava endereço de "a estrada da campanha" — mas todo texto de
#     marketing traz um ano ou uma contagem: `Avenida de crescimento 2026`,
#     `Estrada de dados: 12 fontes`, `Largo prazo de 12 meses`, `Alameda de parceiros
#     com 15 marcas` viravam `[ENDERECO]` inteiros. O que de fato separa é o NOME
#     PRÓPRIO: endereço é logradouro + topônimo (Caixa Alta Inicial ou CAIXA ALTA),
#     opcionalmente com conectivo e abreviação de patente/título ("Av. Brig. Faria Lima
#     3477"). Figura de linguagem tem substantivo comum minúsculo no lugar do topônimo.
#
# O número segue obrigatório (separa endereço de bairro solto) e o complemento
# (apto/bloco/casa) entra junto quando vem colado, senão "apto 42" sobraria em claro
# logo depois do marcador.
_LOGRADOURO_EXTENSO = (
    r"(?:rua|avenida|alameda|travessa|pra[çc]a|rodovia|estrada|largo|viela|quadra)\b\.?"
)
# Abreviações: exigem o PONTO, que é o que as torna endereço e não palavra solta. `\b`
# à esquerda impede colher o fim de outra palavra ("Sr." e "Dr." não viram `r.`).
# `av` é a única aceita SEM ponto ("Av Paulista 1000" é escrita corrente); as demais
# exigem o ponto porque `r`/`al` sem ponto são palavra e preposição.
_LOGRADOURO_ABREV = r"(?:av|r|al|trav|rod|pra[çc]|pca|p[çc])\.|av\b"
_LOGRADOURO = rf"(?i:\b(?:{_LOGRADOURO_EXTENSO}|{_LOGRADOURO_ABREV}))"
# Abreviação de título dentro do nome do logradouro: "Brig.", "Cel.", "Pres.", "Sen.".
_TOKEN_ABREV = rf"[{_MAIUSC}][{_MINUSC}]{{1,4}}\."
_TOKEN_LOGRADOURO = (
    rf"(?:{_CONECTIVO}|{_TOKEN_ABREV}|{_TOKEN_TITULO}|{_TOKEN_CAIXA_ALTA}|\d{{1,3}}[ºªo]?)"
)
# Termina OBRIGATORIAMENTE em token próprio: é isso que barra "de crescimento 2026".
_NOME_LOGRADOURO = rf"(?:{_TOKEN_LOGRADOURO}\s+){{0,4}}(?:{_TOKEN_TITULO}|{_TOKEN_CAIXA_ALTA})"
_ENDERECO = (
    rf"{_LOGRADOURO}\s*{_NOME_LOGRADOURO}(?:,\s*|\s+)(?:n[º°.]?\s*)?\d{{1,6}}\b"
    r"(?:\s*,?\s*(?i:apto?|apartamento|ap\.|bloco|bl\.|casa|sala|cj\.?|conjunto|torre|fundos)"
    r"\s*\.?\s*\d{1,5}\b)?"
)

# DATA DE NASCIMENTO — a data em si NUNCA é mascarada sozinha: "01/10 a 15/10" é janela
# de campanha e "2026-08-06" é data de publicação (há aceite provando que passam
# intactas). O que torna a data um dado do titular é a âncora de nascimento, e só ela.
_DATA = (
    r"(?:\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}\s+de\s+[A-Za-zÀ-ÿ]+\s+de\s+\d{4})"
)
_ANCORA_NASCIMENTO = (
    r"(?i:nascid[oa]s?\s+em|data\s+de\s+nascimento|dt\.?\s*nasc\.?|nascimento|nasc\.)"
)

# CEP e RG ancorados: cobrem a forma SEM pontuação, que o `_PADRAO` não pode reconhecer
# sozinho (`01310100` é indistinguível de uma contagem; `123456789` de um ID).
#
# As duas âncoras aceitam `nº`/`n.` entre rótulo e dado ("CEP n 01310100") e o RG aceita
# o prefixo de UF que metade dos estados imprime ("RG MG-12.345.678", "RG M 1234567") —
# formas medidas na auditoria da onda 3c, todas saindo em claro antes disto.
_CEP_ANCORADO = (
    r"(?i:\bcep)\s*(?:n[º°.]{0,2})?\s*:?\s*(?P<cep_ancorado>\d{2}\.?\d{3}-?\d{3})(?![-\w])"
)
_RG_ANCORADO = (
    r"(?i:\brg)\s*(?:n[º°.]{0,2})?\s*:?\s*(?:[A-Za-z]{1,2}[-\s])?"
    r"(?P<rg_ancorado>\d{1,2}(?:\.\d{3}){2}-?[\dXxKk]?|\d{7,10}-?[\dXxKk]?)(?![\w])"
)

_CONTEXTO = re.compile(
    "|".join(
        (
            rf"\b{_ANCORA_PESSOA}{_SEP}{_NAO_SEGMENTO}(?P<nome_forte>{_NOME_1})",
            rf"\b{_ANCORA_CONTEXTO}{_SEP}{_NAO_SEGMENTO}(?P<nome_fraco>{_NOME_COM_CONECTIVO})",
            rf"(?P<endereco>{_ENDERECO})",
            _CEP_ANCORADO,
            _RG_ANCORADO,
            rf"{_ANCORA_NASCIMENTO}\s*:?\s*(?P<data_nascimento>{_DATA})",
        )
    )
)

_MARCADOR_DO_GRUPO: dict[str, str] = {
    "nome_forte": MARCADOR_NOME,
    "nome_fraco": MARCADOR_NOME,
    "endereco": MARCADOR_ENDERECO,
    "cep_ancorado": MARCADOR_CEP,
    "rg_ancorado": MARCADOR_RG,
    "data_nascimento": MARCADOR_DATA_NASCIMENTO,
}

# ------------------------------------------------------------ LIMITES DECLARADOS
# O §1.3.5 vale para o próprio detector: um sanitizador que promete "nome" e acerta
# metade é PIOR que um que declara onde para, porque o DPO publica `nome: bloquear`
# acreditando ter fechado a porta. O que este módulo NÃO detecta, hoje:
#
# 1. NOME SEM ÂNCORA. "Maria Aparecida da Silva Santos" solto numa frase sai intacto.
#    Não há como distinguir de "Vale do Silício" ou "Torre Móvel Brasil" sem semântica.
# 2. NOME SEM CONECTIVO após âncora fraca ("cliente Joana Silva", "cliente João"). É o
#    preço do desempate estrutural de `_ANCORA_CONTEXTO`, e é o limite mais caro da
#    lista. Continuam cobertos: a âncora FORTE ("titular Joana Silva", "Sra. Joana",
#    "nome do cliente: Joana Silva"), a chave de formulário (`{"titular": "Joana
#    Silva"}`) e qualquer nome ao lado de CPF/telefone/e-mail, que saem por FORMA.
# 3. ÁREA/RAZÃO SOCIAL COM CONECTIVO cuja cabeça não está em `_NAO_SEGMENTO`
#    ("falar com Casa de Carnes", "cliente Torre de Controle") vira `[NOME]`. Falso
#    positivo aceito na direção segura: apaga um termo de negócio, não vaza titular.
#    A lista corta as cabeças de locução frequentes ("Central de...", "Gestão de...",
#    "Diretoria de..."), nunca o caso geral — e é lista de palavras COMUNS, então só
#    pode falhar por baixo se alguém se chamar "Gerência".
# 5. BAIRRO/CIDADE/UF soltos ("Vila Mariana, São Paulo/SP") e ENDEREÇO SEM NÚMERO
#    ("Rua das Flores, próximo ao mercado") saem intactos.
# 6. ENDEREÇO TODO EM MINÚSCULA ("rua das flores 123") sai intacto: o topônimo em Caixa
#    Alta Inicial é o que separa endereço de figura de linguagem ("estrada de dados:
#    12 fontes"), e sem ele os dois são a mesma sequência de tokens. CAIXA ALTA é aceita
#    ("AV. PAULISTA 1000"), que é a forma de export de CRM.
# 7. IDADE ("cliente de 38 anos") e DATA sem âncora de nascimento saem intactas —
#    inclusive sinônimos que não são de nascimento ("aniversário 14/03/1987"), porque
#    "aniversário" é palavra de campanha neste domínio.
# 8. CHAVE EM camelCase (`{"nomeDoTitular": ...}`) não ancora: a normalização de chave
#    troca `_` e `-` por espaço, não fronteira de caixa. Chave em ordem invertida
#    (`titular_nome`) idem.
# 9. ÓRGÃO EMISSOR ("SSP/SP") e NACIONALIDADE não são mascarados — não identificam.
# 10. `mascarar_estrutura` (payload de evento, trace) NÃO usa a chave como âncora, por
#    contrato: ali a chave é nome de campo do §4.1. Só `mascarar_campos` /
#    `mascarar_pii_em_campo` ancoram pela chave. Estrutura ANINHADA dentro de um valor
#    de `mascarar_campos` perde a âncora ao descer.
#
# Cada item acima é buraco conhecido, não descuido. Fechá-los exige sinal que regex não
# tem; enquanto não houver, a política do DPO precisa ser lida com esta lista ao lado
# (ver a EMENDA SUGERIDA sobre expor os limites na tela de IA Responsável).

# DDD brasileiro: 11-19, 21-29, ..., 91-99 (nenhum termina em 0)
_DDD = re.compile(r"(?:1[1-9]|[2-9][1-9])$")
_MOVEL_COM_DDD = re.compile(r"(?:1[1-9]|[2-9][1-9])9\d{8}$")  # DDD + 9º dígito + 8


def _so_digitos(texto: str) -> str:
    return "".join(c for c in texto if c.isdigit())


def _cpf_valido(digitos: str) -> bool:
    """Dígitos verificadores do CPF (mod 11) — desempata CPF × celular (ambos 11)."""
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(digitos[i]) * (tamanho + 1 - i) for i in range(tamanho))
        esperado = (soma * 10 % 11) % 10
        if esperado != int(digitos[tamanho]):
            return False
    return True


_PESOS_CNPJ = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def _cnpj_valido(digitos: str) -> bool:
    """Dígitos verificadores do CNPJ (mod 11)."""
    if len(digitos) != 14 or len(set(digitos)) == 1:
        return False
    for tamanho in (12, 13):
        pesos = _PESOS_CNPJ[13 - tamanho :]
        soma = sum(int(digitos[i]) * pesos[i] for i in range(tamanho))
        resto = soma % 11
        esperado = 0 if resto < 2 else 11 - resto
        if esperado != int(digitos[tamanho]):
            return False
    return True


def _luhn_valido(digitos: str) -> bool:
    """Luhn (mod 10) — confirma cartão antes de mascarar sequências agrupadas."""
    soma = 0
    for indice, char in enumerate(reversed(digitos)):
        valor = int(char)
        if indice % 2 == 1:
            valor *= 2
            if valor > 9:
                valor -= 9
        soma += valor
    return soma % 10 == 0


def _classificar_run(digitos: str) -> str | None:
    """Marcador para um run de dígitos SEM pontuação; None = não é PII (mantém o
    texto intacto). Ordem: verificadores primeiro, formato depois."""
    tamanho = len(digitos)
    if tamanho == 11:  # CPF e celular com DDD têm o MESMO tamanho: DV desempata
        if _cpf_valido(digitos):
            return MARCADOR_CPF
        if _MOVEL_COM_DDD.match(digitos):
            return MARCADOR_TELEFONE
        return MARCADOR_CPF  # 11 dígitos é forma de CPF: mascara mesmo com DV ruim
    if tamanho == 14:
        if _cnpj_valido(digitos):
            return MARCADOR_CNPJ
        return MARCADOR_CARTAO if _luhn_valido(digitos) else MARCADOR_DOCUMENTO
    if tamanho == 10 and _DDD.match(digitos[:2]):  # fixo com DDD
        return MARCADOR_TELEFONE
    if tamanho == 9 and digitos[0] == "9":  # celular sem DDD (9º dígito)
        return MARCADOR_TELEFONE
    if tamanho in (12, 13) and digitos.startswith("55") and _DDD.match(digitos[2:4]):
        return MARCADOR_TELEFONE  # MSISDN com DDI: 55 + DDD + fixo/celular
    if 13 <= tamanho <= 19 and _luhn_valido(digitos):
        return MARCADOR_CARTAO
    if tamanho >= 11:
        return MARCADOR_DOCUMENTO  # identificador longo: nunca em claro (§10.2)
    # 8 dígitos crus são ambíguos demais (datas `20260806`, contagens, IDs de
    # sistema): mascarar aqui seria falso positivo — telefone de 8 dígitos só é
    # reconhecido quando vem formatado (`3456-7890`).
    return None


def _substituir(casamento: re.Match[str]) -> str:
    grupo = casamento.lastgroup
    original = casamento.group(0)
    if grupo == "email":
        return MARCADOR_EMAIL
    if grupo == "cnpj_fmt":
        return MARCADOR_CNPJ
    if grupo == "cpf_fmt":
        return MARCADOR_CPF
    if grupo == "rg_fmt":
        return MARCADOR_RG
    if grupo == "cep_fmt":
        return MARCADOR_CEP
    if grupo == "cartao_fmt":
        # Sem Luhn não é cartão: preserva o texto (verba "2024 2025 2026 2027").
        return MARCADOR_CARTAO if _luhn_valido(_so_digitos(original)) else original
    if grupo in ("tel_ddi", "tel_paren", "tel_hifen"):
        return MARCADOR_TELEFONE
    marcador = _classificar_run(original)
    return marcador if marcador is not None else original


def _substituir_contexto(casamento: re.Match[str]) -> str:
    """Troca só o DADO, preservando a âncora que o antecede.

    Todo grupo interno da passada de contexto é `(?:...)` (não-capturante) de propósito:
    assim `lastgroup` é sempre o único grupo NOMEADO da alternativa que casou, que é
    exatamente o trecho a substituir. O prefixo devolvido é o texto original entre o
    início do casamento e o início desse grupo — a âncora, letra por letra.
    """
    grupo = casamento.lastgroup
    if grupo is None:  # pragma: no cover - toda alternativa tem grupo nomeado
        return casamento.group(0)
    inicio = casamento.start(grupo) - casamento.start(0)
    return casamento.group(0)[:inicio] + _MARCADOR_DO_GRUPO[grupo]


def mascarar_pii(texto: str) -> str:
    """Substitui PII por marcadores estáveis, PRESERVANDO o resto do texto (§10.2).

    Único ponto de mascaramento da plataforma: aplicado ANTES de montar qualquer
    prompt de LLM/embedding e ANTES de gravar `input` no ledger `invocacao`.

    Duas passadas, nesta ordem: CONTEXTO (nome/endereço/nascimento/CEP e RG ancorados)
    e depois FORMATO (CPF/CNPJ/e-mail/telefone/cartão/CEP e RG pontuados). O contexto
    vem primeiro porque ele consome trechos MAIORES — "Rua das Flores 12345678" é um
    endereço inteiro, não um logradouro seguido de um run de dígitos.
    """
    if not texto:
        return texto
    return _PADRAO.sub(_substituir, _CONTEXTO.sub(_substituir_contexto, texto))


_SUFIXO_DE_CHAVE = re.compile(r"[\s]+(?i:ids?|c[óo]d(?:igo)?s?)$")


def _ancora_da_chave(chave: str) -> str:
    """Chave de formulário/JSON reescrita na forma que as âncoras de contexto leem."""
    return _SUFIXO_DE_CHAVE.sub("", chave.replace("_", " ").replace("-", " "))


def mascarar_pii_em_campo(chave: str, valor: str) -> str:
    """`mascarar_pii` no VALOR usando a CHAVE do campo como âncora de contexto (§10.2).

    Existe porque a âncora e o dado se separam quando o texto é um formulário. Na frase
    ("mae Joana Silva") a âncora está na mesma string; num briefing digitado
    (`{"mae": "Joana Silva"}`) a chave fica de um lado e o nome do outro, e mascarar
    cada string isolada perde justamente o sinal que torna o nome reconhecível. É a
    forma REAL do dado de telco: campo `nome do titular`, campo `cep`, campo `rg`.

    Implementação: casa sobre `"{chave}: {valor}"` e só aceita substituição cujo DADO
    comece dentro da região do valor — o casamento pode COMEÇAR na chave (é o ponto),
    mas nada da chave é reescrito aqui. Quem mascara a chave é o chamador, com
    `mascarar_pii`, porque chave também é digitação (achado 9 do UAT #5).

    A chave é NORMALIZADA antes de virar âncora: `_` e `-` viram espaço, e um sufixo
    `id`/`ids`/`cod` final é descartado. Sem isso a forma dominante de chave de JSON
    ficava de fora — `nome_do_titular`, `nome_completo` e `nome_titular` saíam em claro
    (medido na onda 3c), porque as âncoras pedem `\\s` entre as palavras e `_` é
    caractere de PALAVRA: em `nome_do_titular` nem `\\btitular` existe. O sufixo `_id`
    entra pelo mesmo motivo: `cliente_id`/`titular_id` é como um CRM nomeia a coluna, e
    o que o analista cola ali nem sempre é um id (medido: `"cliente_id": "Maria da
    Conceição dos Santos - 111.444.777-35"`). Descartá-lo não cria falso positivo — um
    id de verdade não tem forma de nome e continua intacto.
    """
    if not valor:
        return valor
    prefixo = f"{_ancora_da_chave(chave)}: "
    corte = len(prefixo)

    def _apenas_no_valor(casamento: re.Match[str]) -> str:
        grupo = casamento.lastgroup
        if grupo is None or casamento.start(grupo) < corte:
            return casamento.group(0)
        return _substituir_contexto(casamento)

    combinado = _CONTEXTO.sub(_apenas_no_valor, prefixo + valor)
    return _PADRAO.sub(_substituir, combinado[corte:])


def contem_pii(texto: str) -> bool:
    """True se `mascarar_pii` alteraria o texto — detecção e mascaramento usam
    exatamente a MESMA regra (não podem divergir)."""
    return bool(texto) and mascarar_pii(texto) != texto
