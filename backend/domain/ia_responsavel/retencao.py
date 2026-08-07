"""(b) RETENÇÃO de prompt/resposta no ledger e no trace — parâmetro `retencao`.

Divisão de trabalho com a frente 3: o PURGE (o job que apaga o ledger) é dela E o prazo
dele também — `purge_service` lê `retencao_dias` da política do M12 pela
`PublicacoesPort`. Este módulo NÃO duplica esse prazo; ver `politica.CAMPOS_RETENCAO`
para o porquê (um segundo relógio que ninguém lê é o achado 8 reencenado).

Aqui moram as duas regras que sobram, e são de IA, não de infraestrutura:

1. **redação na ESCRITA** (`aplicar_retencao`): com `reter_prompt: false`, o texto do
   prompt não chega a ser gravado no ledger. É o enforcement imediato — não depende de
   job nenhum rodar, e é o único do módulo que age no instante da gravação.
2. **prazo do TRACE** (`expira_em`): janela do trace Langfuse, que o `retencao_dias` do
   M12 não cobre por ser diagnóstico de engenharia e não prova legal.

## Por que o default NÃO é "não reter"

"Reter o mínimo" foi o pedido, e o instinto é gravar nada. Mas o mínimo aqui é o mínimo
NECESSÁRIO, e a necessidade é legal: o Art. 20 dá ao titular direito a explicação sobre
decisão automatizada, e a plataforma cumpre isso com
`POST /auditoria/reconstruir/{invocacao_id}`, que devolve EXATAMENTE input/evidências/
output da época (§8-M12). Zerar o prompt cumpriria a minimização violando o direito à
explicação — trocaria um dever por outro.

O mínimo defensável é, então: guardar o necessário para explicar, por JANELA CURTA, e
purgar de verdade no fim dela. Daí o default `reter_* = true`. A janela do LEDGER é o
`retencao_dias` do M12 (180 dias no seed §11.4), lido pelo purge — não é redeclarada
aqui, porque dois relógios de retenção divergentes na mesma plataforma seriam um achado
por si só. `dias_trace = 30` é o único prazo deste módulo: o trace Langfuse é
diagnóstico de engenharia, não prova legal, e o M12 não fala dele.

Desligar `reter_prompt` continua disponível para o tenant que aceite abrir mão da
reconstrução — mas passa a ser escolha explícita, versionada e assinada, em vez de
efeito colateral de código.
"""

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, overload

# Chaves TÉCNICAS: correlação e metadado ESCALAR, nunca texto livre — o que SOBREVIVE à
# redação.
#
# A polaridade aqui é a decisão de segurança do módulo, e ela já esteve errada: a versão
# anterior listava as chaves de TEXTO ("instrucoes", "pergunta", "resposta"...) e retinha
# todo o resto. Medido contra os payloads REAIS do ledger (§4.1), isso deixava PII em
# claro com `reter_* = false` ligado — o `output` do `audiencia_service`
# (`sql`/`explicacao`/`evidencias`) não tinha UMA chave em comum com a lista e escapava
# inteiro; o `kv_master` do `criativo_service` escapava por ser dicionário aninhado; as
# `inferencias` do `consultor_service` por serem lista. O DPO desligava a retenção, a
# auditoria via `[SUPRIMIDO...]` ao lado do CPF intacto e concluía que funcionou.
#
# Uma lista de chaves de texto é uma aposta em conhecer TODOS os payloads presentes e
# futuros; toda chave nova nasce retida, em silêncio. Invertido, toda chave nova nasce
# redigida e quem quiser preservá-la precisa declará-la aqui — o mesmo espírito do
# conjunto FECHADO de `politica.py`, e a mesma direção de falha segura que
# `dados._acoes` e `decisao._allowlist` já adotam.
#
# ## Duas saídas desta lista, medidas pela auditoria com `reter_* = false` PUBLICADO
#
# 1. **`evidencias` SAIU.** O comentário que sobrevivia aqui afirmava que evidência é
#    "id e ref `nome@versao`". A premissa é FALSA em todos os produtores: os três
#    intérpretes de saída de agente (`agents/consultor.py`, `agents/engineer.py`,
#    `agents/criativo.py`) montam a lista com `str(e).strip()` de itens que o MODELO
#    escreveu, e no `audiencia_service` o conteúdo vem do corpus RAG. A medição pegou a
#    linha do ledger com `"resposta": "[SUPRIMIDO...]"` ao lado de
#    `"evidencias": ["Solicitante <nome> (contato <email>) pediu 500k"]` — o modo de
#    falha que este comentário descreve 40 linhas acima, dentro da lista que existe para
#    impedi-lo. Ref versionada continua sendo prova útil, mas ela não é o que o campo
#    CARREGA; preservá-la exigiria checar a FORMA do valor (uuid, `nome@versao`), nunca
#    o nome da chave — ver EMENDA SUGERIDA.
# 2. **`propostas` saiu junto**, por consequência da regra de escalares abaixo e não por
#    ser texto: no ledger do `otimizacao_service` ela é LISTA de uuids, e preservação
#    passou a valer só para ESCALARES. A correlação não se perde — o evento
#    `proposta.criada` (§2.3) carrega os mesmos ids ao lado de `invocacao_id`, que é o
#    mesmo argumento já usado para o `compliance_bypass_tentado` do consultor.
CHAVES_TECNICAS: frozenset[str] = frozenset(
    {
        # metadado do span (§4.1) — não vem do usuário
        "agente",
        "skill",
        "skill_versao",
        "proposito",
        "latencia_ms",
        # referência versionada: `consulta` é nome canônico do dicionário
        # (`vw_metricas_*`, §8-M10) — o insight nunca compõe SQL livre, o nome vem de um
        # conjunto fechado de views e não do texto do usuário.
        "consulta",
        # contadores e vereditos: já são agregados, não texto
        "textos",
        "descartadas",
        "valido",
    }
)

