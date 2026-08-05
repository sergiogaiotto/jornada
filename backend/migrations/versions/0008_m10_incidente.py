"""0008_m10_incidente — M10 (parte 1): Torre de Lançamento T12 (§8-M10).

Tabela auxiliar `incidente` (§4.1 nota final: "incidente (sev1..3, kill/retomada 2
aprovadores)" — colunas óbvias, criada na migração do módulo que a usa; ver
CHANGELOG-SDD.md): incidentes TIPADOS da operação — breaker disparado (sev2),
disparo p/ lista de supressão (SEV1 + kill automático, A2), kill manual. `meta`
guarda a evidência do disparo e os aprovadores da retomada.
`launch`, `telemetry_event` e `lista_supressao` NÃO precisam de migração: já constam
da `0001_core` (§4.1).
"""

from alembic import op

revision = "0008_m10_incidente"
down_revision = "0007_preflight"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    """
    create table incidente (
      id uuid primary key default gen_random_uuid(),
      os_id uuid references os not null,
      launch_id uuid references launch,
      sev text not null check (sev in ('sev1','sev2','sev3')),
      tipo text not null,
      titulo text not null,
      descricao text,
      estado text not null default 'aberto' check (estado in ('aberto','resolvido')),
      meta jsonb not null default '{}',
      aberto_em timestamptz default now(),
      resolvido_em timestamptz
    )
    """,
    "create index on incidente (os_id, estado)",
    "create index on incidente (launch_id)",
)

DROPS: tuple[str, ...] = ("drop table if exists incidente",)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
