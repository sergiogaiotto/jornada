"""Configuração via pydantic-settings — espelha o .env do SDD §3.1.

Regras relevantes:
- §10.3: `APP_SECRET` obrigatório ≠ default quando `APP_ENV=prod` (startup falha).
- §3: api_key "not-needed" é válida (o proxy HubGPU autentica por outra via).
"""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_env: Literal["dev", "homolog", "prod"] = "dev"
    app_secret: str = "change-me"
    app_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:5173"
    default_tenant: str = "torre-movel"

    # --- Banco ---
    database_url: str = "postgresql+asyncpg://jornada:jornada@db:5432/jornada"

    # --- LLM HubGPU (OpenAI-compatible) ---
    llm_120b_base_url: str = "https://hub-gpus.claro.com.br/gpt120/v1"
    llm_120b_model: str = "openai/gpt-oss-120b"
    llm_20b_base_url: str = "https://hub-gpus.claro.com.br/gpt20/v1"
    llm_20b_model: str = "openai/gpt-oss-20b"
    llm_api_key: str = "not-needed"
    llm_timeout_s: int = 300
    llm_max_retries: int = 2
    llm_degraded_mode: Literal["auto", "forced_off"] = "auto"

    # --- Embeddings ---
    embed_base_url: str = "https://hub-gpus.claro.com.br/embed06b/v1"
    embed_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embed_dim: int = 1024
    rag_collection: str = "agente_evidence"

    # --- SFMC (dev aponta para o mock) ---
    sfmc_auth_url: str = "http://mock-sfmc:8080/v2/token"
    sfmc_rest_url: str = "http://mock-sfmc:8080/rest"
    sfmc_soap_url: str = "http://mock-sfmc:8080/soap"
    sfmc_client_id: str = "mock"
    sfmc_client_secret: str = "mock"
    sfmc_account_mid: str = "mock"
    sfmc_api_budget_per_apply: int = 200

    # --- Data Cloud (dev aponta para o mock) ---
    dc_auth_url: str = "http://mock-datacloud:8081/oauth/token"
    dc_api_url: str = "http://mock-datacloud:8081/api/v2"
    dc_client_id: str = "mock"
    dc_client_secret: str = "mock"

    # --- Notificações / dev ---
    smtp_url: str = "smtp://mailpit:1025"
    teams_webhook_url: str = ""
    demo_mode: bool = True

    # --- Observabilidade (Langfuse self-hosted — §10.8) ---
    langfuse_host: str = "http://langfuse:3000"
    langfuse_public_key: str = "pk-lf-dev"
    langfuse_secret_key: str = "sk-lf-dev"
    langfuse_enabled: bool = True

    @model_validator(mode="after")
    def _prod_exige_secret_real(self) -> "Settings":
        if self.app_env == "prod" and self.app_secret == "change-me":
            raise ValueError("APP_SECRET deve ser diferente do default em APP_ENV=prod (SDD §10.3)")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
