"""Mascaramento ESTRUTURAL — `mascarar_pii` aplicado a árvores de dados (§10.2).

Por que existe: o C02 mascarou a *string* que vai ao prompt, mas a plataforma também
despeja ESTRUTURAS inteiras em destinos externos — `conteudo`/`briefing` de um pedido
(dicionário campo→valor digitado pelo solicitante), `payload` de evento do outbox
(§2.3) e `metadados`/`spans` do trace Langfuse (§10.8). Mascarar cada string à mão em
cada chamador é a receita do achado 9 do UAT #5: fecha-se a janela e deixa-se a porta.
Aqui a regra é uma só, aplicada à árvore inteira.

Contrato (mesmo espírito de `mascarar_pii` — robustez é lei):
- **puro e determinístico**: sem I/O, sem estado, mesma entrada ⇒ mesma saída;
- **preserva a FORMA**: dicionário continua dicionário, lista continua lista, tupla
  continua tupla; `int`/`float`/`bool`/`None`/`UUID`/`datetime` passam INTACTOS (verba
  `480000` é número de negócio, não texto — não há o que mascarar);
- **não muda chaves**: chave de dicionário é nome de campo do §4.1 (contrato), não
  dado do titular; mascarar `"objetivo"` quebraria completude/validação por código.
  ATENÇÃO: isso vale para estruturas de contrato (payload de evento, trace). Onde a
  chave é DIGITADA pelo usuário — `conteudo`/`campos` do pedido, que são
  `dict[str, Any]` aberto — use `mascarar_campos`, que mascara chave e valor;
- **não muta a entrada**: devolve estrutura nova (o chamador pode manter o original
  em memória para o que já era legítimo).
"""

from typing import Any, TypeVar

from domain.privacidade.mascarar import mascarar_pii

T = TypeVar("T")

# Ciclos em payload de evento/trace não deveriam existir (tudo é JSON serializável),
# mas recursão sem freio vira RecursionError — e telemetria NUNCA pode derrubar a
# aplicação (§10.8). Fundo de poço: abaixo deste nível o ramo é descartado.
PROFUNDIDADE_MAXIMA = 12


def mascarar_estrutura(valor: Any, _profundidade: int = 0) -> Any:
    """Aplica `mascarar_pii` a TODA string alcançável em `valor`, preservando a forma.

    Uso na fronteira: entrada de texto livre estruturado (`conteudo` do pedido,
    `briefing` da OS) e saída para destinos externos (payload de evento, trace).
    """
    if _profundidade >= PROFUNDIDADE_MAXIMA:
        return None
    if isinstance(valor, str):
        return mascarar_pii(valor)
    # `bool` é subclasse de `int`: ambos passam intactos — a checagem explícita existe
    # só para documentar que números de negócio nunca são tocados.
    if isinstance(valor, bool | int | float) or valor is None:
        return valor
    if isinstance(valor, dict):
        return {chave: mascarar_estrutura(item, _profundidade + 1) for chave, item in valor.items()}
    if isinstance(valor, list):
        return [mascarar_estrutura(item, _profundidade + 1) for item in valor]
    if isinstance(valor, tuple):
        return tuple(mascarar_estrutura(item, _profundidade + 1) for item in valor)
    if isinstance(valor, set):
        return {mascarar_estrutura(item, _profundidade + 1) for item in valor}
    # UUID, datetime, Decimal, dataclass de domínio...: tipos que não carregam texto
    # livre do usuário. Passam intactos — converter para str aqui destruiria o
    # contrato de tipos do §4.1 (um os_id viraria string no payload do evento).
    return valor


def mascarar_campos(mapa: dict[str, Any]) -> dict[str, Any]:
    """Mascara CHAVE **e** valor de um mapa `{campo: valor}` digitado pelo usuário.

    Por que é uma função separada de `mascarar_estrutura`: as duas tratam a chave de
    forma OPOSTA, de propósito.

    - `mascarar_estrutura` NÃO toca em chave, porque roda sobre estruturas cujas chaves
      são nomes de campo do contrato (payload de evento, `metadados`/`spans` do trace).
      Mascarar `"objetivo"` ali quebraria a completude, que é código (§8-M3), e os
      consumidores do outbox (§2.3).
    - Aqui a chave É digitação. `POST /pedidos` e `PATCH /pedidos/{id}/campos` recebem
      `conteudo: dict[str, Any]` — dicionário ABERTO, sem enum de campos: o solicitante
      escolhe o nome do campo. Medido no UAT: `{"oferta contato joao@x.com.br": "10%"}`
      persistia a chave em claro em `pedido.conteudo` E vazava no payload de
      `pedido.campos_editados` (`{"campos": sorted(campos)}`), que é o que a integração
      externa lê. É exatamente o motivo pelo qual `editar_briefing` já mascarava o
      `campo` vindo do PATH — a mesma chave, pela porta do JSON, ficara aberta.

    Colisão após o mascaramento (`"CPF 111.111.111-11"` e `"CPF 222.222.222-22"` viram a
    mesma chave) resolve pelo ÚLTIMO — perder um campo de nome forjado é aceitável;
    devolver a PII não é. Completude e faltantes são recalculados por código depois.
    """
    return {mascarar_pii(chave): mascarar_estrutura(valor) for chave, valor in mapa.items()}


def contem_pii_estrutura(valor: Any) -> bool:
    """True se `mascarar_estrutura` alteraria alguma string da árvore — detecção e
    mascaramento usam exatamente a MESMA regra (não podem divergir)."""
    return mascarar_estrutura(valor) != valor
