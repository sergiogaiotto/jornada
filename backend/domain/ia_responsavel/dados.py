"""(a) DADOS QUE PODEM IR AO LLM — enforcement do parâmetro `dados_llm` (§10.2).

Hoje seis serviços chamam `mascarar_pii(texto)` com regra FIXA no código: toda PII vira
marcador e a chamada segue. A regra é boa, mas é constante — o DPO não consegue dizer
"neste tenant, cartão não vira `[CARTAO]`: a chamada não acontece".

Este módulo é o ponto ÚNICO onde a política decide o destino do texto. Ele NÃO
reimplementa detecção: delega a `domain/privacidade/mascarar.py` (fonte única do §10.2,
emenda C02) e lê o resultado. Duplicar os regexes aqui criaria duas verdades de PII que
divergiriam no primeiro ajuste — o erro clássico de "detector do lado do consumidor".

## Como a categoria é descoberta sem duplicar o detector

`mascarar_pii` substitui cada achado por um marcador ESTÁVEL (`[CPF]`, `[EMAIL]`...).
Comparar a contagem de cada marcador ANTES e DEPOIS diz exatamente quais categorias o
mascarador encontrou. A contagem "antes" não é zero por acaso: o mascarador é
idempotente, então um `[CPF]` que já viesse no texto de entrada sobrevive à passagem —
contar o DELTA, e não o total, é o que impede um usuário de forjar detecção digitando
"[CPF]" no briefing (ou de escondê-la, no sentido contrário).

## Ordem das ações: bloquear vence

Se qualquer categoria detectada estiver marcada como `bloquear`, a chamada morre — mesmo
que as outras estejam como `mascarar`. Bloqueio é sobre o texto INTEIRO porque é o texto
inteiro que sairia do perímetro.
"""

from typing import Any, NamedTuple

from domain.ia_responsavel.erros import DadoBloqueadoParaLlm
from domain.ia_responsavel.politica import CATEGORIAS_PII
from domain.privacidade.mascarar import (
    MARCADOR_CARTAO,
    MARCADOR_CEP,
    MARCADOR_CNPJ,
    MARCADOR_CPF,
    MARCADOR_DATA_NASCIMENTO,
    MARCADOR_DOCUMENTO,
    MARCADOR_EMAIL,
    MARCADOR_ENDERECO,
    MARCADOR_NOME,
    MARCADOR_RG,
    MARCADOR_TELEFONE,
    mascarar_pii,
)

# categoria da política → marcador do §10.2 (fonte única).
#
# Este mapa é o ACOPLAMENTO estrutural entre o vocabulário da política e o detector:
# categoria em `CATEGORIAS_PII` sem entrada aqui quebra `categorias_detectadas` no
# import, e é assim que tem de ser — categoria sem marcador seria regra sem detector,
# exatamente o que o cabeçalho de `politica.py` proíbe.
MARCADOR_DA_CATEGORIA: dict[str, str] = {
    "cpf": MARCADOR_CPF,
    "cnpj": MARCADOR_CNPJ,
    "email": MARCADOR_EMAIL,
    "telefone": MARCADOR_TELEFONE,
    "cartao": MARCADOR_CARTAO,
    "documento": MARCADOR_DOCUMENTO,
    # Titular identificado (onda 3c) — detecção por contexto em `mascarar.py`.
    "nome": MARCADOR_NOME,
    "endereco": MARCADOR_ENDERECO,
    "cep": MARCADOR_CEP,
    "data_nascimento": MARCADOR_DATA_NASCIMENTO,
    "rg": MARCADOR_RG,
}


class Saneamento(NamedTuple):
    """Resultado do portão de dados: o texto que PODE seguir + o que foi encontrado.

    `categorias` alimenta o ledger `invocacao` e o trace: uma auditoria precisa saber
    que havia CPF no pedido e que ele foi mascarado, sem que o CPF apareça em lugar
    nenhum (é por isso que o retorno traz a CATEGORIA, nunca o valor).
    """

    texto: str
    categorias: tuple[str, ...]


def categorias_detectadas(texto: str) -> tuple[str, ...]:
    """Categorias de PII presentes em `texto`, na ordem canônica de `CATEGORIAS_PII`.

    Ordem canônica (e não ordem de aparição) para o resultado ser determinístico e
    comparável entre execuções — o ledger é prova, e prova não pode variar de ordem.
    """
    if not texto:
        return ()
    mascarado = mascarar_pii(texto)
    if mascarado == texto:
        return ()
    return tuple(
        categoria
        for categoria in CATEGORIAS_PII
        if mascarado.count(MARCADOR_DA_CATEGORIA[categoria])
        > texto.count(MARCADOR_DA_CATEGORIA[categoria])
    )


def sanear_para_llm(texto: str, conteudo: dict[str, Any]) -> Saneamento:
    """Portão do texto livre antes de virar prompt/embedding/ledger (§10.2).

    Devolve o texto MASCARADO (piso do C02, sempre) ou levanta `DadoBloqueadoParaLlm`
    se alguma categoria detectada estiver como `bloquear` na política do tenant.

    `conteudo` é o conteúdo da política PUBLICADA lida por porta — nunca uma constante
    importada (achado 8 do UAT #5). Política ausente/silenciosa sobre a categoria cai
    no piso `mascarar`: um conteúdo corrompido nunca pode AFROUXAR o comportamento.
    """
    if not texto:
        return Saneamento(texto, ())
    categorias = categorias_detectadas(texto)
    acoes = _acoes(conteudo)
    bloqueadas = tuple(c for c in categorias if acoes.get(c) == "bloquear")
    if bloqueadas:
        raise DadoBloqueadoParaLlm(
            "A política de IA Responsável do tenant BLOQUEIA o envio ao modelo de texto "
            f"contendo: {', '.join(bloqueadas)}. O dado não saiu da plataforma e a "
            "chamada não foi feita — remova o dado do texto e tente de novo.",
            categorias=bloqueadas,
        )
    return Saneamento(mascarar_pii(texto), categorias)


def _acoes(conteudo: dict[str, Any]) -> dict[str, str]:
    """Ações declaradas, com piso `mascarar` para o que a política não disser.

    O fallback é para o lado SEGURO de propósito: se o conteúdo vier truncado, o pior
    que acontece é mascarar (comportamento de hoje), nunca deixar passar em claro.
    """
    bloco = conteudo.get("dados_llm") if isinstance(conteudo, dict) else None
    acoes = bloco.get("acoes") if isinstance(bloco, dict) else None
    if not isinstance(acoes, dict):
        return dict.fromkeys(CATEGORIAS_PII, "mascarar")
    return {c: acoes.get(c, "mascarar") for c in CATEGORIAS_PII}
