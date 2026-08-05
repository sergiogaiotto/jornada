"""0003_criativo — tabela auxiliar do M6 (SDD §4.1, nota final: "criar na migração do
módulo que as usa"): `criativo` (matriz canal×variante, estado por célula,
kv_master_ref). Uma linha por matriz da OS; células no jsonb `celulas`
[{canal, variante, conteudo, estado, aprovada_por, aprovada_em, observacao}] com
estado em gerado|aprovado|revisar|adaptado_revisar (§8-M6).

Convenções (§4): PK uuid gen_random_uuid(); escopo de tenant via OS referenciada
(mesmo padrão de `segmento`); created_at/updated_at timestamptz.
"""

from alembic import op

revision = "0003_criativo"
down_revision = "0002_hike_import_log"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    """
    create table criativo (
      id uuid primary key default gen_random_uuid(),
      os_id uuid references os not null,
      kv_master jsonb not null default '{}',
      kv_master_ref text,
      celulas jsonb not null default '[]',
      created_at timestamptz default now(),
      updated_at timestamptz default now()
    )
    """,
    "create index on criativo (os_id)",
)

DROPS: tuple[str, ...] = ("drop table if exists criativo",)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
