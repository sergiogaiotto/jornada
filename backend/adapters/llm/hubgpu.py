"""Adapter REAL do LLMPort — HubGPU OpenAI-compatible (§3): client `openai` com base_url
custom e `api_key="not-needed"` (o proxy autentica por outra via — string literal válida).

Fica atrás de `LLM_DEGRADED_MODE` (§10.6): `forced_off` → `disponivel()=False` e `chat()`
levanta `LLMIndisponivel` SEM tocar a rede. NUNCA usado em teste (§1.3.5) — testes usam
`adapters/llm/fake.py`. Client é lazy: nenhuma conexão na construção do adapter.
"""

from typing import Any

from app.config import Settings
from application.ports.llm import LLMIndisponivel, PerfilModelo


class LLMHubGPU:
    """Implementa LLMPort; roteamento por perfil (§3): 120b e 20b têm base_url/model próprios."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._clients: dict[str, Any] = {}

    def disponivel(self) -> bool:
        return self._settings.llm_degraded_mode != "forced_off"

    def _config(self, perfil: PerfilModelo) -> tuple[str, str]:
        """(base_url, model) do perfil — POST {base_url}/chat/completions (§3)."""
        if perfil == "120b":
            return self._settings.llm_120b_base_url, self._settings.llm_120b_model
        return self._settings.llm_20b_base_url, self._settings.llm_20b_model

    def _client(self, perfil: PerfilModelo) -> Any:
        if perfil not in self._clients:
            from openai import OpenAI  # import local: adapter nunca carrega em teste

            base_url, _ = self._config(perfil)
            self._clients[perfil] = OpenAI(
                base_url=base_url,
                api_key=self._settings.llm_api_key,  # "not-needed" é válido (§3)
                timeout=self._settings.llm_timeout_s,
                max_retries=self._settings.llm_max_retries,
            )
        return self._clients[perfil]

    def chat(self, mensagens: list[dict[str, str]], *, perfil: PerfilModelo = "20b") -> str:
        if not self.disponivel():
            raise LLMIndisponivel(
                "LLM em modo degradado (LLM_DEGRADED_MODE=forced_off — §10.6); "
                "use o modo manual da UI."
            )
        _, model = self._config(perfil)
        import openai  # lazy, coerente com o client

        try:
            resposta = self._client(perfil).chat.completions.create(model=model, messages=mensagens)
        except (openai.APITimeoutError, openai.APIConnectionError) as erro:
            # §10.6: hub fora do ar/inacessível é modo degradado (503), nunca 500.
            raise LLMIndisponivel(
                f"Hub LLM inacessível ({type(erro).__name__}); use o modo manual da UI."
            ) from erro
        return resposta.choices[0].message.content or ""