# Sufixo de correlação: `os_id`, `pedido_id`, `jornada_base_id`, `invocacao_id`... São
# UUIDs, e sem eles a linha do ledger deixa de ser correlacionável — a redação perderia
# a auditoria junto com o dado, que é o oposto do objetivo.
SUFIXO_ID = "_id"

# ...MAS o sufixo é um padrão ABERTO, e é aí que ele difere de `CHAVES_TECNICAS`.
#
# `CHAVES_TECNICAS` é lista FECHADA: cada entrada foi conferida contra quem PRODUZ o
# campo (`consulta` sai de um conjunto fechado de views; `textos`/`descartadas` são
# `len(...)`; `valido` é `not erros`). Já `*_id` casa com qualquer nome que qualquer
# um invente — e o valor não precisa ser um id só porque a chave termina em `_id`.
#
# Medido pela ROTA, com `reter_prompt: false` + `reter_resposta: false` publicados pela
# rota do DPO e `POST /os/{id}/criativos/gerar` no caminho de usuário — o `kv_master`
# vai CRU ao ledger (só `instrucoes` passa por `portao.sanear`) e suas chaves vêm do
# corpo da requisição:
#
#     "kv_master": {"produto":    "[SUPRIMIDO POR POLITICA DE RETENCAO]",
#                   "cliente_id": "Maria da Conceicao dos Santos - 111.444.777-35",
#                   "contato_id": "maria.da.conceicao@vivo.com.br",
#                   "documento":  11144477735}
#
# É o modo de falha do `evidencias` uma camada abaixo, e desta vez sem adversário
# nenhum: basta o analista de campanha nomear um campo de KV `cliente_id`. Preservar
# pelo NOME da chave é a aposta que esta lista inteira existe para não fazer.
#
# Então a preservação por `*_id` passa a checar a FORMA do valor — é a EMENDA que a
# onda anterior propôs e não aplicou onde ela era carregada. Correlação no §4.1 é UUID
# (`str(pedido.id)`, `str(os_.id)`, `str(run.id)`, `str(skill.id)`): TODOS os `*_id`
# gravados hoje passam, e nenhum nome ("Maria da Conceicao"), e-mail ou documento passa.
#
# Custo declarado: um serviço futuro que use id NÃO-uuid (código externo, chave natural)
# perde correlação sob `reter_* = false` até declarar a chave em `CHAVES_TECNICAS` — de
# propósito, porque essa declaração é a revisão que hoje não acontece.
_UUID_CANONICO = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)

# Número com 11+ dígitos é DOCUMENTO, não métrica — a outra metade da mesma medição.
#
# Valor não-textual atravessa a redação intacto (ver `_redigir`), e o `documento:
# 11144477735` da linha acima é JSON number: `isinstance(valor, str)` é falso e o CPF
# sobrevivia inteiro. Um titular não fica menos identificado por ter sido escrito sem
# aspas.
#
# 11 é o tamanho do CPF e do celular com DDD, e é MAIS permissivo que a doutrina que a
# plataforma já aplica a texto (`domain/privacidade/mascarar._DIGITOS` varre runs de 8+
# dígitos) — a régua daqui não é mais dura que a de lá, é a mesma direção com folga.
#
# Custo medido do falso positivo: nenhuma métrica do ledger de hoje chega perto —
# `latencia_ms` (3-4), `contexto_chars`/`historico_len` (2-4), `textos`/`descartadas`
# (1-2), e verba/volume de campanha em reais ficam na casa dos 6-7 dígitos. Onze dígitos
# é R$ 10 bilhões: em telco isso é documento, não orçamento de campanha.
_DIGITOS_DE_DOCUMENTO = 11

