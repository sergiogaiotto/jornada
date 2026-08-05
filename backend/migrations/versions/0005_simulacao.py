"""0005_simulacao — M8 (parte 1): resultado do Ensaio Geral persistido no twin.

Emenda §4.1 (ver CHANGELOG-SDD.md): `jornada_versao` ganha `simulacao jsonb` (saída §6
— funil por nó, P10/P50/P90 de conversões/custo/receita/ROAS, lift + poder, semáforo)
e `previsto jsonb` (Previsto congelado da versão — a régua que o snapshot M8 parte 2
copia para `snapshot.previsto`). O §6 já mandava persistir "em jornada_versao"; o DDL
original não tinha a coluna.
"""

from alembic import op

revision = "0005_simulacao"
down_revision = "0004_m4_validacao"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    "alter table jornada_versao add column simulacao jsonb",
    "alter table jornada_versao add column previsto jsonb",
)

DROPS: tuple[str, ...] = (
    "alter table jornada_versao drop column if exists previsto",
    "alter table jornada_versao drop column if exists simulacao",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
