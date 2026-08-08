"""Conteúdo da política de IA Responsável — conjunto FECHADO de campos + validação.

Mesma doutrina do M12 (`domain/governanca/politicas.py`): conteúdo versionado, campos
fechados, erros ACUMULADOS (padrão do parser §7.1). E a MESMA correção que o achado 8
do UAT #5 obrigou: `POLITICA_IA_SEED` é SEMENTE e FALLBACK, **nunca fonte da verdade em
runtime** — quem governa é a linha publicada lida por porta e injetada no serviço.
Importar esta constante dentro de `application/services/` é o bug que o achado 8
descreve; o guarda-corpo de CI (`test_nenhum_servico_importa_a_seed_direto`, em
`tests/unit/test_F03_ia_responsavel.py`) falha se isso voltar a acontecer.

## Por que o conjunto é FECHADO (e por que isso é o antídoto do achado 8)

`validar_conteudo` REJEITA campo desconhecido. Isso não é purismo de schema: é o que
impede alguém de publicar um parâmetro bonito e inerte. `teto_tokens` segue de fora:
a MEDIÇÃO chegou na onda 5 (I04 — `invocacao.tokens` recebe o usage do provedor), mas
o ENFORCEMENT ainda não existe (nenhum portão soma o gasto e recusa chamada); aceitá-lo
criaria exatamente a tela que promete governar e não governa. **Campo novo entra junto
com o teste de enforcement que prova que ele muda comportamento, nunca antes.**

## Defaults conservadores (§10.2)

O default v1 reproduz EXATAMENTE o comportamento de hoje — mascarar tudo, propor nada
automaticamente, reter pelo mesmo prazo do M12, perfis iguais ao roster §7.2. Isso é
deliberado: publicar a v1 não pode mudar o comportamento de nenhuma OS em voo. A
política nasce igual ao presente e só aperta a partir daí, por ato humano versionado.
"""

from typing import Any, NamedTuple

# ------------------------------------------------------------------ vocabulários
# Categorias = marcadores de `domain/privacidade/mascarar.py` (fonte única §10.2).
# Não há categoria "outros": o que o mascarador não classifica não é PII para a
# plataforma, e inventar uma categoria aqui criaria regra sem detector.
#
# ## Por que o conjunto CRESCEU (onda 3c) e por que isso é delicado
#
# A auditoria mediu que o detector via apenas run de dígito e e-mail: titular
# IDENTIFICADO — nome + endereço + data de nascimento — saía INTACTO para o hub, para a
# coluna `input` do ledger, para o índice `agente_evidence` (de onde REAPARECE como
# precedente de outro usuário) e para o Langfuse. Numa base de telco esse é o dado mais
# comum da caixa de texto. Pior que o buraco no detector era o buraco no VOCABULÁRIO: o
# DPO não conseguia publicar `nome: bloquear` nem que quisesse, porque a categoria não
# existia. A tela prometia governar uma privacidade que ela não sabia nomear.
CATEGORIAS_PII_V1: tuple[str, ...] = ("cpf", "cnpj", "email", "telefone", "cartao", "documento")

# Titular identificado — categorias novas, com detector novo em `mascarar.py`. Mesma
# régua do resto deste arquivo: entram porque MUDAM comportamento (`nome: bloquear`
# interrompe a chamada), não porque enfeitam a tela.
CATEGORIAS_PII_TITULAR: tuple[str, ...] = ("nome", "endereco", "cep", "data_nascimento", "rg")

CATEGORIAS_PII: tuple[str, ...] = CATEGORIAS_PII_V1 + CATEGORIAS_PII_TITULAR

