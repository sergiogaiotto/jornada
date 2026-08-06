"""Portão de IA Responsável no CAMINHO DE EXECUÇÃO — onde a política vira comportamento.

A onda 3 entregou `domain/ia_responsavel/` com quatro parâmetros cujo enforcement estava
provado por inversão, e o auditor mediu o que faltava: **nada fora do próprio teste
importava o módulo**. Quatro funções puras que ninguém chamava — a um commit de virar o
achado 8 do UAT #5 (tela publica, portão ignora), que é justamente o achado do qual o
módulo nasceu. Este arquivo é a fiação: é por aqui que a política PUBLICADA passa a
interromper, mascarar e redigir de verdade.

## Por que um portão, e não quatro chamadas soltas por serviço

São seis serviços e catorze `LLMPort.chat` no caminho de usuário. Espalhar quatro
chamadas de domínio por cada um deles significa que o sétimo serviço — o que ainda não
existe — nasce sem nenhuma, em silêncio: exatamente o modo de falha que `erros.py`
descreve ("um `if` que alguém esquece de escrever no próximo endpoint"). Com um portão,
o serviço novo precisa de UM objeto para chamar o LLM, e a revisão vê a ausência dele.

O portão NÃO reimplementa regra: cada método é uma linha delegando ao domínio puro. Ele
existe para **carregar a política uma vez por requisição** e emprestá-la aos quatro
enforcements — não para ter opinião própria.

## Uma leitura por requisição, e por quê

`de(publicacoes, tenant_id)` lê a porta UMA vez e congela o `conteudo` no objeto. Isso é
correção, não performance: uma requisição que sanea o prompt com a política v3 e grava o
ledger com a v4 (publicada no meio do caminho) produz uma linha de auditoria que não
corresponde a nenhuma política que existiu. O snapshot por requisição faz a invocação
inteira ser julgada por uma política só.

Não há cache ENTRE requisições, de propósito: apertar privacidade tem de valer no
próximo request, não quando um TTL expirar. A política de IA não é congelada por OS
(ver `domain/ia_responsavel/modelos.py`) pela mesma razão.

## O que este módulo deliberadamente NÃO faz

Não importa a SEMENTE da política nem o módulo que a define — o guarda-corpo de CI
(`test_nenhum_servico_importa_a_seed_direto`) falha se algum serviço o fizer, porque
semente compilada em serviço É o achado 8. O default conservador é materializado no
adapter (`adapters/publicacoes.py`), atrás da porta.

Nota para quem editar este arquivo: aquele guarda-corpo casa SUBSTRING no texto do
arquivo inteiro, então nem mencionar o nome da semente em prosa é permitido aqui. É
estrito de propósito e o preço é este comentário; a alternativa (checar só linhas de
`import`) deixaria passar um `getattr` ou um import adiado, que é como a constante
voltaria a governar sem ninguém ver.
"""

from dataclasses import dataclass
from typing import Any

from application.ports.publicacoes_ia import PublicacoesIaPort, politica_ia_vigente
from domain.ia_responsavel import (
    ACOES_VIA_AI,
    Saneamento,
    aplicar_retencao,
    exigir_perfil_autorizado,
    exigir_revisao_humana,
    pode_aplicar_sozinho,
    sanear_para_llm,
)

# Ações do Art. 20 que ESTA onda fiou, nomeadas em vez de digitadas no call site.
#
# O motivo é a direção do erro: `modo_de_decisao` devolve `"propor"` para ação
# desconhecida (defesa em profundidade do domínio, e o lado seguro). Só que, com string
# solta no serviço, um typo — `"jornada.ajusta"` — viraria "nunca automatiza" em
# SILÊNCIO: o DPO publicaria a autorização, a tela confirmaria e nada mudaria. É a
# mesma falha que `politica._erros_modelos` rejeita no lado da publicação (o typo
# `enginer`), e ela merece a mesma rejeição no lado do consumo.
ACAO_JORNADA_AJUSTAR = "jornada.ajustar"  # §8-M7 · o "propõe, humano aplica" do twin

_DESCONHECIDAS = {ACAO_JORNADA_AJUSTAR} - set(ACOES_VIA_AI)
if _DESCONHECIDAS:  # falha no IMPORT: o CI pega, não a produção
    raise ValueError(
        f"Ação fora do vocabulário fechado ACOES_VIA_AI: {sorted(_DESCONHECIDAS)}. "
        "Enforcement de decisão automatizada com nome que a política não conhece "
        "seria autorização publicada e inerte (§10.2)."
    )

