"""Erros do contexto `ia_responsavel` — cada um é um ENFORCEMENT (§10.2, LGPD Art. 20).

Todos herdam de `ErroDominio` (que já guarda `motivo`), para que a camada de API os
traduza pelo mapa RFC-7807 existente sem exceção especial.

O ponto destes erros é serem LEVANTADOS. Um parâmetro de IA Responsável que apenas
devolve `False` e deixa o chamador decidir vira conselho — e conselho é exatamente o
que o achado 8 do UAT #5 classificou como teatro auditável. Aqui a política INTERROMPE
o fluxo; quem quiser seguir precisa mudar a política, e mudar a política é um ato
versionado, com autor e data.
"""

from domain.campanha.erros import ErroDominio


class PoliticaIaInvalida(ErroDominio):
    """Conteúdo fora do conjunto FECHADO de campos (padrão do parser §7.1: erros
    ACUMULADOS, nunca só o primeiro que aparecer)."""

    def __init__(self, motivo: str, *, erros: list[str]) -> None:
        super().__init__(motivo)
        self.erros = erros


class DadoBloqueadoParaLlm(ErroDominio):
    """A política do tenant marca como `bloquear` uma categoria de PII detectada no
    texto: a chamada ao LLM NÃO acontece (§10.2).

    Mascarar deixa o texto sair do perímetro (marcado, mas sai); bloquear é a única
    ação que impede a saída. Por isso as duas ações não são intercambiáveis.
    """

    def __init__(self, motivo: str, *, categorias: tuple[str, ...]) -> None:
        super().__init__(motivo)
        self.categorias = categorias


class DecisaoAutomatizadaNegada(ErroDominio):
    """LGPD Art. 20: a ação não está na allowlist `pode_aplicar_sozinho`, logo a IA
    PROPÕE e um humano aplica.

    Levantar aqui é o que transforma a convenção de código do `ajustar` (§8-M7 devolve
    `aplicado: False` porque alguém escreveu isso na mão) em política revisável pelo
    DPO — hoje, para automatizar, basta um dev trocar um literal.
    """

    def __init__(self, motivo: str, *, acao: str) -> None:
        super().__init__(motivo)
        self.acao = acao


class ModeloNaoPermitido(ErroDominio):
    """O perfil de modelo pedido não consta na lista do agente (roster §7.2)."""

    def __init__(self, motivo: str, *, agente: str, perfil: str) -> None:
        super().__init__(motivo)
        self.agente = agente
        self.perfil = perfil


class TetoDeTokensExcedido(ErroDominio):
    """O gasto MEDIDO do tenant no dia atingiu `teto_tokens.tokens_por_dia` (J02): a
    chamada ao modelo NÃO foi feita — recusada ANTES de custar, como o 429 do limite
    de login (a requisição está correta e autorizada; o orçamento é que acabou).

    Semântica gate-on-entry, declarada: a chamada que COMEÇA abaixo do teto completa
    (o custo dela só é conhecido depois); a próxima é recusada. O reset é a virada do
    dia UTC."""

    def __init__(self, motivo: str, *, gasto: int, teto: int) -> None:
        super().__init__(motivo)
        self.gasto = gasto
        self.teto = teto