# ## Compatibilidade retroativa — a parte que exige cuidado
#
# `_erros_dados_llm` exige ação DECLARADA para cada categoria ("omitir é deixar buraco
# mudo"). Somar categoria a um conjunto fechado com essa regra invalidaria, de um
# deploy para o outro, TODA política já publicada: a v1 de um tenant traz seis ações e
# passaria a acusar cinco erros. O efeito prático seria péssimo e silencioso — a tela do
# DPO abriria o conteúdo vigente, o formulário nasceria em estado inválido e a única
# saída seria republicar; e enquanto isso a linha antiga continua governando, porque
# validação é ato de PUBLICAÇÃO, não de leitura.
#
# Por isso a obrigatoriedade fica congelada no conjunto V1, e as categorias novas são
# OPCIONAIS na declaração. Isso é seguro porque omissão não vira permissão: `_acoes`
# (`dados.py`) devolve `mascarar` para o que a política não disser, e o detector novo
# roda de qualquer jeito. O que a política antiga perde ao omitir é só o direito de
# APERTAR — nunca o piso do C02.
#
# O default de fábrica (`politica_ia_seed`) declara TODAS as categorias, então quem
# publicar dali para frente sai com o conjunto completo. Tornar as novas obrigatórias
# exigiria uma migração que reescrevesse as linhas já publicadas, e reescrever política
# publicada é adulterar prova de auditoria — não se faz por conveniência de schema.
CATEGORIAS_PII_OBRIGATORIAS: tuple[str, ...] = CATEGORIAS_PII_V1

# ------------------------------------------------- natureza da detecção e LIMITES (F04)
#
# ## Por que isto existe: o achado 8 na granularidade da CONFIANÇA do detector
#
# A onda 3c provou que `mascarar.py` detecta por DUAS naturezas diferentes, e a tela do
# DPO mostrava as onze categorias na MESMA linha, com o mesmo seletor, como se todas
# fechassem a porta do mesmo jeito:
#
# * por FORMA — `cpf`, `cnpj`, `email`, `telefone`, `cartao`, `documento`, `cep`, `rg`.
#   O formato basta, e onde é ambíguo há CÓDIGO verificável (DV de CPF/CNPJ, Luhn de
#   cartão). Cobertura previsível: o que tem a forma é pego, sempre.
# * por CONTEXTO — `nome`, `endereco`, `data_nascimento`. Não têm forma; o sinal é como
#   o dado aparece escrito. Cobertura PARCIAL, com buracos que `mascarar.py` já
#   NOMEAVA num comentário ("LIMITES DECLARADOS") que nenhum DPO jamais leu.
#
# `nome: bloquear` numa tela sem essa distinção é o achado 8 outra vez, um nível mais
# fundo: o parâmetro MUDA comportamento (o teste de enforcement prova), mas o DPO assina
# acreditando em uma cobertura que não existe. Parametrização honesta no efeito e
# desonesta na CONFIANÇA continua sendo teatro auditável — só que mais caro, porque
# agora tem assinatura.
#
# ## Por que os limites moram no DOMÍNIO e não na tela
#
# Buraco de detector muda quando o detector muda. Escrito no React, o texto envelhece na
# primeira mexida em `mascarar.py` e a tela passa a mentir na direção contrária (avisa de
# um buraco que já foi fechado, ou cala sobre um novo). Aqui, cada limite viaja com um
# `exemplo` EXECUTÁVEL, e o teste da frente F04
# (`tests/unit/test_F04_natureza_e_limites.py`) roda o detector sobre ele:
#
# * o `exemplo` de um limite tem de sair INTACTO — se alguém fechar o buraco, o teste
#   quebra e obriga a APAGAR o aviso da tela (limite fechado que continua sendo exibido é
#   mentira na direção oposta);
# * o `detecta` de cada categoria tem de sair MASCARADO — se alguém quebrar a detecção,
#   o teste quebra antes de a tela prometer o que o detector não faz mais.
#
# É a mesma régua do resto deste arquivo: nada entra na tela do DPO sem um teste que
# prove que o que está escrito ali é o que acontece.
NATUREZA_FORMA = "forma"
NATUREZA_CONTEXTO = "contexto"
NATUREZAS: tuple[str, ...] = (NATUREZA_FORMA, NATUREZA_CONTEXTO)