# O conjunto das ações que ALGUÉM de fato consulta — o outro sentido do guarda-corpo.
#
# `_DESCONHECIDAS` cobre o erro de digitação: enforcement citando ação que a política
# não conhece. Ele NÃO cobre o inverso, que é o mais caro e o que esta onda encontrou
# medindo: ação que a política ACEITA publicar e que nenhum serviço consulta. Das sete
# de `ACOES_VIA_AI`, só esta é lida em runtime; para as outras seis o DPO publica
# `pode_aplicar_sozinho`, a API responde 201, a tela mostra a versão nova com autor e
# data — e o comportamento da plataforma não muda em nada. É a forma exata do achado 8
# do UAT #5, sobrevivendo DENTRO do módulo que nasceu para matá-lo, só que na
# granularidade do vocabulário em vez da do parâmetro.
#
# Exportado (sem `_`) porque quem precisa dele é o guarda-corpo de aceite: manter a
# contagem aqui, ao lado do único call site, é o que faz a lista encolher junto com a
# fiação em vez de virar documentação que envelhece sozinha. Ver a EMENDA SUGERIDA do
# relatório desta onda sobre encolher `ACOES_VIA_AI` até a fiação existir.
ACOES_FIADAS: frozenset[str] = frozenset({ACAO_JORNADA_AJUSTAR})


@dataclass(frozen=True)
class PortaoIa:
    """Política de IA vigente de UM tenant + os quatro enforcements que ela governa.

    `frozen` porque o conteúdo é um snapshot da requisição: um serviço que conseguisse
    reatribuir `conteudo` no meio do fluxo recriaria o problema que o snapshot resolve.
    """

    conteudo: dict[str, Any]

    # ------------------------------------------------ (a) dados que podem ir ao LLM
    def sanear(self, texto: str) -> str:
        """Texto livre pronto para o prompt — substituto direto de `mascarar_pii`.

        Mesmo comportamento de hoje no default (mascarar tudo, §10.2/C02); levanta
        `DadoBloqueadoParaLlm` se a política do tenant marcar como `bloquear` alguma
        categoria detectada. É a troca que faz o parâmetro (a) existir fora do teste.
        """
        return sanear_para_llm(texto, self.conteudo).texto

    def sanear_detalhado(self, texto: str) -> Saneamento:
        """Texto saneado + categorias detectadas, para quem alimenta ledger/trace.

        As CATEGORIAS (nunca os valores) são o que permite a auditoria afirmar "havia
        CPF neste pedido e ele foi mascarado" sem que o CPF exista em lugar nenhum.
        """
        return sanear_para_llm(texto, self.conteudo)

    # --------------------------------------------- (f) modelos permitidos por agente
    def autorizar_modelo(self, agente: str, perfil: str) -> None:
        """Confere o perfil do roster §7.2 contra a política ANTES de `LLMPort.chat`.

        Chamado no ponto da chamada, não no carregamento da skill: um caminho que monte
        o perfil dinamicamente escaparia de um portão posicionado antes (`modelos_llm`
        documenta o porquê).
        """
        exigir_perfil_autorizado(agente, perfil, self.conteudo)

    # ------------------------------------------------ (c) decisão automatizada Art. 20
    def exigir_revisao_humana(self, acao: str) -> None:
        """Recusa o caminho de aplicação AUTOMÁTICA quando a política não o abre."""
        exigir_revisao_humana(acao, self.conteudo)

    def pode_aplicar_sozinho(self, acao: str) -> bool:
        """Booleano para quem escolhe ENTRE dois caminhos em vez de recusar um."""
        return pode_aplicar_sozinho(acao, self.conteudo)

    # ------------------------------------------------------------------ (b) retenção
    def reter_input(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        """Redige o `input` da invocação conforme `reter_prompt` (§10.4)."""
        return aplicar_retencao(payload, self.conteudo, tipo="input")

    def reter_output(self, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        """Redige o `output` da invocação conforme `reter_resposta` (§10.4)."""
        return aplicar_retencao(payload, self.conteudo, tipo="output")


def de(publicacoes: PublicacoesIaPort, tenant_id: str | None = None) -> PortaoIa:
    """Portão do tenant a partir da política PUBLICADA — a única fonte em runtime.

    Nome curto porque o call site vira `portao_ia.de(self._publicacoes_ia, tenant_id)`,
    que se lê como frase e deixa explícito, na linha, que a política veio de uma porta.
    """
    return PortaoIa(politica_ia_vigente(publicacoes, tenant_id))
