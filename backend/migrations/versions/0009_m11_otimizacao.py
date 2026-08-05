"""0009_m11_otimizacao — M11: Otimização/Retro/Calibração T15 (§8-M11).

Tabelas auxiliares `proposta_otimizacao` e `aprendizado` (§4.1 nota final — colunas
óbvias, criadas na migração do módulo que as usa; emenda registrada no
CHANGELOG-SDD.md): propostas do agente optimize (diff JGC + impacto pré-simulado +
ranking lift×esforço×risco; aprovar gera nova `jornada_versao`) e a memória da retro
(aceito/sinal/promovido; clone herda via `herdado_de` — A3).
`experimento`, `calibracao_prior` e `agente_evidence` NÃO precisam de migração: já
constam da `0001_core` (§4.1).
"""

from alembic import op

revision = "0009_m11_otimizacao"
down_revision = "0008_m10_incidente"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    """
    create table proposta_otimizacao (
      id uuid primary key default gen_random_uuid(),
      os_id uuid references os not null,
      jornada_base_id uuid references jornada_versao not null,
      titulo text not null,
      motivacao text,
      grafo_proposto jsonb not null,
      diff jsonb not null default '{}',
      impacto jsonb not null default '{}',
      esforco int not null,
      risco numeric(4,2) not null,
      score numeric(10,6),
      estado text not null default 'proposta' check (estado in ('proposta','aprovada','rejeitada')),
      motivo_rejeicao text,
      jornada_gerada_id uuid references jornada_versao,
      via_ai boolean default true,
      decidido_por text,
      decidido_em timestamptz,
      created_at timestamptz default now()
    )
    """,
    "create index on proposta_otimizacao (os_id, estado)",
    """
    create table aprendizado (
      id uuid primary key default gen_random_uuid(),
      tenant_id text not null,
      os_id uuid references os not null,
      origem text not null check (origem in ('proposta_aprovada','proposta_rejeitada','experimento')),
      status text not null check (status in ('aceito','sinal','promovido')),
      texto text not null,
      meta jsonb not null default '{}',
      herdado_de uuid references os,
      created_at timestamptz default now()
    )
    """,
    "create index on aprendizado (os_id, status)",
    "create index on aprendizado (tenant_id)",
)

DROPS: tuple[str, ...] = (
    "drop table if exists aprendizado",
    "drop table if exists proposta_otimizacao",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