# Nome usado para os ITENS de uma lista. Dentro de uma lista não existe chave, e herdar
# a chave do campo era o que estendia a preservação a TUDO abaixo dela — a metade
# latente do mesmo furo do `evidencias`. Não é técnico nem termina em `_id`, então cai
# no caso geral: redigir.
_ITEM_LIVRE = "item"

# Marcador que substitui o texto redigido — a CHAVE permanece, para a auditoria ver que
# havia conteúdo e que ele foi suprimido por política (apagar a chave faria parecer que
# o campo nunca existiu, que é uma mentira diferente).
REDIGIDO = "[SUPRIMIDO POR POLITICA DE RETENCAO]"

# Só `dias_trace`: o prazo do LEDGER é `retencao_dias` da política do M12, que o
# `purge_service` (§10.4) já lê pela `PublicacoesPort`. Ver `politica.CAMPOS_RETENCAO`.
_PADRAO_DIAS = {"dias_trace": 30}


def deve_reter_prompt(conteudo: dict[str, Any]) -> bool:
    """Piso seguro `True`: conteúdo corrompido não pode APAGAR prova de auditoria."""
    return _flag(conteudo, "reter_prompt")


def deve_reter_resposta(conteudo: dict[str, Any]) -> bool:
    return _flag(conteudo, "reter_resposta")


def dias_retencao(conteudo: dict[str, Any], alvo: str = "dias_trace") -> int:
    """Janela de retenção do TRACE em dias.

    Só existe `dias_trace`. O prazo do ledger é `retencao_dias` na política do M12 —
    duplicá-lo aqui criaria dois relógios, e só um deles é lido pelo purge.
    """
    bloco = _bloco(conteudo)
    valor = bloco.get(alvo)
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        return _PADRAO_DIAS.get(alvo, 30)
    return valor


def expira_em(created_at: datetime, conteudo: dict[str, Any], alvo: str = "dias_trace") -> datetime:
    """Instante a partir do qual o TRACE é descartável (§10.4).

    Puro: recebe o `created_at` da linha, devolve data. Nenhum relógio interno, para o
    cálculo ser testável e idêntico em qualquer fuso.
    """
    return created_at + timedelta(days=dias_retencao(conteudo, alvo))


@overload
def aplicar_retencao(
    payload: dict[str, Any], conteudo: dict[str, Any], *, tipo: str
) -> dict[str, Any]: ...


@overload
def aplicar_retencao(payload: None, conteudo: dict[str, Any], *, tipo: str) -> None: ...


def aplicar_retencao(
    payload: dict[str, Any] | None, conteudo: dict[str, Any], *, tipo: str
) -> dict[str, Any] | None:
    """Redige o texto livre de um payload do ledger ANTES da gravação.

    `tipo` = `"input"` (consulta `reter_prompt`) ou `"output"` (consulta
    `reter_resposta`) — o `tipo` escolhe a FLAG, não um conjunto de chaves. A regra de
    redação é a mesma dos dois lados de propósito: manter duas listas de chaves era
    manter duas chances de divergir dos serviços.

    Redige TUDO que é texto, em qualquer profundidade, exceto o valor ESCALAR das
    chaves técnicas declaradas em `CHAVES_TECNICAS` e dos campos de correlação `*_id`
    CUJO VALOR TEM FORMA DE UUID (chave preservada com dicionário/lista embaixo NÃO
    atravessa: `_redigir` desce). Só o `input`/`output`: a coluna `evidencias` do §4.1
    tem função própria (`aplicar_retencao_evidencias`), porque ela nunca esteve dentro
    deste payload — e é exatamente por isso que ela passou uma onda inteira sem política
    alguma. Recursivo porque
    os payloads reais aninham (`kv_master` é dicionário, `inferencias` e `explicacao`
    são listas): redigir só a superfície suprimiria a chave visível e deixaria o dado
    uma camada abaixo — pior que não redigir, porque a auditoria acreditaria na
    supressão.

    Valores não-textuais (bool, float, None e inteiro curto) atravessam intactos: não
    são texto livre, e zerá-los destruiria a métrica sem ganho de privacidade. INTEIRO
    com 11+ dígitos é a exceção — é documento, não métrica (ver `_e_documento`).

    Não muta a entrada (o chamador ainda precisa do texto original para montar o prompt
    da chamada em curso). Com `reter = true` a cópia é RASA, e isso é dito porque a
    versão anterior desta linha prometia "estrutura nova" sem qualificar: quem retém e
    depois mutar um galho aninhado do dicionário devolvido mutará o do chamador. Não é
    um caminho de hoje — os serviços constroem o payload literal na própria chamada —
    mas uma promessa de imutabilidade mais forte do que o código entrega é como um
    controle de privacidade vira crença. No caminho REDIGIDO a estrutura é reconstruída
    inteira, então lá a garantia é real.

    Os `@overload` existem por ergonomia de chamador: `invocacao.input`/`output` são
    `dict | None` no §4.1, mas quem passa um dicionário recebe um dicionário e não
    deveria ter de estreitar tipo para indexar o resultado. Sem isso, o caminho mais
    curto para o serviço satisfazer o mypy seria um `# type: ignore` — e aí o portão
    de tipos para de valer justamente onde ele protege dado pessoal.
    """
    if payload is None:
        return None
    reter = deve_reter_prompt(conteudo) if tipo == "input" else deve_reter_resposta(conteudo)
    if reter:
        return dict(payload)
    return {chave: _redigir(chave, valor) for chave, valor in payload.items()}


