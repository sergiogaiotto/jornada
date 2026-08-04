"""0001_core — DDL núcleo integral do SDD §4.1 (com emenda de ordem da view os_saude).

Convenções (§4): PK uuid gen_random_uuid(); tenant_id text not null nas tabelas de negócio;
histórico via event sourcing/versões (sem soft-delete). Extensões: pgcrypto, vector.
Statements executados um a um (asyncpg não aceita múltiplos comandos por prepared statement).
Nota: em `launch.ondas`, os `:` do JSON default estão escapados (`\\:`) porque `op.execute`
interpreta `:nome` como bind param (SQLAlchemy text()); o SQL renderizado é idêntico ao §4.1.
"""

from alembic import op

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS: tuple[str, ...] = (
    "create extension if not exists pgcrypto",
    "create extension if not exists vector",
    # ===== Núcleo OS/governança =====
    """
    create table os (                            -- Campanha/Ordem de Serviço
      id uuid primary key default gen_random_uuid(),
      tenant_id text not null, codigo text unique not null,        -- ex. OS-2026-0457
      nome text not null, tshirt text not null check (tshirt in ('P','M','G','GG')),
      fase text not null default 'pensada' check (fase in
        ('pensada','discutida','criada','avaliada','configurada','disparada','monitorada','encerrada')),
      briefing jsonb not null default '{}',                        -- 14 campos (§8.M3)
      frozen jsonb,                    -- congelado no GO: {agent_versions, policy_version, tarifario_id, slas}
      created_by uuid not null, created_at timestamptz default now(), updated_at timestamptz default now()
    )
    """,
    """
    create table sla_clock (
      id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
      etapa text not null, prazo timestamptz not null,
      estado text not null default 'correndo' check (estado in ('correndo','pausado_cliente','bloqueado_pendencia','concluido')),
      pausas jsonb not null default '[]'                            -- [{de,ate,motivo}]
    )
    """,
    """
    create table pendencia (
      id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
      numero int not null, tipo text check (tipo in ('risk','assumption','issue','dependency')),
      titulo text not null, descricao text, severidade text check (severidade in ('baixa','media','alta')),
      bloqueante boolean default true, bloqueia_etapa text,
      status text default 'aberta' check (status in ('aberta','resolvida','aceita')),
      accountable uuid, aceite jsonb,                               -- {por, em, justificativa}
      origem text, via_ai boolean default false, created_at timestamptz default now()
    )
    """,
    # Saúde NUNCA é coluna: view derivada (após sla_clock/pendencia — emenda M0, CHANGELOG-SDD.md)
    """
    create view os_saude as
      select o.id as os_id,
        case when exists(select 1 from pendencia r where r.os_id=o.id and r.status='aberta' and r.bloqueante)
          or exists(select 1 from sla_clock s where s.os_id=o.id and s.estado='correndo' and now()>s.prazo)
        then 'em_risco' else 'normal' end as saude
      from os o
    """,
    """
    create table jornada_versao (                 -- o TWIN: versões do grafo canônico
      id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
      versao int not null, grafo jsonb not null,                    -- JGC (§5), validado por JSON Schema
      hash char(64) not null,                                       -- sha256 do JGC canonicalizado (RFC 8785)
      estado text default 'rascunho' check (estado in ('rascunho','simulado','aprovado','publicado','arquivado')),
      premissas jsonb default '[]', custo_projetado numeric(12,2),
      unique(os_id, versao)
    )
    """,
    """
    create table snapshot (                       -- pacote imutável de aprovação
      id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
      hash char(64) unique not null,              -- hash composto: JGC+SQL+criativos+políticas+custo+experimento
      conteudo jsonb not null, previsto jsonb,    -- Previsto congelado da simulação
      created_at timestamptz default now()
    )
    """,
    """
    create table aprovacao (                      -- link mágico
      id uuid primary key default gen_random_uuid(), snapshot_id uuid references snapshot not null,
      token_hash char(64) unique not null, expira_em timestamptz not null, alcada text not null,
      decisao text check (decisao in ('aprovado','aprovado_ressalvas','reprovado')),
      decidido_em timestamptz, decidido_meta jsonb,                 -- ip, device, otp?
      ressalvas jsonb default '[]'                                  -- viram pendências automaticamente
    )
    """,
    """
    create table segmento (
      id uuid primary key default gen_random_uuid(), os_id uuid references os,
      origem text not null check (origem in ('estudio_sql','data_cloud')),
      dc_segment_id text, sql_publico text, criterios_resumo text,
      contagem_bruta int, contagem_liquida int, waterfall jsonb,    -- [{etapa, corte, restante, motivo}]
      volume_abordagem jsonb,                                        -- {email:{n,pct},sms:{...},push:{...},whatsapp:{...}}
      holdout_pct numeric(4,1) default 10.0, frescor jsonb           -- {fonte: ultima_atualizacao}
    )
    """,
    """
    create table experimento (
      id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
      holdout_pct numeric(4,1) not null, n_minimo int not null, mde_pp numeric(5,2) not null,
      janela_dias int not null, metricas jsonb not null, travado_em timestamptz,
      estado text default 'pre_registrado' check (estado in ('pre_registrado','em_apuracao','apurado')),
      resultado jsonb                                                -- {lift, ic95:[a,b], significativo, roas}
    )
    """,
    """
    create table etapa_workflow (                 -- T4a: esteira ex-Hike
      id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
      ordem int not null, nome text not null,     -- briefing|discovery|audiencia|criativos|configuracao|disparo|acompanhamento
      responsavel uuid, sla_dias int, estado text default 'pendente'
        check (estado in ('pendente','em_andamento','concluida','bloqueada')),
      checklist jsonb default '[]',               -- [{item, feito, por, em}] — subtarefas de Criativos/Acompanhamento
      dependencias jsonb default '[]', hike_ref jsonb               -- {card_id, importado_em, url_arquivada}
    )
    """,
    """
    create table sync_run (                       -- compilador plan/apply
      id uuid primary key default gen_random_uuid(), snapshot_id uuid references snapshot not null,
      ambiente text check (ambiente in ('homolog','prod')), fase text check (fase in ('plan','apply')),
      plano jsonb,                                -- [{recurso, acao: criar|alterar|manter|destruir, aviso?}]
      resultado jsonb, estado text default 'pendente'
        check (estado in ('pendente','ok','parcial','revertido','falhou')),
      api_calls int default 0, created_at timestamptz default now()
    )
    """,
    """
    create table resource_registry (              -- twin ↔ SFMC
      id uuid primary key default gen_random_uuid(), tenant_id text not null,
      no_jgc text not null, tipo_sfmc text not null,               -- dataExtension|eventDefinition|journey|asset|automation
      external_key text not null, sfmc_id text, ambiente text, snapshot_hash char(64),
      unique(tenant_id, ambiente, external_key)
    )
    """,
    """
    create table drift_check (
      id uuid primary key default gen_random_uuid(), snapshot_id uuid references snapshot,
      recurso text, estado text check (estado in ('em_sincronia','drift_sfmc','twin_a_frente')),
      diff jsonb, resolucao text check (resolucao in ('adopt','enforce','excecao') or resolucao is null),
      checked_at timestamptz default now()
    )
    """,
    r"""
    create table launch (                         -- T12
      id uuid primary key default gen_random_uuid(), snapshot_id uuid references snapshot not null,
      ondas jsonb not null default '[{"pct"\:1},{"pct"\:10},{"pct"\:100}]', onda_atual int default 0,
      estado text default 'armado' check (estado in ('armado','em_rampa','pausado_breaker','morto','concluido')),
      breakers jsonb not null,                    -- limites da política congelada
      eventos jsonb default '[]'
    )
    """,
    """
    create table telemetry_event (
      id bigint generated always as identity primary key, tenant_id text not null,
      os_id uuid, no_jgc text, canal text, tipo text,               -- sent|delivered|open|click|bounce|optout|conversion
      contato_hash char(64),                      -- NUNCA msisdn/e-mail em claro
      fonte text check (fonte in ('ens','extract')), ts timestamptz not null, payload jsonb
    )
    """,
    "create index on telemetry_event (os_id, tipo, ts)",
    # ===== Mesh de agentes =====
    """
    create table agente (
      id uuid primary key default gen_random_uuid(), tenant_id text not null,
      nome text unique not null,                  -- consultor|engineer|activate|flow|visual|copy|content|sync|publish|simulate|persona|insight|optimize|calibrate|cost|doc|maestro|triagem_*
      camada text check (camada in ('maestro','triagem','especialista')),
      etapa_workflow text, modelo_perfil text check (modelo_perfil in ('120b','20b')),
      deterministico boolean default false        -- guard=true (NÃO invoca LLM)
    )
    """,
    """
    create table skill_versao (
      id uuid primary key default gen_random_uuid(), agente_id uuid references agente not null,
      versao text not null, skill_md text not null, execution_profile jsonb,
      bases_rag text[] default '{}', estado text default 'draft' check (estado in ('draft','em_revisao','publicada')),
      harness_score numeric(5,2), publicada_em timestamptz, unique(agente_id, versao)
    )
    """,
    """
    create table harness_case (                   -- golden dataset
      id uuid primary key default gen_random_uuid(), agente_id uuid references agente not null,
      input jsonb not null, esperado jsonb not null, dimensoes text[] default '{correcao,evidencia,compliance,formato}'
    )
    """,
    """
    create table harness_run (
      id uuid primary key default gen_random_uuid(), skill_versao_id uuid references skill_versao not null,
      resultados jsonb not null, score numeric(5,2), passou boolean, created_at timestamptz default now()
    )
    """,
    """
    create table invocacao (                      -- ledger via_ai (LGPD Art. 20 — reconstruível)
      id uuid primary key default gen_random_uuid(), tenant_id text not null, os_id uuid,
      agente_id uuid references agente, skill_versao text, usuario_portador uuid not null,
      input jsonb, output jsonb, evidencias jsonb default '[]',     -- ids de chunks RAG citados
      judge jsonb, aceito_por uuid, aceito_em timestamptz,
      tokens int, latencia_ms int, created_at timestamptz default now()
    )
    """,
    """
    create table agente_evidence (                -- RAG (collection única, filtrada por metadados)
      id uuid primary key default gen_random_uuid(), tenant_id text not null,
      base text not null,                         -- dicionario_dados|criativos|governanca|inventario_jornadas|resultados|historico_campanhas|ofertas|tarifario
      ref text, chunk text not null, meta jsonb default '{}',
      embedding vector(1024) not null             -- Qwen3-Embedding-0.6B; EMBED_DIM
    )
    """,
    "create index on agente_evidence using hnsw (embedding vector_cosine_ops)",
    # ===== Governança/plataforma =====
    """
    create table policy_versao (
      id uuid primary key default gen_random_uuid(), tenant_id text not null, versao int not null,
      conteudo jsonb not null,  -- {frequency_cap, quiet_hours, blackout, holdout_min, alcadas:[{ate,papel}], retencao_dias, breakers, precedencia}
      estado text default 'draft' check (estado in ('draft','publicada')), publicada_em timestamptz
    )
    """,
    """
    create table lista_supressao (                -- 7 listas
      tenant_id text not null, lista text not null check (lista in
        ('blacklist','fraude','nao_perturbe','optout','procon','inadimplente','reprovado_credito')),
      contato_hash char(64) not null, atualizado_em timestamptz default now(),
      primary key (tenant_id, lista, contato_hash)
    )
    """,
    """
    create table certificado_elegibilidade (
      id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
      hash char(64) not null, suprimidos jsonb not null,            -- {lista: contagem}
      liquido int not null, emitido_em timestamptz default now(), valido_ate timestamptz,
      last_mile jsonb                                                -- re-varredura no disparo
    )
    """,
    """
    create table tarifa_canal (
      tenant_id text not null, canal text not null, custo_unit numeric(10,6) not null,
      vigencia daterange not null, primary key (tenant_id, canal, vigencia)
    )
    """,
    """
    create table pedido (                         -- intake do Consultor (T2/portal)
      id uuid primary key default gen_random_uuid(), tenant_id text not null,
      solicitante jsonb not null, conteudo jsonb not null default '{}',
      completude numeric(4,1) default 0, faltantes text[] default '{}',
      estado text default 'rascunho' check (estado in ('rascunho','completo','convertido')),
      os_id uuid references os
    )
    """,
    """
    create table dc_segment_cache (               -- T5a (consulta, não cópia)
      id text primary key, tenant_id text not null, nome text, criterios_resumo text,
      membros int, dmos text[], republicado_em timestamptz, ciclo text, status text, atualizado_em timestamptz
    )
    """,
    """
    create table calibracao_prior (
      id uuid primary key default gen_random_uuid(), tenant_id text, tipo_campanha text,
      versao int, priors jsonb not null, score numeric(4,2), backtest jsonb, publicada_em timestamptz
    )
    """,
    "create table usuario (id uuid primary key, tenant_id text, nome text, email text unique,"
    " papeis text[])",
    """
    create table domain_event (id bigint generated always as identity primary key, tenant_id text,
      os_id uuid, type text not null, payload jsonb, actor text, via_ai boolean default false,
      created_at timestamptz default now())
    """,
)

# Ordem reversa de dependências para downgrade
DROPS: tuple[str, ...] = (
    "drop table if exists domain_event",
    "drop table if exists usuario",
    "drop table if exists calibracao_prior",
    "drop table if exists dc_segment_cache",
    "drop table if exists pedido",
    "drop table if exists tarifa_canal",
    "drop table if exists certificado_elegibilidade",
    "drop table if exists lista_supressao",
    "drop table if exists policy_versao",
    "drop table if exists agente_evidence",
    "drop table if exists invocacao",
    "drop table if exists harness_run",
    "drop table if exists harness_case",
    "drop table if exists skill_versao",
    "drop table if exists agente",
    "drop table if exists telemetry_event",
    "drop table if exists launch",
    "drop table if exists drift_check",
    "drop table if exists resource_registry",
    "drop table if exists sync_run",
    "drop table if exists etapa_workflow",
    "drop table if exists experimento",
    "drop table if exists segmento",
    "drop table if exists aprovacao",
    "drop table if exists snapshot",
    "drop table if exists jornada_versao",
    "drop view if exists os_saude",
    "drop table if exists pendencia",
    "drop table if exists sla_clock",
    "drop table if exists os",
)


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DROPS:
        op.execute(stmt)