class LimiteDeteccao(NamedTuple):
    """Um buraco CONHECIDO do detector, em português do DPO + prova executável.

    `texto` é o que o DPO lê ao lado do seletor da categoria — frase no presente do
    indicativo, dizendo o que NÃO acontece. `exemplo` é o trecho que sai em claro hoje;
    o teste o executa contra `mascarar_pii`. `chave` só é preenchida quando o buraco é
    de CHAVE de formulário: aí o exemplo é o VALOR e o teste usa
    `mascarar_pii_em_campo(chave, exemplo)`, que é o caminho real do dado.
    """

    texto: str
    exemplo: str
    chave: str = ""


class Deteccao(NamedTuple):
    """Como uma categoria é detectada — e até onde.

    `detecta` é um exemplo que HOJE é mascarado (a ponta boa da pinça; sem ele, "por
    forma" seria só um rótulo). `limites` é o que NÃO é pego. Categoria de contexto sem
    limite declarado é recusada pelo teste da F04: contexto tem buraco por construção, e
    declarar zero seria a promessa que este bloco existe para desfazer.
    """

    natureza: str
    detecta: str
    limites: tuple[LimiteDeteccao, ...] = ()


# Os exemplos são SINTÉTICOS e é o que se espera deles: `111.444.777-35` e
# `4111 1111 1111 1111` são os valores de teste canônicos (o primeiro é o CPF de exemplo
# que já circula pelos testes do C02; o segundo é o cartão de teste público da bandeira),
# e os nomes/endereços são inventados. Exemplo na tela do DPO nunca pode ser dado real.
DETECCAO_DA_CATEGORIA: dict[str, Deteccao] = {
    "cpf": Deteccao(NATUREZA_FORMA, "CPF 111.444.777-35"),
    "cnpj": Deteccao(NATUREZA_FORMA, "CNPJ 11.222.333/0001-81"),
    "email": Deteccao(NATUREZA_FORMA, "contato joana.silva@exemplo.com.br"),
    "telefone": Deteccao(
        NATUREZA_FORMA,
        "(11) 98765-4321",
        (
            LimiteDeteccao(
                "Telefone de 8 dígitos SEM hífen e sem DDD não é detectado — cru, "
                "“34567890” é indistinguível de uma contagem ou de um código interno. "
                "Com hífen (“3456-7890”) ou com DDD, é.",
                "telefone 34567890 na ficha",
            ),
        ),
    ),
    "cartao": Deteccao(NATUREZA_FORMA, "4111 1111 1111 1111"),
    "documento": Deteccao(NATUREZA_FORMA, "protocolo 123456789012"),
    "nome": Deteccao(
        NATUREZA_CONTEXTO,
        "cliente Maria da Silva",
        (
            LimiteDeteccao(
                "Nome SOLTO na frase, sem palavra que anuncie pessoa antes dele, NÃO é "
                "detectado. Sem essa âncora não há como separar o nome de um titular do "
                "nome de uma marca, de um bairro ou de um produto.",
                "Maria Aparecida da Silva Santos aprovou o roteiro",
            ),
            LimiteDeteccao(
                "Depois de “cliente”, “assinante”, “usuário”, “falar com” ou “contato”, "
                "só é detectado o nome que traz uma partícula (“da”, “de”, “dos”, “e”): "
                "“cliente Maria DA Silva” é pego, “cliente Joana Silva” NÃO é. A "
                "exigência existe porque sem ela “clientes Fibra Residencial” e "
                "“Cliente Vivo Empresas” viravam nome de pessoa. Continuam cobertos "
                "“titular”, “Sr./Sra.”, “mãe”, “nome completo” e “nome do cliente”, que "
                "só antecedem pessoa.",
                "cliente Joana Silva pediu portabilidade",
            ),
            LimiteDeteccao(
                "Em formulário e JSON, a CHAVE só ancora quando as palavras vêm "
                "separadas por espaço, “_” ou “-” (“nome do titular”, “nome_completo”). "
                "Chave em camelCase (“nomeDoTitular”) ou em ordem invertida "
                "(“titular_nome”) NÃO ancora, e o valor sai em claro.",
                "Maria da Conceição dos Santos",
                chave="nomeDoTitular",
            ),
        ),
    ),
    "endereco": Deteccao(
        NATUREZA_CONTEXTO,
        "Av. Paulista 1000",
        (
            LimiteDeteccao(
                "Endereço TODO EM MINÚSCULA não é detectado. O nome do logradouro em "
                "maiúscula inicial (ou em CAIXA ALTA, como sai do CRM) é o que separa "
                "endereço de figura de linguagem — “estrada de dados: 12 fontes” não "
                "pode virar endereço.",
                "rua das flores 123",
            ),
            LimiteDeteccao(
                "Endereço SEM NÚMERO não é detectado: o número é o que separa endereço "
                "de referência solta.",
                "Rua das Flores, próximo ao mercado",
            ),
            LimiteDeteccao(
                "Bairro, cidade e UF sozinhos, sem logradouro e sem número, não são detectados.",
                "Vila Mariana, São Paulo/SP",
            ),
        ),
    ),
    "cep": Deteccao(
        NATUREZA_FORMA,
        "CEP 01310-100",
        (
            LimiteDeteccao(
                "CEP SEM hífen só é detectado quando a palavra “CEP” aparece antes "
                "(“CEP 01310100”). Solto, “01310100” é oito dígitos como qualquer "
                "contagem. Com hífen (“01310-100”), é detectado sempre.",
                "entrega em 01310100",
            ),
        ),
    ),
    "data_nascimento": Deteccao(
        NATUREZA_CONTEXTO,
        "data de nascimento 14/03/1987",
        (
            LimiteDeteccao(
                "Data só vira dado do titular quando vem depois de “nascimento”, "
                "“nascido em”, “dt. nasc.”. Depois de “aniversário” NÃO — nesta "
                "plataforma aniversário é palavra de campanha, e mascarar toda data "
                "apagaria janela de campanha e data de publicação.",
                "aniversário 14/03/1987",
            ),
            LimiteDeteccao(
                "IDADE não é detectada: “cliente de 38 anos” sai em claro. Idade não "
                "tem forma de data e, sozinha, não identifica ninguém.",
                "cliente de 38 anos",
            ),
        ),
    ),
    "rg": Deteccao(
        NATUREZA_FORMA,
        "RG 12.345.678-9",
        (
            LimiteDeteccao(
                "RG SEM pontuação só é detectado quando a palavra “RG” aparece antes "
                "(“RG 123456789”). Solto, “123456789” é indistinguível de um id de "
                "sistema — e o RG não tem dígito verificador nacional para desempatar. "
                "Pontuado (“12.345.678-9”), é detectado sempre.",
                "documento 123456789 na ficha",
            ),
        ),
    ),
}

