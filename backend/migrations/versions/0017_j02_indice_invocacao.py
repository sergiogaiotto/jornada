"""0017_j02_indice_invocacao — índice do gasto do teto de tokens (§10.8, J02).

O enforcement do `teto_tokens` (onda 6) soma `invocacao.tokens` por tenant desde a
virada do dia UTC — em TODA requisição de LLM de tenant com teto configurado. A tabela
`invocacao` não tinha NENHUM índice além da PK (0001), então essa soma degradaria
linearmente com o ledger (quem o encolhe é o purge §10.4, com retenção default de 180
dias). O índice (tenant_id, created_at) serve exatamente o predicado da soma.

Sem mudança de schema — só índice; `if not exists` torna a migração idempotente como
as demais.
"""

from alembic import op

revision = "0017_j02_indice_invocacao"
down_revision = "0016_f03_politica_ia"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "create index if not exists invocacao_tenant_created_idx"
        " on invocacao (tenant_id, created_at)"
    )


def downgrade() -> None:
    op.execute("drop index if exists invocacao_tenant_created_idx")
