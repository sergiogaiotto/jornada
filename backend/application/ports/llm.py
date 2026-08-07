"""LLMPort — porta do LLM HubGPU (§2.1, §3): roteamento por perfil 120b|20b.

Contrato: `chat()` recebe mensagens estilo OpenAI (`[{role, content}]`) e devolve
`RespostaLLM(texto, tokens)`. Indisponibilidade (hub fora ou
`LLM_DEGRADED_MODE=forced_off` — §10.6) → `LLMIndisponivel`; a camada de API traduz
para 503 `degraded`. Testes usam SEMPRE o adapter fake (adapters/llm/fake.py) — o hub
real NUNCA é chamado em teste (§1.3.5).

Emenda I04 (onda 5): o retorno vira NamedTuple para o `usage` do provedor FLUIR até
`invocacao.tokens` — a coluna existia desde a 0001, a persistência funcionava, e o
valor morria aqui na porta: `chat()` devolvia só a string e o §10.8 ("tokens/latência
espelhados na tabela invocacao") ficava cumprido pela metade. O MÉTODO mantém o nome
`chat` de propósito: o vigia F03 (test_F03_vigia_portao_llm) identifica call sites por
`no.func.attr == "chat"` — um método novo (`chat_com_uso`) escaparia dele. `tokens` é
Optional e viaja NO RETORNO, nunca em estado do adapter: `app.state.llm` é UM adapter
compartilhado entre threads (ver DisjuntorHub) — "último usage" seria race condition.
"""

from typing import Literal, NamedTuple, Protocol, runtime_checkable

PerfilModelo = Literal["120b", "20b"]  # §3: 120B especialistas/judge; 20B triagens/resumos


class RespostaLLM(NamedTuple):
    """Retorno de `chat()`: o texto e o total de tokens reportado pelo provedor.

    `tokens=None` quando o hub não manda `usage` (proxies às vezes suprimem) — usage
    ausente JAMAIS vira falha (§10.6: degradar, nunca 500). Desempacota como tupla
    (`texto, tokens = ...`) e `.texto`/`.tokens` nomeiam nos serviços."""

    texto: str
    tokens: int | None = None


class LLMIndisponivel(RuntimeError):
    """Hub indisponível ou modo degradado forçado (§10.6) — API responde 503 degraded."""


def soma_tokens(*valores: int | None) -> int | None:
    """Agrega o `usage` de VÁRIAS chamadas numa linha de ledger (retry §7.3, exec+judge
    do Ateliê, as 2 chamadas do consultor): soma os medidos; todos None → None — a
    métrica auditável de custo nunca subrepresenta fingindo zero."""
    presentes = [v for v in valores if v is not None]
    return sum(presentes) if presentes else None


@runtime_checkable
class LLMPort(Protocol):
    def disponivel(self) -> bool:
        """False em modo degradado (§10.6); caminho crítico nunca depende disto."""
        ...

    def chat(self, mensagens: list[dict[str, str]], *, perfil: PerfilModelo = "20b") -> RespostaLLM:
        """Completions de chat OpenAI-compatible; levanta LLMIndisponivel se degradado."""
        ...