# `permitir` NÃO existe de propósito. O piso do C02 (mascarar sempre) é garantia de
# contrato, não default configurável: uma política capaz de DESLIGAR o mascaramento
# transformaria a tela de IA Responsável no maior vetor de vazamento da plataforma.
# A política só APERTA — mascarar (piso de hoje) ou bloquear (impede a chamada).
ACOES_DADO: tuple[str, ...] = ("mascarar", "bloquear")

# Ações via_ai automatizáveis (LGPD Art. 20). Vocabulário FECHADO e ancorado nos
# serviços que hoje escrevem no ledger `invocacao` — cada entrada corresponde a um
# span real. Fechado porque um typo na allowlist ("jornada.ajusta") passaria batido e
# o DPO acharia que autorizou algo que segue bloqueado — falha silenciosa na direção
# errada da auditoria.
ACOES_VIA_AI: tuple[str, ...] = (
    "consultor.preencher_briefing",  # §8-M3 · consultor_service
    "audiencia.montar_sql",  # §8-M5 · audiencia_service (engineer)
    "criativo.gerar",  # §8-M6 · criativo_service
    "jornada.ajustar",  # §8-M7 · jornada_service (flow) — o "propõe, humano aplica"
    "insight.responder",  # §8-M10 · insight_service
    "otimizacao.propor",  # §8-M11 · otimizacao_service (optimize)
    "ajuda.responder",  # §8-M-Guia · ajuda_service
)

# Perfis do §3 (roteamento 120b|20b). `PerfilModelo` vive em `application/ports/llm.py`;
# domínio não importa de application (§2.1) — a tupla é a mesma por contrato.
PERFIS_MODELO: tuple[str, ...] = ("120b", "20b")

