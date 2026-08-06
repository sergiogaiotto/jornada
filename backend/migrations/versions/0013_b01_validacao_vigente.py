"""0013_b01_validacao_vigente — B01 (UAT #2): `validacao_campo` guarda a decisão VIGENTE.

Achado: a tela T3 zerava após reload/restart porque só existiam POSTs; e revalidar o
mesmo campo empilhava linhas. A emenda §8-M4 cria `GET /os/{id}/validacoes` e torna o
POST idempotente por (os_id, campo) — esta migração sustenta a invariante no banco:

1. `por` / `atualizado_em`: quem e quando produziu a decisão vigente (a leitura mostra
   autoria; `created_at` continua sendo a PRIMEIRA checagem do campo). Backfill de
   `atualizado_em` a partir de `created_at` para as linhas já existentes.
2. Dedup das duplicatas já gravadas em produção (mantém a mais recente por os_id+campo,
   critério de desempate estável por id) e troca do índice (os_id, campo) por um UNIQUE.
   O histórico de cada execução permanece intacto no outbox `domain_event`
   (`validacao.executada`, §2.3) — a tabela guarda estado, o outbox guarda o filme.
"""

from alembic import op

revision = "0013_b01_validacao_vigente"
down_revision = "0012_a7_ordem_estavel"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    "alter table validacao_campo add column por text",
    "alter table validacao_campo add column atualizado_em timestamptz",
    "update validacao_campo set atualizado_em = created_at where atualizado_em is null",
    # dedup: sobrevive a mais recente de cada (os_id, campo) — é a que a UI hidratava
    """
    delete from validacao_campo v
     using validacao_campo mais_nova
     where v.os_id = mais_nova.os_id
       and v.campo = mais_nova.campo
       and (v.created_at, v.id) < (mais_nova.created_at, mais_nova.id)
    """,
    "drop index if exists validacao_campo_os_id_campo_idx",
    "create unique index validacao_campo_os_id_campo_key on validacao_campo (os_id, campo)",
)

DROPS: tuple[str, ...] = (
    "drop index if exists validacao_campo_os_id_campo_key",
    "create index validacao_campo_os_id_campo_idx on validacao_campo (os_id, campo)",
    "alter table validacao_campo drop column if exists atualizado_em",
    "alter table validacao_campo drop column if exists por",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
