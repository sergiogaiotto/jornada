"""(c) DECISÃO AUTOMATIZADA — enforcement do parâmetro `decisao_automatizada`.

LGPD Art. 20: o titular tem direito a revisão de decisões tomadas unicamente com base
em tratamento automatizado. Hoje a plataforma respeita isso por CONVENÇÃO: o `ajustar`
do twin (§8-M7) devolve `aplicado: False` e o `optimize` (§8-M11) devolve proposta,
porque alguém escreveu esses literais na mão. Nada impede o próximo commit de trocar
`False` por `True` — e nenhuma tela, nenhum log e nenhum DPO ficariam sabendo.

Aqui a convenção vira política: uma allowlist versionada, com autor e data. O default
é a lista VAZIA — tudo propõe, nada aplica sozinho —, então publicar a v1 preserva
exatamente o comportamento atual, e qualquer automação futura passa a exigir um ato
humano registrado.

Nota de fronteira: este módulo governa "a IA pode APLICAR sozinha?". Ele não substitui
os portões determinísticos (Guard §1.1.2, pré-voo §8-M9) nem a segregação
criador/aprovador (§10.5) — automatizar uma ação aqui nunca dispensa aqueles gates,
que continuam valendo depois. Autorizar `jornada.ajustar` significa "o diff entra sem
clique humano", não "o disparo dispensa aprovação".
"""

from typing import Any, Literal

from domain.ia_responsavel.erros import DecisaoAutomatizadaNegada
from domain.ia_responsavel.politica import ACOES_VIA_AI

ModoDecisao = Literal["propor", "aplicar"]


def modo_de_decisao(acao: str, conteudo: dict[str, Any]) -> ModoDecisao:
    """`aplicar` se a ação está na allowlist do tenant; `propor` caso contrário.

    Ação fora do vocabulário `ACOES_VIA_AI` devolve `propor`: o desconhecido nunca é
    automatizado. `validar_conteudo` já recusa a publicação de ação desconhecida, mas
    a função não depende disso — defesa em profundidade, porque o conteúdo pode vir de
    uma linha antiga do banco gravada antes de a validação existir.
    """
    if acao not in ACOES_VIA_AI:
        return "propor"
    return "aplicar" if acao in _allowlist(conteudo) else "propor"


def pode_aplicar_sozinho(acao: str, conteudo: dict[str, Any]) -> bool:
    """Açúcar de leitura para os pontos que só querem o booleano."""
    return modo_de_decisao(acao, conteudo) == "aplicar"


def exigir_revisao_humana(acao: str, conteudo: dict[str, Any]) -> None:
    """Levanta `DecisaoAutomatizadaNegada` se a ação NÃO puder ser aplicada sozinha.

    É a forma imperativa, para o serviço chamar antes de aplicar qualquer coisa: o
    caminho de aplicação automática só existe se a política abrir. Sem isto, o
    parâmetro viraria um `if` que alguém esquece de escrever no próximo endpoint.
    """
    if not pode_aplicar_sozinho(acao, conteudo):
        raise DecisaoAutomatizadaNegada(
            f"LGPD Art. 20: {acao!r} não está autorizada a ser aplicada automaticamente "
            "pela política de IA Responsável deste tenant — a IA PROPÕE e uma pessoa "
            "aplica. Para automatizar, publique uma versão nova da política.",
            acao=acao,
        )


def _allowlist(conteudo: dict[str, Any]) -> frozenset[str]:
    """Allowlist declarada; qualquer forma inesperada vira conjunto VAZIO.

    Conteúdo corrompido resulta em "tudo propõe" — o lado seguro. Um `dict` no lugar da
    lista, por exemplo, não pode acabar liberando automação por acidente de parsing.
    """
    bloco = conteudo.get("decisao_automatizada") if isinstance(conteudo, dict) else None
    acoes = bloco.get("pode_aplicar_sozinho") if isinstance(bloco, dict) else None
    if not isinstance(acoes, list):
        return frozenset()
    return frozenset(a for a in acoes if isinstance(a, str))
