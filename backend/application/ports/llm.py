"""LLMPort — porta do LLM HubGPU (§2.1, §3): roteamento por perfil 120b|20b.

Contrato: `chat()` recebe mensagens estilo OpenAI (`[{role, content}]`) e devolve o texto
da resposta. Indisponibilidade (hub fora ou `LLM_DEGRADED_MODE=forced_off` — §10.6) →
`LLMIndisponivel`; a camada de API traduz para 503 `degraded`. Testes usam SEMPRE o
adapter fake (adapters/llm/fake.py) — o hub real NUNCA é chamado em teste (§1.3.5).
"""

from typing import Literal, Protocol, runtime_checkable

PerfilModelo = Literal["120b", "20b"]  # §3: 120B especialistas/judge; 20B triagens/resumos


class LLMIndisponivel(RuntimeError):
    """Hub indisponível ou modo degradado forçado (§10.6) — API responde 503 degraded."""


@runtime_checkable
class LLMPort(Protocol):
    def disponivel(self) -> bool:
        """False em modo degradado (§10.6); caminho crítico nunca depende disto."""
        ...

    def chat(self, mensagens: list[dict[str, str]], *, perfil: PerfilModelo = "20b") -> str:
        """Completions de chat OpenAI-compatible; levanta LLMIndisponivel se degradado."""
        ...
