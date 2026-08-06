"""Configuração via pydantic-settings — espelha o .env do SDD §3.1.

Regras relevantes:
- §10.3: `APP_SECRET` obrigatório ≠ default quando `APP_ENV=prod` (startup falha).
- §3: api_key "not-needed" é válida (o proxy HubGPU autentica por outra via).
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
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

    # --- Identidade & sessão (emenda G01 — §8-M0) ---
    # `session_cookie_secure` é CONFIGURAÇÃO, não constante: hoje a VPS serve HTTP puro
    # e um cookie Secure simplesmente não seria enviado (login quebrado); com o TLS na
    # frente basta SESSION_COOKIE_SECURE=true, sem release de código. Hardcodar
    # qualquer um dos dois lados é escolher entre "não funciona agora" e "nunca liga".
    session_cookie_nome: str = "jornada_sessao"
    session_cookie_secure: bool = False
    session_ttl_horas: int = 12
    login_max_tentativas: int = 5
    login_bloqueio_minutos: int = 15
    # Tokens estáticos `dev-<papel>`/`portal-dev` (§8-M0). Em dev valem sempre; fora de
    # dev só com opt-in EXPLÍCITO — e em prod nem com opt-in (validador abaixo).
    permitir_tokens_dev: bool = False
    # Bootstrap do root (§8-M0 — emenda G01). O e-mail/login não é segredo; a senha é
    # `SecretStr` para nunca aparecer em repr/log/traceback, e o serviço a descarta da
    # memória depois de gerar o hash.
    jornada_root_email: str = ""
    jornada_root_senha: SecretStr = SecretStr("")

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
    embed_timeout_s: int = 30
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

    @model_validator(mode="after")
    def _prod_proibe_tokens_dev(self) -> "Settings":
        """Fail-fast de startup no MESMO padrão do APP_SECRET (§10.3) — fecha o achado
        do UAT #5: `dev-admin` é uma senha publicada no repositório.

        O par `Authorization: Bearer dev-admin` sempre existiu em `app/auth.py` e valia
        em QUALQUER ambiente. Basta o processo subir com APP_ENV=prod para que o token
        deixe de ser aceito (`app.auth.tokens_dev_ativos`); esta validação cobre o furo
        seguinte — subir prod com o opt-in ligado "só para depurar" e esquecer ligado.
        Prod não negocia: a config nem carrega.
        """
        if self.app_env == "prod" and self.permitir_tokens_dev:
            raise ValueError(
                "PERMITIR_TOKENS_DEV não pode ser true em APP_ENV=prod: os tokens "
                "estáticos dev-<papel>/portal-dev são públicos no repositório (SDD §10.3)."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