def aplicar_retencao_evidencias(evidencias: Sequence[Any], conteudo: dict[str, Any]) -> list[Any]:
    """Redige a COLUNA `invocacao.evidencias` (§4.1) ANTES da gravação.

    Existe separada de `aplicar_retencao` porque `evidencias` não está DENTRO de
    `input`/`output`: é a TERCEIRA coluna de conteúdo do ledger, e era a única que
    nenhuma política alcançava. Os `_registrar_invocacao` embrulhavam os dois
    dicionários no portão e atribuíam `evidencias=` ao lado, fora dele — com
    `reter_* = false` publicado a auditoria lia `[SUPRIMIDO...]` no `output` e o texto
    livre do modelo intacto na coluna vizinha, que é a supressão em que se acredita e
    que não aconteceu. Três colunas de conteúdo, três enforcements: o que não tem
    função para chamar é o que ninguém lembra de chamar.

    **As DUAS flags governam, e a conjunção é deliberada.** A evidência é ao mesmo tempo
    eco do PROMPT (no consultor ela é o trecho da conversa que sustentou a inferência —
    `agents/consultor.py`) e saída do MODELO (no audiencia é o que o agente citou do
    corpus RAG). Preservá-la com `reter_prompt: false` devolveria pela coluna o texto
    que o DPO mandou não gravar; preservá-la com `reter_resposta: false` faria o mesmo
    com a resposta. Quem desliga um dos lados desliga a evidência.

    Devolve lista NOVA (não muta): o chamador ainda usa as evidências originais na
    resposta da rota e no evento.
    """
    if deve_reter_prompt(conteudo) and deve_reter_resposta(conteudo):
        return list(evidencias)
    return [_redigir(_ITEM_LIVRE, item) for item in evidencias]


def _preservar(chave: str, valor: Any = "") -> bool:
    """Escalar que a redação NÃO toca: chave técnica declarada, ou `*_id` com FORMA de id.

    As duas metades não são simétricas, e a assimetria é a correção desta rodada.
    `CHAVES_TECNICAS` é conjunto FECHADO — cada nome foi conferido contra seu produtor,
    então o NOME basta. `SUFIXO_ID` é padrão ABERTO: ele casa com qualquer chave que
    qualquer serviço (ou qualquer usuário, via `kv_master`) invente amanhã, e por isso
    precisa olhar o VALOR. Um `contato_id` com um e-mail dentro não vira correlação por
    causa do sufixo.
    """
    if chave in CHAVES_TECNICAS:
        return True
    return chave.endswith(SUFIXO_ID) and bool(_UUID_CANONICO.match(valor))


def _e_documento(valor: Any) -> bool:
    """Inteiro longo o bastante para ser CPF/CNPJ/celular — PII escrita sem aspas.

    `bool` é subclasse de `int` em Python e `valido: True` é veredito, não documento:
    sem a exclusão explícita, `True` viraria o inteiro 1 e a régua o deixaria passar por
    acidente em vez de por decisão.
    """
    if not isinstance(valor, int) or isinstance(valor, bool):
        return False
    return len(str(abs(valor))) >= _DIGITOS_DE_DOCUMENTO


