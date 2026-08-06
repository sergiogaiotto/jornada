"""Metadados SQLAlchemy Core das tabelas persistidas em Postgres (A7 partes 1 e 2).

Espelham COLUNA A COLUNA o DDL do SDD §4.1 aplicado pelas migrações alembic
(0001..0012) — o DDL continua sendo a fonte de verdade: estas Tables existem só
para o adapter `RepositorioSql` montar insert/select tipados (jsonb↔dict, uuid,
text[], bytea, numeric, vector); NUNCA são usadas para create_all (schema é 100%
alembic). `agente_evidence` entra com o A11 (RAG §7.4): coluna `embedding` tipada
`pgvector.sqlalchemy.Vector(1024)` — dimensão FIXA do DDL (`EMBED_DIM` §3.1; mudar
exige re-embed §10.4); o índice HNSW cosine já vive na migração 0001.
As colunas `created_at` de ordenação (migração 0012 — segmento/experimento/aprovacao/
launch) NUNCA recebem valor do adapter: o default now() do banco registra a ordem de
inserção e o upsert por id a preserva.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

metadata = MetaData()

tabela_os = Table(
    "os",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("codigo", Text, nullable=False),
    Column("nome", Text, nullable=False),
    Column("tshirt", Text, nullable=False),
    Column("fase", Text, nullable=False),
    Column("briefing", JSONB, nullable=False),
    Column("frozen", JSONB),
    Column("created_by", UUID(as_uuid=True), nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

tabela_pendencia = Table(
    "pendencia",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("numero", Integer, nullable=False),
    Column("tipo", Text),
    Column("titulo", Text, nullable=False),
    Column("descricao", Text),
    Column("severidade", Text),
    Column("bloqueante", Boolean),
    Column("bloqueia_etapa", Text),
    Column("status", Text),
    Column("accountable", UUID(as_uuid=True)),
    Column("aceite", JSONB),
    Column("origem", Text),
    Column("via_ai", Boolean),
    Column("created_at", DateTime(timezone=True)),
)

tabela_sla_clock = Table(
    "sla_clock",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("etapa", Text, nullable=False),
    Column("prazo", DateTime(timezone=True), nullable=False),
    Column("estado", Text, nullable=False),
    Column("pausas", JSONB, nullable=False),
)

tabela_validacao_campo = Table(
    "validacao_campo",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("campo", Text, nullable=False),
    Column("veredito", Text, nullable=False),
    Column("checagens", JSONB, nullable=False),
    Column("evidencia", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    # emenda B01 (migração 0013): quem/quando da decisão VIGENTE — a leitura
    # GET /os/{id}/validacoes mostra autoria, e a linha é única por (os_id, campo)
    Column("por", Text),
    Column("atualizado_em", DateTime(timezone=True)),
)

tabela_os_thread = Table(
    "os_thread",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("campo", Text, nullable=False),
    Column("titulo", Text),
    Column("mensagens", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

tabela_documento_portao = Table(
    "documento_portao",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("portao", Text, nullable=False),
    Column("nome_arquivo", Text, nullable=False),
    Column("conteudo", LargeBinary, nullable=False),
    Column("hash", Text, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

tabela_pedido = Table(
    "pedido",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("solicitante", JSONB, nullable=False),
    Column("conteudo", JSONB, nullable=False),
    Column("completude", Numeric(4, 1)),
    Column("faltantes", ARRAY(Text)),
    Column("estado", Text),
    Column("os_id", UUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

tabela_etapa_workflow = Table(
    "etapa_workflow",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("ordem", Integer, nullable=False),
    Column("nome", Text, nullable=False),
    Column("responsavel", UUID(as_uuid=True)),
    Column("sla_dias", Integer),
    Column("estado", Text),
    Column("checklist", JSONB),
    Column("dependencias", JSONB),
    Column("hike_ref", JSONB),
)

tabela_hike_import_log = Table(
    "hike_import_log",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("os_id", UUID(as_uuid=True)),
    Column("hike_card_id", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("detalhe", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

tabela_domain_event = Table(
    "domain_event",
    metadata,
    Column("id", BigInteger, primary_key=True),  # identity — o banco atribui
    Column("tenant_id", Text),
    Column("os_id", UUID(as_uuid=True)),
    Column("type", Text, nullable=False),
    Column("payload", JSONB),
    Column("actor", Text),
    Column("via_ai", Boolean),
    Column("created_at", DateTime(timezone=True)),
)

# ===== A7 parte 2 — twin, governança, audiência, criativo, lançamento, otimização,
# Ateliê e ledger (DDL: 0001_core + 0003/0005/0006/0007/0008/0009/0010/0012) =====

tabela_jornada_versao = Table(
    "jornada_versao",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("versao", Integer, nullable=False),
    Column("grafo", JSONB, nullable=False),
    Column("hash", Text, nullable=False),  # char(64) no DDL
    Column("estado", Text),
    Column("premissas", JSONB),
    Column("custo_projetado", Numeric(12, 2)),
    Column("simulacao", JSONB),  # migração 0005 (M8)
    Column("previsto", JSONB),  # migração 0005 (M8)
    Column("created_at", DateTime(timezone=True)),  # migração 0010 (M7)
)

tabela_snapshot = Table(
    "snapshot",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("hash", Text, nullable=False),  # char(64) unique
    Column("conteudo", JSONB, nullable=False),
    Column("previsto", JSONB),
    Column("created_at", DateTime(timezone=True)),
)

tabela_aprovacao = Table(
    "aprovacao",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("token_hash", Text, nullable=False),  # char(64) unique
    Column("expira_em", DateTime(timezone=True), nullable=False),
    Column("alcada", Text, nullable=False),
    Column("decisao", Text),
    Column("decidido_em", DateTime(timezone=True)),
    Column("decidido_meta", JSONB),
    Column("ressalvas", JSONB),
    Column("invalidada_em", DateTime(timezone=True)),  # migração 0006 (A4)
    Column("invalidada_motivo", Text),  # migração 0006 (A4)
    Column("created_at", DateTime(timezone=True)),  # migração 0012 — só o banco escreve
)

tabela_segmento = Table(
    "segmento",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True)),
    Column("origem", Text, nullable=False),
    Column("dc_segment_id", Text),
    Column("sql_publico", Text),
    Column("criterios_resumo", Text),
    Column("contagem_bruta", Integer),
    Column("contagem_liquida", Integer),
    Column("waterfall", JSONB),
    Column("volume_abordagem", JSONB),
    Column("holdout_pct", Numeric(4, 1)),
    Column("frescor", JSONB),
    Column("created_at", DateTime(timezone=True)),  # migração 0012 — só o banco escreve
)

tabela_certificado = Table(
    "certificado_elegibilidade",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("hash", Text, nullable=False),  # char(64)
    Column("suprimidos", JSONB, nullable=False),
    Column("liquido", Integer, nullable=False),
    Column("emitido_em", DateTime(timezone=True)),
    Column("valido_ate", DateTime(timezone=True)),
    Column("last_mile", JSONB),
)

tabela_dc_segment_cache = Table(
    "dc_segment_cache",
    metadata,
    Column("id", Text, primary_key=True),  # id do segmento no Data Cloud
    Column("tenant_id", Text, nullable=False),
    Column("nome", Text),
    Column("criterios_resumo", Text),
    Column("membros", Integer),
    Column("dmos", ARRAY(Text)),
    Column("republicado_em", DateTime(timezone=True)),
    Column("ciclo", Text),
    Column("status", Text),
    Column("atualizado_em", DateTime(timezone=True)),
)

tabela_criativo = Table(
    "criativo",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("kv_master", JSONB, nullable=False),
    Column("kv_master_ref", Text),
    Column("celulas", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
)

tabela_experimento = Table(
    "experimento",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("holdout_pct", Numeric(4, 1), nullable=False),
    Column("n_minimo", Integer, nullable=False),
    Column("mde_pp", Numeric(5, 2), nullable=False),
    Column("janela_dias", Integer, nullable=False),
    Column("metricas", JSONB, nullable=False),
    Column("travado_em", DateTime(timezone=True)),
    Column("estado", Text),
    Column("resultado", JSONB),
    Column("created_at", DateTime(timezone=True)),  # migração 0012 — só o banco escreve
)

tabela_sync_run = Table(
    "sync_run",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("ambiente", Text),
    Column("fase", Text),
    Column("plano", JSONB),
    Column("resultado", JSONB),
    Column("estado", Text),
    Column("api_calls", Integer),
    Column("created_at", DateTime(timezone=True)),
)

tabela_resource_registry = Table(
    "resource_registry",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("no_jgc", Text, nullable=False),
    Column("tipo_sfmc", Text, nullable=False),
    Column("external_key", Text, nullable=False),  # unique(tenant_id, ambiente, external_key)
    Column("sfmc_id", Text),
    Column("ambiente", Text),
    Column("snapshot_hash", Text),  # char(64)
)

tabela_drift_check = Table(
    "drift_check",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("snapshot_id", UUID(as_uuid=True)),
    Column("recurso", Text),
    Column("estado", Text),
    Column("diff", JSONB),
    Column("resolucao", Text),
    Column("checked_at", DateTime(timezone=True)),
)

tabela_preflight_run = Table(
    "preflight_run",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("ambiente", Text),
    Column("resultado", Text, nullable=False),
    Column("itens", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True)),
)

tabela_launch = Table(
    "launch",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("snapshot_id", UUID(as_uuid=True), nullable=False),
    Column("ondas", JSONB, nullable=False),
    Column("onda_atual", Integer),
    Column("estado", Text),
    Column("breakers", JSONB, nullable=False),
    Column("eventos", JSONB),
    Column("created_at", DateTime(timezone=True)),  # migração 0012 — só o banco escreve
)

tabela_telemetry_event = Table(
    "telemetry_event",
    metadata,
    Column("id", BigInteger, primary_key=True),  # identity — o banco atribui
    Column("tenant_id", Text, nullable=False),
    Column("os_id", UUID(as_uuid=True)),
    Column("no_jgc", Text),
    Column("canal", Text),
    Column("tipo", Text),
    Column("contato_hash", Text),  # char(64) — NUNCA msisdn/e-mail em claro (§10.2)
    Column("fonte", Text),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("payload", JSONB),
)

tabela_incidente = Table(
    "incidente",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("launch_id", UUID(as_uuid=True)),
    Column("sev", Text, nullable=False),
    Column("tipo", Text, nullable=False),
    Column("titulo", Text, nullable=False),
    Column("descricao", Text),
    Column("estado", Text, nullable=False),
    Column("meta", JSONB, nullable=False),
    Column("aberto_em", DateTime(timezone=True)),
    Column("resolvido_em", DateTime(timezone=True)),
)

tabela_proposta_otimizacao = Table(
    "proposta_otimizacao",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("jornada_base_id", UUID(as_uuid=True), nullable=False),
    Column("titulo", Text, nullable=False),
    Column("motivacao", Text),
    Column("grafo_proposto", JSONB, nullable=False),
    Column("diff", JSONB, nullable=False),
    Column("impacto", JSONB, nullable=False),
    Column("esforco", Integer, nullable=False),
    Column("risco", Numeric(4, 2), nullable=False),
    Column("score", Numeric(10, 6)),
    Column("estado", Text, nullable=False),
    Column("motivo_rejeicao", Text),
    Column("jornada_gerada_id", UUID(as_uuid=True)),
    Column("via_ai", Boolean),
    Column("decidido_por", Text),
    Column("decidido_em", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
)

tabela_aprendizado = Table(
    "aprendizado",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("os_id", UUID(as_uuid=True), nullable=False),
    Column("origem", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("texto", Text, nullable=False),
    Column("meta", JSONB, nullable=False),
    Column("herdado_de", UUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True)),
)

tabela_calibracao_prior = Table(
    "calibracao_prior",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text),
    Column("tipo_campanha", Text),
    Column("versao", Integer),
    Column("priors", JSONB, nullable=False),
    Column("score", Numeric(4, 2)),
    Column("backtest", JSONB),
    Column("publicada_em", DateTime(timezone=True)),
)

tabela_agente = Table(
    "agente",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("nome", Text, nullable=False),  # unique GLOBAL (§4.1)
    Column("camada", Text),
    Column("etapa_workflow", Text),
    Column("modelo_perfil", Text),
    Column("deterministico", Boolean),
)

tabela_skill_versao = Table(
    "skill_versao",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("agente_id", UUID(as_uuid=True), nullable=False),
    Column("versao", Text, nullable=False),  # unique(agente_id, versao)
    Column("skill_md", Text, nullable=False),
    Column("execution_profile", JSONB),
    Column("bases_rag", ARRAY(Text)),
    Column("estado", Text),
    Column("harness_score", Numeric(5, 2)),
    Column("publicada_em", DateTime(timezone=True)),
)

tabela_harness_case = Table(
    "harness_case",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("agente_id", UUID(as_uuid=True), nullable=False),
    Column("input", JSONB, nullable=False),
    Column("esperado", JSONB, nullable=False),
    Column("dimensoes", ARRAY(Text)),
)

tabela_harness_run = Table(
    "harness_run",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("skill_versao_id", UUID(as_uuid=True), nullable=False),
    Column("resultados", JSONB, nullable=False),
    Column("score", Numeric(5, 2)),
    Column("passou", Boolean),
    Column("created_at", DateTime(timezone=True)),
)

tabela_invocacao = Table(
    "invocacao",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("os_id", UUID(as_uuid=True)),
    Column("agente_id", UUID(as_uuid=True)),
    Column("skill_versao", Text),
    Column("usuario_portador", UUID(as_uuid=True), nullable=False),
    Column("input", JSONB),
    Column("output", JSONB),
    Column("evidencias", JSONB),
    Column("judge", JSONB),
    Column("aceito_por", UUID(as_uuid=True)),
    Column("aceito_em", DateTime(timezone=True)),
    Column("tokens", Integer),
    Column("latencia_ms", Integer),
    Column("created_at", DateTime(timezone=True)),
)

tabela_agente_evidence = Table(
    "agente_evidence",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("base", Text, nullable=False),
    Column("ref", Text),
    Column("chunk", Text, nullable=False),
    Column("meta", JSONB),
    Column("embedding", Vector(1024), nullable=False),  # Qwen3-Embedding-0.6B; EMBED_DIM §3.1
)

tabela_policy_versao = Table(
    "policy_versao",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("versao", Integer, nullable=False),
    Column("conteudo", JSONB, nullable=False),
    Column("estado", Text),
    Column("publicada_em", DateTime(timezone=True)),
)

# --- IA Responsável (F03): `politica_ia` — migração 0016 ---
# Mesmo desenho de `policy_versao` (versão sequencial por tenant + conteúdo jsonb), com
# a AUTORIA que falta lá: quem escreveu e quem publicou, gravados na própria linha. Para
# a pergunta "quem autorizou a IA a decidir sozinha, e quando?" correlacionar outbox não
# basta — a resposta tem de estar na linha que governa.
tabela_politica_ia = Table(
    "politica_ia",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("versao", Integer, nullable=False),
    Column("conteudo", JSONB, nullable=False),
    Column("estado", Text),
    Column("autor_id", UUID(as_uuid=True)),
    Column("autor_nome", Text),
    Column("criada_em", DateTime(timezone=True)),
    Column("publicada_em", DateTime(timezone=True)),
    Column("publicado_por_id", UUID(as_uuid=True)),
    Column("publicado_por_nome", Text),
    Column("motivo", Text),
)

# --- Identidade (emenda G01): `usuario` do §4.1 com corpo + `sessao` — migração 0015 ---
tabela_usuario = Table(
    "usuario",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("tenant_id", Text, nullable=False),
    Column("nome", Text),
    Column("email", Text, nullable=False),  # unique POR TENANT sobre lower(email) — 0015
    Column("papeis", ARRAY(Text)),
    Column("senha_hash", Text),  # argon2id (PHC string); NUNCA sai do adapter/serviço
    Column("ativo", Boolean),
    Column("senha_expirada", Boolean),
    Column("criado_em", DateTime(timezone=True)),
    Column("criado_por", UUID(as_uuid=True)),
    Column("ultimo_acesso", DateTime(timezone=True)),
    Column("tentativas_falhas", Integer),
    Column("bloqueado_ate", DateTime(timezone=True)),
)

tabela_sessao = Table(
    "sessao",
    metadata,
    # `id` é TEXT: guarda o sha256 do token do cookie (o segredo nunca chega ao banco)
    Column("id", Text, primary_key=True),
    Column("usuario_id", UUID(as_uuid=True), nullable=False),
    Column("criada_em", DateTime(timezone=True), nullable=False),
    Column("expira_em", DateTime(timezone=True), nullable=False),
    Column("revogada_em", DateTime(timezone=True)),
    Column("ip", Text),
    Column("user_agent", Text),
)
