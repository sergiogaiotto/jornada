"""0012_a7_ordem_estavel — A7 (parte 2): ordem de inserção durável (emenda §4.1).

Com a persistência SQL de TODOS os agregados, listas que em memória seguiam a ordem
de inserção ("o último é o corrente": `segmentos[-1]`, `aprovacoes[-1]`,
`experimento_da_os`, `_launch_de_referencia`) precisam de uma coluna de ordenação —
`segmento`, `experimento`, `aprovacao` e `launch` não tinham NENHUMA no DDL original.
Emenda §4.1 (ver CHANGELOG-SDD.md): as quatro ganham `created_at timestamptz default
now()` (convenção §4). O adapter SQL NUNCA escreve a coluna (o default do banco
registra o instante da inserção e o upsert por id preserva o original) — por isso as
dataclasses de domínio não mudam.
"""

from alembic import op

revision = "0012_a7_ordem_estavel"
down_revision = "0011_m3_pedido_crud"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    "alter table segmento add column created_at timestamptz default now()",
    "alter table experimento add column created_at timestamptz default now()",
    "alter table aprovacao add column created_at timestamptz default now()",
    "alter table launch add column created_at timestamptz default now()",
)

DROPS: tuple[str, ...] = (
    "alter table launch drop column if exists created_at",
    "alter table aprovacao drop column if exists created_at",
    "alter table experimento drop column if exists created_at",
    "alter table segmento drop column if exists created_at",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
