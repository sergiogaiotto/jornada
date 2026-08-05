"""0006_aprovacao_invalidada — M8 (parte 2): invalidação da aprovação por custo (A4).

Emenda §4.1 (ver CHANGELOG-SDD.md): `aprovacao` ganha `invalidada_em timestamptz` e
`invalidada_motivo text`. O aceite §8-M8-A4 exige que variação de custo >10% APÓS a
aprovação invalide a aprovação (snapshot novo obrigatório); o DDL original não tinha
onde registrar a invalidação sem destruir o histórico da decisão (decisao/decidido_em
permanecem — event sourcing §4.1).
"""

from alembic import op

revision = "0006_aprovacao_invalidada"
down_revision = "0005_simulacao"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    "alter table aprovacao add column invalidada_em timestamptz",
    "alter table aprovacao add column invalidada_motivo text",
)

DROPS: tuple[str, ...] = (
    "alter table aprovacao drop column if exists invalidada_motivo",
    "alter table aprovacao drop column if exists invalidada_em",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
