"""0011_m3_pedido_crud — CRUD de pedidos (emenda §8-M3 2026-08-05).

Emenda §4.1 (ver CHANGELOG-SDD.md): `pedido` ganha o estado 'arquivado' no CHECK
(soft archive — `POST /pedidos/{id}/arquivar`) e as colunas `created_at`/`updated_at`
(convenção §4 de toda tabela de negócio; `GET /pedidos` expõe `updated_at` — o DDL
original não tinha as colunas; o instante vem do ClockPort §2.1, default now() no banco).
"""

from alembic import op

revision = "0011_m3_pedido_crud"
down_revision = "0010_m7_versionamento"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    "alter table pedido drop constraint if exists pedido_estado_check",
    "alter table pedido add constraint pedido_estado_check "
    "check (estado in ('rascunho','completo','convertido','arquivado'))",
    "alter table pedido add column if not exists created_at timestamptz default now()",
    "alter table pedido add column if not exists updated_at timestamptz default now()",
)

DROPS: tuple[str, ...] = (
    "alter table pedido drop constraint if exists pedido_estado_check",
    "update pedido set estado = 'rascunho' where estado = 'arquivado'",
    "alter table pedido add constraint pedido_estado_check "
    "check (estado in ('rascunho','completo','convertido'))",
    "alter table pedido drop column if exists created_at",
    "alter table pedido drop column if exists updated_at",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
