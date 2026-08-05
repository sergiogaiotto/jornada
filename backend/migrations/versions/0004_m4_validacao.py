"""0004_m4_validacao — tabelas auxiliares do M4 (SDD §4.1, nota final: "criar na
migração do módulo que as usa"): `validacao_campo` (resultado de cada checagem
automática campo-a-campo §8-M4), `os_thread` (thread do War Room ancorada em campo)
e `documento_portao` (docx executivos gerados nos portões — §4.1 lista nominalmente).

Convenções (§4): PK uuid gen_random_uuid(); escopo de tenant via OS referenciada
(mesmo padrão de `segmento`/`criativo`); created_at timestamptz.
"""

from alembic import op

revision = "0004_m4_validacao"
down_revision = "0003_criativo"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    """
    create table validacao_campo (
      id uuid primary key default gen_random_uuid(),
      os_id uuid references os not null,
      campo text not null,
      veredito text not null check (veredito in ('ok','falha')),
      checagens jsonb not null default '[]',
      evidencia jsonb not null default '{}',
      created_at timestamptz default now()
    )
    """,
    "create index on validacao_campo (os_id, campo)",
    """
    create table os_thread (
      id uuid primary key default gen_random_uuid(),
      os_id uuid references os not null,
      campo text not null,
      titulo text,
      mensagens jsonb not null default '[]',
      status text not null default 'aberta' check (status in ('aberta','resolvida')),
      created_at timestamptz default now()
    )
    """,
    "create index on os_thread (os_id)",
    """
    create table documento_portao (
      id uuid primary key default gen_random_uuid(),
      os_id uuid references os not null,
      portao text not null,
      nome_arquivo text not null,
      conteudo bytea not null,
      hash char(64) not null,
      created_at timestamptz default now()
    )
    """,
    "create index on documento_portao (os_id, portao)",
)

DROPS: tuple[str, ...] = (
    "drop table if exists documento_portao",
    "drop table if exists os_thread",
    "drop table if exists validacao_campo",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
