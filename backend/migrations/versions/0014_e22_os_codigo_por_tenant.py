"""0014_e22_os_codigo_por_tenant — achado 22 (UAT5): `os.codigo` é unique POR TENANT.

O DDL §4.1 nasceu com `codigo text unique` (unique GLOBAL). Com um só cliente isso
passou despercebido, mas são duas fugas de multi-tenancy:

1. **Oráculo de existência**: `POST /os {"codigo": "OS-2026-0457"}` de um tenant vazio
   devolvia 409 "Já existe OS com código ..." — dá para enumerar a plataforma inteira
   a partir de uma conta nova.
2. **Volume de negócio no próprio código**: a sequência `OS-{ano}-NNNN` era max+1
   global, então o número da primeira OS de um cliente novo contava quantas OS TODOS
   os outros já abriram.

Esta migração troca o unique de `(codigo)` por `(tenant_id, codigo)`; a checagem de
duplicidade e o sequencial passam a filtrar por tenant nos dois adapters (§2.1). Nada
precisa de dedup: um unique mais FRACO nunca invalida linhas já gravadas.

O nome do constraint criado pelo `unique` inline do 0001 é o default do Postgres
(`os_codigo_key`); o drop é `if exists` para bancos que já tenham sido ajustados à mão.
"""

from alembic import op

revision = "0014_e22_os_codigo_por_tenant"
down_revision = "0013_b01_validacao_vigente"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    "alter table os drop constraint if exists os_codigo_key",
    "create unique index if not exists os_tenant_id_codigo_key on os (tenant_id, codigo)",
)

DROPS: tuple[str, ...] = (
    # volta ao unique global — só é possível se não houver código repetido entre tenants
    "drop index if exists os_tenant_id_codigo_key",
    "alter table os add constraint os_codigo_key unique (codigo)",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