# Roster §7.2: perfil declarado por agente. É o default de `modelos_permitidos` —
# a política nasce PINANDO o roster, não abrindo tudo.
PERFIL_DO_ROSTER: dict[str, tuple[str, ...]] = {
    "consultor": ("120b",),
    "engineer": ("120b",),
    "activate": ("120b",),
    "visual": ("120b",),
    "copy": ("120b",),
    "content": ("120b",),
    "flow": ("120b",),
    "simulate": ("120b",),
    "persona": ("120b",),
    "sync": ("120b",),
    "publish": ("120b",),
    "insight": ("120b",),
    "optimize": ("120b",),
    "calibrate": ("120b",),
    "maestro": ("120b",),
    "cost": ("20b",),
    "doc": ("20b",),
    "ajuda": ("20b",),
    # guard é DETERMINÍSTICO (§7.2/§1.1.2): o veredito é código; o 20b só EXPLICA o
    # veredito já decidido. Por isso ele aparece com 20b e não com lista vazia —
    # a explicação é uma chamada legítima; a decisão nunca chega ao modelo.
    "guard": ("20b",),
    # As 5 triagens do §7.2 (emenda A18) — camada triagem, 20b.
    "triagem_intake": ("20b",),
    "triagem_audiencia": ("20b",),
    "triagem_criativo": ("20b",),
    "triagem_jornada": ("20b",),
    "triagem_operacao": ("20b",),
}

# Conjunto FECHADO. Cinco campos desde a onda 6 (J02) — e a ausência dos que ficaram
# de fora segue sendo a parte mais importante deste arquivo:
#
# * `teto_tokens` (pedido (d)) ENTROU na onda 6, na ordem que a régua exige: a medição
#   veio na onda 5 (I04 — o `usage` chega a `invocacao.tokens`) e o ENFORCEMENT veio
#   junto com o campo (J02): o portão congela o gasto MEDIDO do tenant no dia (UTC) na
#   fábrica `portao_ia.de` e `autorizar_modelo` recusa com `TetoDeTokensExcedido` (429)
#   ANTES de a chamada custar — teste de inversão em test_F03_ia_responsavel_enforcement.
#   Escopo deliberado: por TENANT por DIA — `os_id` é NULL em ajuda/Ateliê, então um
#   teto "por OS" nasceria com metade das chamadas fora; e teto sem período só estoura
#   uma vez na vida e trava para sempre. Limite DECLARADO (vale o mesmo da tela): linha
#   de ledger com tokens NULL (hub/proxy sem usage) contribui 0 — o teto governa o
#   gasto MEDIDO, nunca inventa medida (a régua de `soma_tokens`).
# * `teto_custo` NÃO entra: exige tarifa R$/token que não existe no domínio (tarifas
#   são por canal de disparo). Entrar sem consumidor seria recriar o achado 8 no mesmo
#   commit que o mata para tokens.
# * `rotulo_ia` (pedido (e)) NÃO entra porque o enforcement dele é a UI marcar a saída
#   de agente em ~10 telas — arquivos fora desta frente. A regra sem as telas seria um
#   booleano que ninguém lê.
#
# Campo novo entra junto com o teste que prova que muda comportamento. É literalmente a
# regra que o achado 8 do UAT #5 cobrou, aplicada ao próprio módulo que nasce dele.
CAMPOS_CONTEUDO: tuple[str, ...] = (
    "dados_llm",  # (a) o que pode sair para o modelo
    "retencao",  # (b) por quanto tempo prompt/resposta ficam guardados
    "decisao_automatizada",  # (c) LGPD Art. 20
    "modelos_permitidos",  # (f) roster §7.2 pinado
    "teto_tokens",  # (d) orçamento de consumo — J02, com enforcement no portão
)