# O valor de sonda é um UUID de propósito, porque é o pior caso: com `_ITEM_LIVRE`
# renomeado para algo terminado em `_id`, sondar com `""` acharia a guarda satisfeita e
# mesmo assim todo item de lista com forma de uuid passaria a ser preservado.
if _preservar(_ITEM_LIVRE, "3f1a0c2e-0000-4000-8000-000000000001"):  # falha no IMPORT
    raise ValueError(
        f"O nome de item de lista {_ITEM_LIVRE!r} entrou em CHAVES_TECNICAS/SUFIXO_ID: "
        "todo item de lista passaria a ser preservado, e a redação viraria carimbo. "
        "É o furo do `evidencias` (§10.4) generalizado para o payload inteiro."
    )


def _redigir(chave: str, valor: Any) -> Any:
    """Redige `valor` recursivamente; chave E valor decidem a preservação.

    **A preservação vale para ESCALARES e só para eles.** `{"os_id": "<uuid>"}` é
    correlação; `{"os_id": {"nota": "<texto do titular>"}}` é texto livre atrás de um
    nome de chave preservado, e uma versão anterior devolvia essa estrutura INTEIRA sem
    olhar. Era a metade latente do furo do `evidencias` (que já era explorável por
    rota): qualquer chave técnica ou `*_id`, em qualquer profundidade, atravessava
    completa. Por isso o container é tratado ANTES da preservação — descer na estrutura
    redige o texto e ainda preserva os `*_id` escalares lá dentro, enquanto trocar o
    dicionário inteiro por `[SUPRIMIDO...]` destruiria a forma junto.

    **E ela vale só para escalares COM A FORMA CERTA.** Descer na estrutura não bastava:
    a auditoria mediu `{"kv_master": {"cliente_id": "<nome> - <CPF>"}}` gravado inteiro
    pela rota do criativo, porque a chave terminava em `_id` e o valor era escalar. Um
    escalar sob nome preservado é o mesmo bolso, um nível mais raso. Ver `_preservar`.

    O payload de HOJE que aninha sob chave técnica é o `kv_master`, cujas chaves vêm do
    corpo da requisição; para as demais a regra existe porque a lista de exceções é a
    parte do módulo em que o autor do payload de amanhã escolhe, sem saber que escolheu,
    o que a auditoria vai poder ler.

    Custo aceito: `{"propostas": ["<uuid>", "<uuid>"]}` passa a ser redigida. Uma lista
    de escalares não se distingue, PELA CHAVE, de `evidencias` — e a correlação das
    propostas está no evento `proposta.criada` (§2.3).

    **Números atravessam, EXCETO os que têm cara de documento.** `latencia_ms` e os
    contadores são métrica e zerá-los cegaria a auditoria sem ganho nenhum de
    privacidade; um inteiro de 11+ dígitos, porém, é CPF/CNPJ/celular — a auditoria
    mediu `{"documento": 11144477735}` sobrevivendo à redação pela rota do criativo, só
    por ter chegado como JSON number em vez de string. Ver `_DIGITOS_DE_DOCUMENTO`.

    **Limite que este módulo NÃO alcança, e que por isso é declarado:** a redação é dos
    VALORES. A CHAVE de um dicionário atravessa sempre — `{"Maria da Conceicao": "x"}`
    grava o nome no ledger com o valor suprimido ao lado. Manter a chave é o que permite
    à auditoria ver que houve conteúdo e que ele foi suprimido (apagá-la mentiria sobre
    o campo ter existido), e redigir chaves colidiria várias em uma só, destruindo a
    forma que esta função existe para preservar. O conserto certo é a montante — o
    `kv_master` chegar ao ledger já saneado, como `instrucoes` chega — e não aqui. Ver
    EMENDA SUGERIDA.
    """
    if isinstance(valor, dict):
        return {sub: _redigir(sub, item) for sub, item in valor.items()}
    if isinstance(valor, list | tuple):
        return [_redigir(_ITEM_LIVRE, item) for item in valor]
    if isinstance(valor, str):
        return valor if _preservar(chave, valor) else REDIGIDO
    return REDIGIDO if _e_documento(valor) else valor


def _bloco(conteudo: dict[str, Any]) -> dict[str, Any]:
    bloco = conteudo.get("retencao") if isinstance(conteudo, dict) else None
    return bloco if isinstance(bloco, dict) else {}


def _flag(conteudo: dict[str, Any], campo: str) -> bool:
    valor = _bloco(conteudo).get(campo)
    return valor if isinstance(valor, bool) else True
