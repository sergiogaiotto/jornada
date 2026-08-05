"""0007_preflight — M9 (fatia 2): pré-voo T11 (§8-M9).

Tabela auxiliar `preflight_run` (§4.1 nota final — colunas óbvias, criada na migração
do módulo que a usa; ver CHANGELOG-SDD.md): resultado da bateria pass/warn/fail do
`POST /preflight/{snapshot}` com evidência por item. FAIL (`vermelho`) bloqueia o
apply; apply em prod exige pré-voo executado e não-vermelho (§5.4.4).
`drift_check` NÃO precisa de migração: já consta da `0001_core` (§4.1).
"""

from alembic import op

revision = "0007_preflight"
down_revision = "0006_aprovacao_invalidada"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    """
    create table preflight_run (
      id uuid primary key default gen_random_uuid(),
      snapshot_id uuid references snapshot not null,
      ambiente text check (ambiente in ('homolog','prod')),
      resultado text not null check (resultado in ('verde','amarelo','vermelho')),
      itens jsonb not null default '[]',
      created_at timestamptz default now()
    )
    """,
    "create index on preflight_run (snapshot_id, ambiente)",
)

DROPS: tuple[str, ...] = ("drop table if exists preflight_run",)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
