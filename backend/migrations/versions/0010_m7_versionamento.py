"""0010_m7_versionamento — M7 versionamento/exportação (emenda §8-M7 2026-08-05).

Emenda §4.1 (ver CHANGELOG-SDD.md): `jornada_versao` ganha `created_at timestamptz`
— a lista resumida `GET /os/{id}/jornadas` expõe quando cada versão nasceu (o DDL
original não tinha a coluna; o instante vem do ClockPort §2.1, default now() no banco).
"""

from alembic import op

revision = "0010_m7_versionamento"
down_revision = "0009_m11_otimizacao"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    "alter table jornada_versao add column created_at timestamptz default now()",
)

DROPS: tuple[str, ...] = ("alter table jornada_versao drop column if exists created_at",)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