# Obrigatoriedade CONGELADA no conjunto v1 (o espelho exato da doutrina de
# `CATEGORIAS_PII_OBRIGATORIAS`): exigir `teto_tokens` invalidaria, de um deploy para
# o outro, toda política já publicada — a tela do DPO abriria o vigente e o formulário
# nasceria inválido. Omissão cai em "sem teto", que nunca AFROUXA nada: sem teto é o
# comportamento de sempre.
CAMPOS_CONTEUDO_OBRIGATORIOS: tuple[str, ...] = (
    "dados_llm",
    "retencao",
    "decisao_automatizada",
    "modelos_permitidos",
)

# Sub-conjunto FECHADO do bloco `teto_tokens` (mesma doutrina de CAMPOS_RETENCAO).
# Só `tokens_por_dia` tem enforcement hoje; `tokens_por_os_dia`/`teto_custo` entram
# quando (e se) ganharem o seu.
CAMPOS_TETO_TOKENS: tuple[str, ...] = ("tokens_por_dia",)

# Mesmo teto do `retencao_dias` do M12 (`domain/governanca/politicas.py`, purge §10.4).
DIAS_RETENCAO_MAX = 36500

# Sub-conjunto FECHADO do bloco `retencao`. Fechado pelo mesmo motivo que
# `CAMPOS_CONTEUDO`, e com um alvo NOMEADO: `dias_ledger`.
#
# A primeira versão deste módulo trazia `dias_ledger` "para o ledger expirar junto com o
# M12". Medido, isso era um SEGUNDO relógio de retenção: quem apaga o ledger é o
# `purge_service` (§10.4), e ele lê `retencao_dias` da política do M12 pela
# `PublicacoesPort` — provado em `tests/acceptance/test_D01_purge.py`, onde publicar
# `retencao_dias: 30` muda o que some. Nada lia `dias_ledger`. O DPO publicaria
# `dias_ledger: 30`, a tela confirmaria, e o purge seguiria apagando com 180 — o achado
# 8 do UAT #5 reencenado dentro do módulo que nasceu para acabar com ele.
#
# Retenção do ledger tem dono, e o dono é o M12. Aqui fica só `dias_trace`, que é órfão
# lá: o trace do Langfuse é diagnóstico de engenharia, não prova legal, e o `retencao_dias`
# não fala dele. Publicar `dias_ledger` agora é ERRO com mensagem que aponta o campo certo.
CAMPOS_RETENCAO: tuple[str, ...] = ("reter_prompt", "reter_resposta", "dias_trace")


def politica_ia_seed() -> dict[str, Any]:
    """Conteúdo v1 (semente/fallback) — igual ao comportamento de HOJE, por decisão.

    Função e não constante de módulo: devolve estrutura NOVA a cada chamada, então
    ninguém muta o default global sem querer (um `conteudo["retencao"]["dias_ledger"] =
    1` num teste envenenaria todos os outros).
    """
    return {
        # (a) Piso do C02 preservado: tudo mascarado, nada bloqueado ainda. O primeiro
        # aperto recomendado ao DPO é `cartao: bloquear` (cartão em briefing de
        # marketing nunca é parâmetro legítimo — é sempre erro do solicitante).
        "dados_llm": {"acoes": dict.fromkeys(CATEGORIAS_PII, "mascarar")},
        # (b) "Reter o mínimo" é o mínimo NECESSÁRIO, não zero: o Art. 20 exige
        # reconstruir a decisão automatizada (`POST /auditoria/reconstruir/{id}`
        # devolve input/evidências/output da época). Zerar o prompt cumpriria
        # minimização violando o direito à explicação.
        # O PRAZO do ledger não mora aqui: é `retencao_dias` do M12, que o purge §10.4
        # já consome (ver `CAMPOS_RETENCAO`). Aqui fica o que é decisão de IA — gravar
        # ou não o texto — e o prazo do trace, que o M12 não cobre.
        "retencao": {
            "reter_prompt": True,
            "reter_resposta": True,
            "dias_trace": 30,  # trace é diagnóstico, não prova legal: janela menor
        },
        # (c) Art. 20 conservador: allowlist VAZIA = a IA propõe, humano aplica.
        "decisao_automatizada": {"pode_aplicar_sozinho": []},
        # (f) Roster §7.2 pinado.
        "modelos_permitidos": {nome: list(perfis) for nome, perfis in PERFIL_DO_ROSTER.items()},
        # (d) Sem teto por default (J02): null = nenhum limite de consumo — o
        # comportamento de sempre. O DPO aperta quando quiser; ver o efeito na tela.
        "teto_tokens": {"tokens_por_dia": None},
    }


