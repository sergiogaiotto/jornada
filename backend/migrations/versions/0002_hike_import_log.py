"""0002_hike_import_log — tabela auxiliar do M2 (SDD §4.1, nota final: "criar na migração
do módulo que as usa"). Log do `POST /admin/hike/import` (§8-M2): um registro por card
do export, com status ok|duplicado|erro e detalhe jsonb.

Convenções (§4): PK uuid gen_random_uuid(); tenant_id text not null + índice.
"""

from alembic import op

revision = "0002_hike_import_log"
down_revision = "0001_core"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    """
    create table hike_import_log (
      id uuid primary key default gen_random_uuid(),
      tenant_id text not null,
      os_id uuid references os,
      hike_card_id text not null,
      status text not null check (status in ('ok','duplicado','erro')),
      detalhe jsonb not null default '{}',
      created_at timestamptz default now()
    )
    """,
    "create index on hike_import_log (tenant_id)",
)

DROPS: tuple[str, ...] = ("drop table if exists hike_import_log",)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
