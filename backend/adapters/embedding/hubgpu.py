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

Frente 1: ganha o `DisjuntorHub` do §10.7, o MESMO do adapter de LLM (importado de lá —
ver a nota abaixo). O `except openai.APIError` já estava certo aqui desde sempre; era o
adapter de LLM que capturava só `(APITimeoutError, APIConnectionError)` e deixava
429/5xx virarem 500. Este arquivo era a referência do conserto de lá.

Nota de estrutura: `DisjuntorHub` vem de `adapters.llm.hubgpu` porque os dois adapters
falam com o MESMO hub e a frente 1 não abre arquivo fora do seu escopo — duplicar a
classe seria pior (dois disjuntores divergindo em manutenção). EMENDA SUGERIDA:
promover `DisjuntorHub` para `backend/adapters/circuito.py`, de onde os dois importam
sem que um adapter dependa do outro.
"""

from typing import Any

from adapters.llm.hubgpu import DisjuntorHub
from adapters.relogio import RelogioSistema
from app.config import Settings
from application.ports.clock import ClockPort
from application.ports.embedding import EmbeddingIndisponivel


class EmbeddingHubGPU:
    """Implementa EmbeddingPort — POST {EMBED_BASE_URL}/embeddings, modelo EMBED_MODEL."""

    def __init__(self, settings: Settings, relogio: ClockPort | None = None) -> None:
        self._settings = settings
        self._client: Any = None
        # `relogio` opcional para não quebrar `EmbeddingHubGPU(settings)` (app/main.py,
        # app/rag.py, api/v1/intake.py); o teste injeta relógio fixo e prova o meio-aberto.
        self._disjuntor = DisjuntorHub(relogio or RelogioSistema(), rotulo="hub de embeddings")

    @property
    def disjuntor(self) -> DisjuntorHub:
        return self._disjuntor

    def disponivel(self) -> bool:
        """`False` também com o circuito ABERTO (§10.7): durante o cooldown a busca
        semântica degrada suave em vez de mandar cada request esperar o timeout."""
        return self._settings.llm_degraded_mode != "forced_off" and not self._disjuntor.aberto()

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
        if self._settings.llm_degraded_mode == "forced_off":
            raise EmbeddingIndisponivel(
                "Embeddings em modo degradado (LLM_DEGRADED_MODE=forced_off — §10.6)."
            )
        if not textos:
            return []
        if not self._disjuntor.permite_chamada():
            # §10.7: circuito aberto NÃO toca a rede.
            raise EmbeddingIndisponivel(self._disjuntor.motivo())
        import openai  # lazy, coerente com o client

        try:
            resposta = self._client_lazy().embeddings.create(
                model=self._settings.embed_model, input=textos
            )
        except openai.APIError as erro:
            # §10.6: hub fora do ar/timeout/429/5xx é modo degradado, nunca 500.
            self._disjuntor.registrar_falha()
            raise EmbeddingIndisponivel(
                f"Hub de embeddings inacessível ({type(erro).__name__})."
            ) from erro
        self._disjuntor.registrar_sucesso()
        vetores = [list(item.embedding) for item in sorted(resposta.data, key=lambda d: d.index)]
        esperada = self._settings.embed_dim
        if any(len(v) != esperada for v in vetores):
            # NÃO conta falha para o disjuntor: o hub RESPONDEU, e bem. Isto é erro de
            # CONFIGURAÇÃO (EMBED_MODEL trocado sem `rag reindex` — §10.4), e abrir o
            # circuito esconderia a causa atrás de um "hub indisponível" que nunca passa:
            # o cooldown venceria, a sonda voltaria com a mesma dimensão errada, e o
            # operador ficaria caçando rede quando o problema é o `.env`.
            raise EmbeddingIndisponivel(
                f"Embedding com dimensão fora do EMBED_DIM={esperada} — modelo/config "
                "divergentes; mudar a dimensão exige `python -m app.rag reindex` (§10.4)."
            )
        return vetores