def validar_conteudo(conteudo: Any) -> list[str]:
    """Erros ACUMULADOS do conteúdo (§7.1) — lista vazia = válido.

    Acumula em vez de abortar no primeiro erro porque quem edita isto é o DPO pela
    tela: devolver um erro por vez transformaria a publicação numa gincana.
    """
    if not isinstance(conteudo, dict) or not conteudo:
        return ["conteudo deve ser objeto não-vazio (política de IA Responsável)"]
    erros: list[str] = []
    # Obrigatórios = conjunto v1 CONGELADO (compatibilidade retroativa — ver a nota em
    # CAMPOS_CONTEUDO_OBRIGATORIOS): política publicada antes do J02 continua válida.
    for campo in CAMPOS_CONTEUDO_OBRIGATORIOS:
        if campo not in conteudo:
            erros.append(f"conteudo sem campo obrigatório {campo!r}")
    for campo in conteudo:
        if campo not in CAMPOS_CONTEUDO:
            erros.append(
                f"campo desconhecido {campo!r} — conjunto FECHADO: parâmetro só entra "
                "junto com o enforcement que prova que ele muda comportamento"
            )
    erros.extend(_erros_dados_llm(conteudo.get("dados_llm")) if "dados_llm" in conteudo else [])
    erros.extend(_erros_retencao(conteudo.get("retencao")) if "retencao" in conteudo else [])
    if "decisao_automatizada" in conteudo:
        erros.extend(_erros_decisao(conteudo.get("decisao_automatizada")))
    if "modelos_permitidos" in conteudo:
        erros.extend(_erros_modelos(conteudo.get("modelos_permitidos")))
    if "teto_tokens" in conteudo:
        erros.extend(_erros_teto_tokens(conteudo.get("teto_tokens")))
    return erros


def _erros_teto_tokens(bloco: Any) -> list[str]:
    """Bloco (d) — sub-conjunto fechado {tokens_por_dia: int>0 | null} (J02)."""
    if not isinstance(bloco, dict):
        return ["teto_tokens deve ser {tokens_por_dia: inteiro positivo ou null}"]
    erros: list[str] = []
    for chave in bloco:
        if chave not in CAMPOS_TETO_TOKENS:
            erros.append(
                f"teto_tokens.{chave} desconhecido — sub-conjunto FECHADO: só "
                f"{list(CAMPOS_TETO_TOKENS)} tem enforcement hoje (a régua do achado 8 "
                "vale dentro do bloco também)"
            )
    valor = bloco.get("tokens_por_dia")
    if valor is not None and (isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0):
        erros.append(
            f"teto_tokens.tokens_por_dia deve ser inteiro positivo ou null (recebido "
            f"{valor!r}) — null = sem teto"
        )
    return erros


def _erros_dados_llm(bloco: Any) -> list[str]:
    if not isinstance(bloco, dict) or not isinstance(bloco.get("acoes"), dict):
        return ["dados_llm deve ser {acoes: {categoria: mascarar|bloquear}}"]
    erros: list[str] = []
    acoes = bloco["acoes"]
    # Só as OBRIGATÓRIAS (conjunto V1) são exigidas: uma categoria acrescentada depois
    # não pode invalidar política já publicada. Ver a nota de compatibilidade retroativa
    # em `CATEGORIAS_PII_OBRIGATORIAS` — omitir uma categoria nova cai no piso
    # `mascarar` de `dados._acoes`, então a omissão nunca AFROUXA nada.
    for categoria in CATEGORIAS_PII_OBRIGATORIAS:
        if categoria not in acoes:
            erros.append(
                f"dados_llm.acoes sem a categoria {categoria!r} — todas as categorias "
                "detectáveis precisam de ação declarada (omitir é deixar buraco mudo)"
            )
    for categoria, acao in acoes.items():
        if categoria not in CATEGORIAS_PII:
            erros.append(f"dados_llm.acoes: categoria desconhecida {categoria!r} (§10.2)")
        elif acao not in ACOES_DADO:
            erros.append(
                f"dados_llm.acoes[{categoria!r}] = {acao!r} inválida — use "
                f"{' ou '.join(ACOES_DADO)}. Não existe 'permitir': o mascaramento "
                "do C02 é piso de contrato, a política só aperta."
            )
    return erros


