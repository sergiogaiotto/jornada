"""EmbeddingPort — porta de embeddings do hub (§3, §7.4): Qwen3 via endpoint
OpenAI-compatible (`POST {EMBED_BASE_URL}/embeddings`, modelo `EMBED_MODEL`,
dimensão `EMBED_DIM`).

Contrato: `embed()` recebe uma lista de textos e devolve um vetor por texto, NA MESMA
ORDEM. Indisponibilidade (hub fora, timeout, `LLM_DEGRADED_MODE=forced_off` — §10.6)
→ `EmbeddingIndisponivel`, que HERDA de `LLMIndisponivel`: os handlers de rota que já
traduzem LLM degradado para 503 `degraded` cobrem embeddings sem código novo. Testes
usam SEMPRE o adapter fake (adapters/embedding/fake.py) — o hub real NUNCA é chamado
em teste (§1.3.5).
"""

from typing import Protocol, runtime_checkable

from application.ports.llm import LLMIndisponivel


class EmbeddingIndisponivel(LLMIndisponivel):
    """Hub de embeddings indisponível/timeout ou modo degradado forçado (§10.6)."""


@runtime_checkable
class EmbeddingPort(Protocol):
    def disponivel(self) -> bool:
        """False em modo degradado (§10.6); RAG degrada suave — nunca derruba o agente."""
        ...

    def embed(self, textos: list[str]) -> list[list[float]]:
        """Um vetor (dim `EMBED_DIM`) por texto, na ordem de entrada; levanta
        `EmbeddingIndisponivel` se o hub estiver fora/degradado."""
        ...
