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

from datetime import datetime, timedelta
from typing import Any, overload

# Chaves TÉCNICAS: correlação e metadado, nunca texto livre — o que SOBREVIVE à redação.
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
CHAVES_TECNICAS: frozenset[str] = frozenset(
    {
        # metadado do span (§4.1) — não vem do usuário
        "agente",
        "skill",
        "skill_versao",
        "proposito",
        "latencia_ms",
        # referências versionadas: prova de auditoria SEM conteúdo do titular.
        # `consulta` é nome canônico do dicionário (`vw_metricas_*`, §8-M10) — o insight
        # nunca compõe SQL livre; `evidencias`/`propostas` são ids e refs `nome@versao`.
        "consulta",
        "evidencias",
        "propostas",
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

    Redige TUDO que é texto, em qualquer profundidade, exceto as chaves técnicas
    declaradas em `CHAVES_TECNICAS` e os campos de correlação `*_id`. Recursivo porque
    os payloads reais aninham (`kv_master` é dicionário, `inferencias` e `explicacao`
    são listas): redigir só a superfície suprimiria a chave visível e deixaria o dado
    uma camada abaixo — pior que não redigir, porque a auditoria acreditaria na
    supressão.

    Valores não-textuais (int, bool, float, None) atravessam intactos: não são texto
    livre, e zerá-los destruiria a métrica sem ganho de privacidade.

    Não muta a entrada: devolve estrutura nova (o chamador ainda precisa do texto
    original para montar o prompt da chamada em curso).

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


def _preservar(chave: str) -> bool:
    """Chave técnica ou de correlação — o que a redação NÃO toca (deny by default)."""
    return chave in CHAVES_TECNICAS or chave.endswith(SUFIXO_ID)


def _redigir(chave: str, valor: Any) -> Any:
    """Redige `valor` recursivamente; `chave` decide apenas a preservação técnica.

    A chave não é reavaliada dentro das listas: uma lista preservada é preservada
    inteira (`evidencias`), e uma lista redigida tem cada item redigido — não existe
    caso real de lista mista, e inventar um daria margem a "meio suprimido".
    """
    if _preservar(chave):
        return valor
    if isinstance(valor, str):
        return REDIGIDO
    if isinstance(valor, dict):
        return {sub: _redigir(sub, item) for sub, item in valor.items()}
    if isinstance(valor, list):
        return [_redigir(chave, item) for item in valor]
    return valor


def _bloco(conteudo: dict[str, Any]) -> dict[str, Any]:
    bloco = conteudo.get("retencao") if isinstance(conteudo, dict) else None
    return bloco if isinstance(bloco, dict) else {}


def _flag(conteudo: dict[str, Any], campo: str) -> bool:
    valor = _bloco(conteudo).get(campo)
    return valor if isinstance(valor, bool) else True