def _erros_retencao(bloco: Any) -> list[str]:
    if not isinstance(bloco, dict):
        return [f"retencao deve ser objeto com {', '.join(CAMPOS_RETENCAO)}"]
    erros: list[str] = []
    for campo in ("reter_prompt", "reter_resposta"):
        if not isinstance(bloco.get(campo), bool):
            erros.append(f"retencao.{campo} deve ser booleano")
    valor = bloco.get("dias_trace")
    if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= DIAS_RETENCAO_MAX:
        erros.append(f"retencao.dias_trace deve ser inteiro de 1 a {DIAS_RETENCAO_MAX} (§10.4)")
    # Sub-conjunto FECHADO: sem isto, remover `dias_ledger` do seed não bastaria —
    # publicar `retencao.dias_ledger: 30` passaria calado e o DPO acreditaria ter
    # encurtado a retenção do ledger, enquanto o purge seguiria com o `retencao_dias`
    # do M12. Campo inerte precisa ser REJEITADO, não apenas não-documentado.
    for campo in bloco:
        if campo == "dias_ledger":
            erros.append(
                "retencao.dias_ledger não existe nesta política — a retenção do ledger "
                "é `retencao_dias` na política do M12, que é quem o purge §10.4 lê. "
                "Publicar aqui não mudaria nada do que é apagado."
            )
        elif campo not in CAMPOS_RETENCAO:
            erros.append(
                f"retencao: campo desconhecido {campo!r} — conjunto FECHADO: "
                f"{', '.join(CAMPOS_RETENCAO)}"
            )
    return erros


def _erros_decisao(bloco: Any) -> list[str]:
    if not isinstance(bloco, dict) or not isinstance(bloco.get("pode_aplicar_sozinho"), list):
        return ["decisao_automatizada deve ser {pode_aplicar_sozinho: [acao, ...]}"]
    return [
        f"decisao_automatizada.pode_aplicar_sozinho: ação desconhecida {acao!r} — "
        f"vocabulário fechado: {', '.join(ACOES_VIA_AI)}"
        for acao in bloco["pode_aplicar_sozinho"]
        if acao not in ACOES_VIA_AI
    ]


def _erros_modelos(bloco: Any) -> list[str]:
    if not isinstance(bloco, dict) or not bloco:
        return ["modelos_permitidos deve ser {agente: [perfil, ...]} não-vazio (roster §7.2)"]
    erros: list[str] = []
    for agente, perfis in bloco.items():
        # Agente fora do roster §7.2 é REJEITADO pelo mesmo motivo que ação fora de
        # `ACOES_VIA_AI`: um typo ("enginer") viraria entrada morta, `perfis_permitidos`
        # cairia no roster e o `engineer` seguiria liberado. O DPO acreditaria ter
        # restringido um agente que continua aberto — falha silenciosa na direção errada
        # da auditoria, que é o pior modo de errar para um controle de governança.
        if agente not in PERFIL_DO_ROSTER:
            erros.append(
                f"modelos_permitidos: agente desconhecido {agente!r} — roster §7.2: "
                f"{', '.join(sorted(PERFIL_DO_ROSTER))}"
            )
        if not isinstance(perfis, list):
            erros.append(f"modelos_permitidos[{agente!r}] deve ser lista de perfis")
            continue
        for perfil in perfis:
            if perfil not in PERFIS_MODELO:
                erros.append(
                    f"modelos_permitidos[{agente!r}]: perfil {perfil!r} inválido — "
                    f"roteamento §3 usa {' e '.join(PERFIS_MODELO)}"
                )
    return erros
