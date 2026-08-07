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

import json
from collections.abc import Sequence
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

# Import do SUBMÓDULO porque `domain/ia_responsavel/__init__.py` não é arquivo desta
# frente e a re-exportação não foi feita — ver EMENDA SUGERIDA. Funciona igual; a única
# perda é a simetria com os outros quatro enforcements, que vêm do pacote.
from domain.ia_responsavel.retencao import aplicar_retencao_evidencias
from domain.privacidade.sanitizar import mascarar_campos, mascarar_estrutura

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

    def sanear_estrutura(self, valor: Any) -> Any:
        """`sanear` para quem manda ÁRVORE ao prompt (dict/list), não texto corrido.

        Existe porque nem todo prompt da plataforma é string: o Ateliê serializa
        `harness_case.input` e a `entrada` do dry-run com `json.dumps` antes de mandar
        ao modelo (§8-M12). Sem um método AQUI, cada serviço escreveria o próprio
        caminhamento da árvore — e caminhamento duplicado é exatamente como o
        `kv_master` (dicionário aninhado) escapou inteiro da retenção na onda 3.

        São dois passos, nenhum reimplementado neste arquivo:

        1. **detectar e BLOQUEAR sobre o JSON inteiro** — `self.sanear` é a mesma porta
           de sempre, e serializar garante que nenhuma string do galho escape da
           varredura. Detectar sobre o texto serializado é MAIS abrangente que detectar
           string a string (um CPF partido entre dois valores é pego); errar para o lado
           de bloquear demais é a direção certa num controle de privacidade.
        2. **mascarar com a CHAVE servindo de âncora** — `mascarar_campos` (§10.2), a
           MESMA função que o intake usa em `pedido.conteudo`. Ver abaixo por que não é
           `mascarar_estrutura`.

        `default=str` porque a serialização aqui é MEIO de varredura, não contrato: um
        `UUID` no galho não pode levantar `TypeError` e derrubar a rota — o portão que
        quebra com dado exótico vira o portão que alguém desliga.

        ## Por que a árvore do Ateliê é DIGITAÇÃO, e não contrato (auditoria da onda 3c)

        A primeira versão deste método mascarava com `mascarar_estrutura`, que por
        contrato **não olha a chave e não mascara a chave** — o certo para payload de
        evento e trace, onde a chave é nome de campo do §4.1. Só que a `entrada` do
        dry-run e o `harness_case.input` são `dict[str, Any]` ABERTO, digitado na tela
        do T16: quem escolhe o nome do campo é o analista. É a mesma forma do
        `pedido.conteudo`, e a auditoria mediu o preço de tratá-la como contrato — 10 de
        14 árvores de PII brasileira realista chegavam INTEIRAS ao prompt:

        * `{"nome do titular": "Maria da Conceição Souza"}` — a âncora está na CHAVE e o
          dado no valor; mascarar cada string isolada perde exatamente o sinal que torna
          o nome reconhecível (é o argumento que `mascarar_campos` já documenta);
        * `{"cep": "01310100"}`, `{"rg": "1234567"}`, `{"data de nascimento": ...}` —
          idem, e são a forma REAL do cadastro de telco;
        * `{"dados do titular": {"nome completo": "..."}}` — aninhado, e `mascarar_campos`
          desce mantendo a âncora;
        * `{"contato joao@x.com.br": "10%"}` — PII na CHAVE, que `mascarar_estrutura`
          devolve intacta. É o achado 9 do UAT #5 renascido nesta rota.

        O piso não mudou para quem manda árvore de CONTRATO: chave não-`str` (ou raiz que
        não é dicionário) continua indo por `mascarar_estrutura`.

        ## Por que a varredura tira ASPAS e `_` antes de detectar

        Mascarar e BLOQUEAR são dois enforcements do mesmo parâmetro (a), e eles não
        podem divergir: uma rota que mascara `nome` mas não honra `nome: bloquear` deixa
        a requisição SEGUIR quando o DPO mandou recusar — menos estrito que o publicado,
        e em silêncio. A auditoria mediu essa divergência aqui, e a causa é de texto:

        * as âncoras de contexto pedem `[\\s:\\-–—]{1,3}` entre rótulo e dado, e o que
          `json.dumps` põe ali é `": "` — com ASPAS, que não estão no separador. Então
          `nome do titular` nunca ficava adjacente a `Maria` e a varredura não via nada;
        * `_` é caractere de PALAVRA, então em `nome_do_titular` nem `\\btitular` existe.
          É a mesma normalização que `mascarar_pii_em_campo` já faz do lado do
          mascaramento — sem ela, a forma DOMINANTE de chave de JSON mascarava e não
          bloqueava.

        As duas trocas colam `chave: valor` e devolvem a âncora. O texto resultante é
        MEIO de varredura e nunca é retornado (mesmo argumento do `default=str`), então
        corromper um valor que contenha aspa ou `_` não tem efeito observável; e o erro
        que elas podem introduzir é detectar DEMAIS, que é a direção em que este
        controle deve errar. `-` NÃO é trocado de propósito: ele já está no separador, e
        removê-lo apagaria as bordas `(?<![-\\w])` que protegem `OS-2026-0457` de virar
        telefone/CEP (falso positivo do C02 que a suíte cobra).
        """
        varredura = json.dumps(valor, ensure_ascii=False, default=str)
        self.sanear(varredura.replace('"', "").replace("_", " "))
        if isinstance(valor, dict) and all(isinstance(chave, str) for chave in valor):
            return mascarar_campos(valor)
        return mascarar_estrutura(valor)

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

    def reter_evidencias(self, evidencias: Sequence[Any]) -> list[Any]:
        """Redige a COLUNA `invocacao.evidencias` (§4.1) conforme a retenção (§10.4).

        Terceiro método porque `evidencias` é a TERCEIRA coluna de conteúdo do ledger, e
        era a única que política nenhuma alcançava: `reter_output` embrulha o dicionário
        `output`, e o serviço atribuía `evidencias=` ao lado, FORA do portão. Com
        `reter_* = false` publicado, a auditoria lia `[SUPRIMIDO...]` no `output` e o
        texto livre do modelo intacto na coluna vizinha — supressão em que se acredita e
        que não aconteceu.

        Alternativa considerada e recusada: `reter_output` passar a receber o registro
        inteiro. Ela obrigaria os seis serviços a mudar de forma no mesmo commit e faria
        o portão conhecer o dataclass `Invocacao` — hoje ele só vê payloads, e é isso
        que o mantém em uma linha por enforcement, sem regra própria. Uma coluna de
        conteúdo, um método: a ausência do terceiro é o que a revisão do próximo serviço
        consegue ver, que é o mesmo argumento pelo qual o portão existe.
        """
        return aplicar_retencao_evidencias(evidencias, self.conteudo)


def de(publicacoes: PublicacoesIaPort, tenant_id: str | None = None) -> PortaoIa:
    """Portão do tenant a partir da política PUBLICADA — a única fonte em runtime.

    Nome curto porque o call site vira `portao_ia.de(self._publicacoes_ia, tenant_id)`,
    que se lê como frase e deixa explícito, na linha, que a política veio de uma porta.
    """
    return PortaoIa(politica_ia_vigente(publicacoes, tenant_id))
