"""Adapter REAL do EmbeddingPort — HubGPU OpenAI-compatible (§3): client `openai` com
`base_url=EMBED_BASE_URL` (o client adiciona o sufixo `/embeddings` — §3) e
`api_key="not-needed"` (proxy autentica por outra via — string literal válida).

Mesmo padrão do LLMHubGPU (adapters/llm/hubgpu.py): fica atrás de `LLM_DEGRADED_MODE`
(§10.6) — `forced_off` → `disponivel()=False` e `embed()` levanta
`EmbeddingIndisponivel` SEM tocar a rede; timeout/erros de API viram
`EmbeddingIndisponivel` (LLMIndisponivel-like → 503 degraded). NUNCA usado em teste
(§1.3.5) — testes usam `adapters/embedding/fake.py`. Client é lazy: nenhuma conexão
na construção do adapter. Vetor com dimensão ≠ `EMBED_DIM` é erro de configuração
(§10.4: mudar a dimensão exige `rag reindex`) — também vira `EmbeddingIndisponivel`
para a busca degradar em vez de corromper a collection.
"""

from typing import Any

from app.config import Settings
from application.ports.embedding import EmbeddingIndisponivel


class EmbeddingHubGPU:
    """Implementa EmbeddingPort — POST {EMBED_BASE_URL}/embeddings, modelo EMBED_MODEL."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any = None

    def disponivel(self) -> bool:
        return self._settings.llm_degraded_mode != "forced_off"

    def _client_lazy(self) -> Any:
        if self._client is None:
            from openai import OpenAI  # import local: adapter nunca carrega em teste

            self._client = OpenAI(
                base_url=self._settings.embed_base_url,
                api_key=self._settings.llm_api_key,  # "not-needed" é válido (§3)
                timeout=self._settings.embed_timeout_s,
                max_retries=self._settings.llm_max_retries,
            )
        return self._client

    def embed(self, textos: list[str]) -> list[list[float]]:
        if not self.disponivel():
            raise EmbeddingIndisponivel(
                "Embeddings em modo degradado (LLM_DEGRADED_MODE=forced_off — §10.6)."
            )
        if not textos:
            return []
        import openai  # lazy, coerente com o client

        try:
            resposta = self._client_lazy().embeddings.create(
                model=self._settings.embed_model, input=textos
            )
        except openai.APIError as erro:
            # §10.6: hub fora do ar/timeout/erro de API é modo degradado, nunca 500.
            raise EmbeddingIndisponivel(
                f"Hub de embeddings inacessível ({type(erro).__name__})."
            ) from erro
        vetores = [list(item.embedding) for item in sorted(resposta.data, key=lambda d: d.index)]
        esperada = self._settings.embed_dim
        if any(len(v) != esperada for v in vetores):
            raise EmbeddingIndisponivel(
                f"Embedding com dimensão fora do EMBED_DIM={esperada} — modelo/config "
                "divergentes; mudar a dimensão exige `python -m app.rag reindex` (§10.4)."
            )
        return vetores
