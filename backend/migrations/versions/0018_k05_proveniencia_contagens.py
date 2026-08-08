"""0018_k05_proveniencia_contagens — o certificado declara de onde vieram os números (§8-M5-A5).

Até o K05, `certificado_elegibilidade.suprimidos`/`liquido` vinham de fixture (o read
model de dev ignora o `sql_publico`) e a API os devolvia com a mesma cara de supressão
MEDIDA — o overclaim que a auditoria do J01 apontou. A coluna nova registra a
proveniência, e ela também entra no payload canônico do hash (elegibilidade.py), então
não é editável a posteriori sem invalidar a assinatura.

`default false` no servidor: TODA linha existente veio de fixture por definição — o read
model real nunca existiu. É o único caso em que um default aqui é honesto; a partir da
migração, quem escreve é o domínio, que exige o campo sem default.

`if not exists` torna a migração idempotente como as demais.
"""

from alembic import op

revision = "0018_k05_proveniencia_contagens"
down_revision = "0017_j02_indice_invocacao"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "alter table certificado_elegibilidade"
        " add column if not exists contagens_derivadas_do_sql boolean not null default false"
    )


def downgrade() -> None:
    op.execute(
        "alter table certificado_elegibilidade drop column if exists contagens_derivadas_do_sql"
    )
