"""0016_f03_politica_ia — dá BANCO e DONO à política de IA Responsável (§10.2, F03).

A onda 3 entregou `domain/ia_responsavel/` com quatro parâmetros cujo enforcement está
provado por inversão — e sem tabela, sem rota e sem tela. Uma política que só existe em
memória de função pura não tem dono: ninguém a publica, ninguém responde por ela, e ela
não sobrevive a um restart. Esta migração é a metade "existe no mundo" do conserto.

Três decisões que a tabela congela:

1. **Autoria na LINHA, não só no outbox.** `policy_versao` (M12) não guarda quem
   publicou; a rastreabilidade depende de correlacionar `domain_event`. Para o Art. 20
   da LGPD isso é pouco: "quem autorizou a IA a decidir sozinha, e quando?" é pergunta
   de auditoria, e a resposta tem de estar na linha que governa — não numa junção que
   alguém precisa saber fazer. Daí `autor_*` (criação) e `publicado_por_*` (publicação)
   SEPARADOS: são atos distintos e a segregação de funções (§10.5) exige distingui-los,
   mesmo quando hoje a mesma pessoa faz os dois.

2. **`motivo` é coluna, não metadado.** Política de privacidade que muda sem
   justificativa escrita é exatamente o que uma auditoria pede para ver e não encontra.
   Fica nullable no BANCO (a API é quem exige) pela mesma disciplina do 0015: apertar
   `not null` numa coluna nova só é seguro depois de um `select count(*) where ... is
   null` limpo, e a garantia real já está no agregado.

3. **Sem `unique (tenant_id, versao)`, com índice de leitura.** O mesmo desenho do
   `policy_versao`, deliberadamente: a numeração é `max(existentes)+1` calculado no
   serviço, e um unique aqui transformaria corrida de publicação simultânea em 500 de
   integridade em vez de erro tratável. O índice que importa é o do caminho quente —
   "qual a publicada atual deste tenant?" — que roda em TODO request que consulta a
   política.

**Não há seed.** Diferente de `semear_politicas` (M12), nada escreve uma linha v1 no
boot: uma linha `estado='publicada'` sem autor humano faria a tela do DPO exibir
"publicada" para algo que ninguém assinou. O default conservador vive no domínio
(`politica_ia_seed`) e é servido pelo adapter com `origem='seed'` — governo real,
origem honesta, tabela vazia até um humano publicar.
"""

from alembic import op

revision = "0016_f03_politica_ia"
down_revision = "0015_g01_identidade"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    """
    create table if not exists politica_ia (
      id uuid primary key,
      tenant_id text not null,
      versao int not null,
      conteudo jsonb not null,
      estado text not null default 'draft',
      autor_id uuid,
      autor_nome text,
      criada_em timestamptz default now(),
      publicada_em timestamptz,
      publicado_por_id uuid,
      publicado_por_nome text,
      motivo text
    )
    """,
    # caminho quente: "qual a política de IA publicada deste tenant?" em todo request
    "create index if not exists politica_ia_tenant_versao_idx"
    " on politica_ia (tenant_id, versao desc)",
    # histórico da tela (todas as versões do tenant, ordem de versão)
    "create index if not exists politica_ia_tenant_estado_idx on politica_ia (tenant_id, estado)",
)

DROPS: tuple[str, ...] = (
    "drop index if exists politica_ia_tenant_estado_idx",
    "drop index if exists politica_ia_tenant_versao_idx",
    "drop table if exists politica_ia",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
