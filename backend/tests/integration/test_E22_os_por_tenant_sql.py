"""Achado 22 (UAT5) no adapter SQL, com Postgres REAL (@integration).

O espelho em memória está em `tests/unit/test_E22_os_por_tenant.py`. Aqui o que importa
é o SCHEMA: a migração 0014 troca `unique (codigo)` por `unique (tenant_id, codigo)` —
sem ela, o segundo `insert` do mesmo código estoura IntegrityError e a plataforma
continua com um oráculo de existência entre clientes.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from adapters.persistence.sql import RepositorioSql, criar_engine
from domain.campanha.modelos import OS

pytestmark = pytest.mark.integration

AGORA = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


def _os(tenant: str, codigo: str) -> OS:
    return OS(
        id=uuid.uuid4(),
        tenant_id=tenant,
        codigo=codigo,
        nome="Campanha Integração",
        tshirt="M",
        fase="pensada",
        briefing={},
        frozen=None,
        created_by=uuid.uuid4(),
        created_at=AGORA,
        updated_at=AGORA,
    )


def test_unique_de_codigo_e_por_tenant(banco_limpo: str) -> None:
    """Dois tenants gravam OS-2026-0457; a busca escopada devolve a de cada um."""
    repo = RepositorioSql(criar_engine(banco_limpo))
    minha = _os("torre-movel", "OS-2026-0457")
    dela = _os("outra-torre", "OS-2026-0457")
    repo.adicionar_os(minha)
    repo.adicionar_os(dela)  # sem a 0014: IntegrityError (unique global)

    encontrada = repo.obter_os_por_codigo("OS-2026-0457", "outra-torre")
    assert encontrada is not None and encontrada.id == dela.id
    assert repo.obter_os_por_codigo("OS-2026-0457", "tenant-vazio") is None
    assert repo.obter_os_por_codigo("OS-2026-0457") is not None  # global segue existindo

    # o unique novo é do BANCO, não só do serviço: repetir dentro do tenant ainda quebra
    with pytest.raises(IntegrityError):
        repo.adicionar_os(_os("torre-movel", "OS-2026-0457"))


def test_indice_unique_tenant_codigo_existe_no_schema(banco_limpo: str) -> None:
    """Guarda-corpo do DDL: a invariante vive no schema (0014), não na aplicação."""
    engine = criar_engine(banco_limpo)
    try:
        with engine.connect() as conexao:
            indices = {
                linha[0]
                for linha in conexao.execute(
                    text("select indexname from pg_indexes where tablename = 'os'")
                )
            }
    finally:
        engine.dispose()
    assert "os_tenant_id_codigo_key" in indices
    assert "os_codigo_key" not in indices  # o unique GLOBAL saiu


def test_sequencial_por_tenant_sobrevive_a_restart(banco_limpo: str) -> None:
    """max+1 escopado: o cliente novo começa em 0001 mesmo com o outro em 9002."""
    repo = RepositorioSql(criar_engine(banco_limpo))
    repo.adicionar_os(_os("torre-movel", "OS-2026-9001"))

    repo2 = RepositorioSql(criar_engine(banco_limpo))  # engine NOVO = restart
    assert repo2.proximo_sequencial_os(2026, "torre-movel") == 9002
    assert repo2.proximo_sequencial_os(2026, "outra-torre") == 1
    assert repo2.proximo_sequencial_os(2026) == 9002  # global segue para o cross-tenant
