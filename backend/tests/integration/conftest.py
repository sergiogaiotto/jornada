"""Fixtures dos testes de integração (@pytest.mark.integration) — Postgres REAL.

Fonte do banco, em ordem:
1. `DATABASE_URL` do ambiente (CI: service `pgvector/pgvector:pg16` no job backend);
2. senão, container efêmero `pgvector/pgvector:pg16` via docker CLI (dev local),
   derrubado no fim da sessão;
3. sem docker e sem DATABASE_URL → skip explícito (os testes unit/aceite continuam
   cobrindo tudo em memória — §1.3.5).

O schema é SEMPRE o real: `alembic upgrade head` (migrações 0001..head, DDL §4.1)
no setup da sessão; cada teste começa com as tabelas core truncadas (isolamento).
"""

import os
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from adapters.persistence.sql import criar_engine

BACKEND = Path(__file__).resolve().parents[2]
IMAGEM_PG = "pgvector/pgvector:pg16"
_TABELAS_CORE = (
    # núcleo (A7 parte 1)
    "pendencia",
    "sla_clock",
    "validacao_campo",
    "os_thread",
    "documento_portao",
    "etapa_workflow",
    "hike_import_log",
    "pedido",
    "domain_event",
    # A7 parte 2 — twin/governança/audiência/criativo/lançamento/otimização/Ateliê
    "proposta_otimizacao",
    "aprendizado",
    "calibracao_prior",
    "incidente",
    "telemetry_event",
    "launch",
    "preflight_run",
    "drift_check",
    "resource_registry",
    "sync_run",
    "aprovacao",
    "snapshot",
    "experimento",
    "jornada_versao",
    "criativo",
    "certificado_elegibilidade",
    "dc_segment_cache",
    "segmento",
    "invocacao",
    "agente_evidence",
    "harness_run",
    "harness_case",
    "skill_versao",
    "agente",
    "policy_versao",
    "os",
    # identidade (emenda G01 — migração 0015). `sessao` antes de `usuario` por clareza;
    # o `cascade` do truncate já cobriria a FK, mas a ordem documenta a dependência.
    "sessao",
    "usuario",
)


def _porta_livre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _esperar_postgres(url: str, timeout_s: float = 90.0) -> None:
    """Espera o `select 1` responder via TCP (o init do container só abre TCP no
    start final — quando conecta, o banco está pronto)."""
    limite = time.monotonic() + timeout_s
    ultimo_erro: Exception | None = None
    while time.monotonic() < limite:
        try:
            engine = criar_engine(url)
            try:
                with engine.connect() as conexao:
                    conexao.execute(text("select 1"))
                return
            finally:
                engine.dispose()
        except Exception as exc:  # noqa: BLE001 — qualquer falha = ainda subindo
            ultimo_erro = exc
            time.sleep(1.0)
    raise TimeoutError(f"Postgres de teste não respondeu em {timeout_s}s: {ultimo_erro}")


@pytest.fixture(scope="session")
def url_banco() -> Iterator[str]:
    url = os.environ.get("DATABASE_URL")
    if url:
        _esperar_postgres(url)
        yield url
        return

    if shutil.which("docker") is None:
        pytest.skip("integração exige DATABASE_URL setado ou docker disponível")

    nome = f"jornada-it-{uuid.uuid4().hex[:8]}"
    porta = _porta_livre()
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            nome,
            "-e",
            "POSTGRES_USER=jornada",
            "-e",
            "POSTGRES_PASSWORD=jornada",
            "-e",
            "POSTGRES_DB=jornada",
            "-p",
            f"127.0.0.1:{porta}:5432",
            IMAGEM_PG,
        ],
        check=True,
        capture_output=True,
        timeout=600,  # inclui pull da imagem na 1ª execução
    )
    try:
        # driver canônico do §3.1 (asyncpg); o adapter normaliza para psycopg2
        url_efemera = f"postgresql+asyncpg://jornada:jornada@127.0.0.1:{porta}/jornada"
        _esperar_postgres(url_efemera)
        yield url_efemera
    finally:
        subprocess.run(["docker", "rm", "-f", nome], check=False, capture_output=True)


@pytest.fixture(scope="session")
def url_banco_migrado(url_banco: str) -> str:
    """`alembic upgrade head` (0001..head) — o DDL §4.1 é a única fonte de schema."""
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url_banco)
    command.upgrade(config, "head")
    return url_banco


@pytest.fixture()
def banco_limpo(url_banco_migrado: str) -> str:
    """Isolamento por teste: trunca as tabelas core (cascade cobre FKs)."""
    engine = criar_engine(url_banco_migrado)
    try:
        with engine.begin() as conexao:
            conexao.execute(
                text(f"truncate table {', '.join(_TABELAS_CORE)} restart identity cascade")
            )
    finally:
        engine.dispose()
    return url_banco_migrado
