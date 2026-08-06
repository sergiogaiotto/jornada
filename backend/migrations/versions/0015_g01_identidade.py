"""0015_g01_identidade — dá corpo a `usuario` e cria `sessao` (emenda G01).

A tabela `usuario` nasceu no 0001 como DECORAÇÃO do DDL §4.1
(`id, tenant_id, nome, email unique, papeis text[]`): nada nunca escreveu nela porque a
autenticação eram seis strings publicadas no repositório (`dev-admin`, `portal-dev`...).
Esta migração transforma a tabela na fonte de verdade da identidade e acrescenta a
`sessao` que torna o logout REVOGÁVEL.

Três decisões que a migração congela:

1. **`email` passa a ser unique POR TENANT, sobre `lower(email)`.** O unique global do
   0001 tem exatamente os dois defeitos que o achado 22/UAT5 encontrou no `os.codigo`:
   um cliente novo descobre, pelo 409, que o e-mail já existe em OUTRO tenant (oráculo
   cross-tenant), e a mesma pessoa fica impedida de ter conta em dois tenants. O
   `lower()` no índice é o que impede `Sergio@x` e `sergio@x` de coexistirem — a
   aplicação normaliza, mas o banco é quem garante.
2. **`papeis` continua `text[]`** — justificativa longa em
   `domain/identidade/modelos.py` (conjunto fechado de 6, sem atributos na atribuição,
   lido inteiro em todo request; junção custaria um join por request e não compraria
   integridade nenhuma, porque a lista de papéis vive no Python).
3. **`sessao.id` é `text`, não `uuid`**: guarda o sha256 do segredo que viaja no
   cookie, na mesma disciplina do `aprovacao.token_hash` do M8 (o banco nunca vê o
   token em claro; um dump de `sessao` não reencena sessão nenhuma).

Colunas novas entram todas com default ou nullable — a tabela está vazia em qualquer
ambiente (nada nunca a escreveu), mas a migração não depende desse fato para ser segura.
`tenant_id`/`email`/`nome` seguem nullable no banco: apertá-los exigiria assumir o que
há nas linhas existentes, e a aplicação já os exige no agregado. O `not null` fica para
a migração que puder rodar depois de um `select count(*) where ... is null` limpo.
"""

from alembic import op

revision = "0015_g01_identidade"
down_revision = "0014_e22_os_codigo_por_tenant"
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    # --- usuario: identidade de verdade ---
    "alter table usuario add column if not exists senha_hash text",
    "alter table usuario add column if not exists ativo boolean not null default true",
    "alter table usuario add column if not exists senha_expirada boolean not null default false",
    "alter table usuario add column if not exists criado_em timestamptz default now()",
    "alter table usuario add column if not exists criado_por uuid",
    "alter table usuario add column if not exists ultimo_acesso timestamptz",
    "alter table usuario add column if not exists tentativas_falhas int not null default 0",
    "alter table usuario add column if not exists bloqueado_ate timestamptz",
    # unique global (nome default do Postgres para o `unique` inline do 0001) → por tenant
    "alter table usuario drop constraint if exists usuario_email_key",
    "create unique index if not exists usuario_tenant_id_email_key"
    " on usuario (tenant_id, lower(email))",
    # --- sessao: o que torna logout/bloqueio revogáveis ---
    """
    create table if not exists sessao (
      id text primary key,
      usuario_id uuid not null references usuario(id),
      criada_em timestamptz not null default now(),
      expira_em timestamptz not null,
      revogada_em timestamptz,
      ip text,
      user_agent text
    )
    """,
    # revogação em massa (desativar usuário / trocar senha) varre por usuário
    "create index if not exists sessao_usuario_id_idx on sessao (usuario_id)",
    # faxina de sessões vencidas (rotina de ops) varre por expiração
    "create index if not exists sessao_expira_em_idx on sessao (expira_em)",
)

DROPS: tuple[str, ...] = (
    "drop table if exists sessao",
    "drop index if exists usuario_tenant_id_email_key",
    # volta ao unique global — só é possível se não houver e-mail repetido entre tenants
    "alter table usuario add constraint usuario_email_key unique (email)",
    "alter table usuario drop column if exists bloqueado_ate",
    "alter table usuario drop column if exists tentativas_falhas",
    "alter table usuario drop column if exists ultimo_acesso",
    "alter table usuario drop column if exists criado_por",
    "alter table usuario drop column if exists criado_em",
    "alter table usuario drop column if exists senha_expirada",
    "alter table usuario drop column if exists ativo",
    "alter table usuario drop column if exists senha_hash",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
