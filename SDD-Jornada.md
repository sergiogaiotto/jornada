# SDD — Jornada v1.0.0

**Documentação Técnica: Framework de Building Blocks de IA**
Codinome: **Jornada** · materializa o plano **Martech v1.2** (Digital Twin do Journey Builder / SFMC)
Abordagem: **Spec-Driven Development** — este documento é o contrato; código que diverge dele está errado até que o SDD seja emendado (ver §1.3).
Referência visual/funcional (mocks das 18 telas, obrigatória): https://claude.ai/code/artifact/7e01bb7a-44e8-4dbc-ba3c-e2382e53b634

---

## 1. Visão e regras do jogo

### 1.1 O que é
Plataforma que acelera o ciclo de vida completo de campanhas (pensada → discutida → criada → avaliada → configurada → disparada → monitorada → otimizada) operando como **Digital Twin do Journey Builder** do Salesforce Marketing Cloud:

1. **O twin é a fonte da verdade** — a jornada é um grafo canônico JSON versionado (JGC, §5), snapshot imutável por hash; um compilador determinístico plan/apply materializa no SFMC; monitor de drift acusa edição por fora.
2. **Nada dispara sem ensaio** — simulação Monte Carlo é portão obrigatório; o "Previsto" congelado é a régua do pós-disparo (previsto × realizado em todo KPI).
3. **IA copilota, humano aprova** — mesh de agentes (Maestro→Triagem→Especialista) sempre como prévia/diff com Aplicar/Rejeitar; ledger `via_ai`; **compliance é código determinístico, nunca LLM**.

### 1.2 Escopo do v1 (e non-goals)
Inclui: as 18 telas do plano (T1–T16 + T4a Esteira/ex-Hike + T5a Data Cloud), mesh de agentes com harness, compilador SFMC (com **mock server** para dev), simulador, governança completa (pendências, SLAs, link mágico, certificado LGPD), conectores Data Cloud e Hike-import.
**Non-goals v1:** custom activities de terceiros no twin (viram "nó de exceção"), MMS/mídia paga, edição de jornada ao vivo sem novo ciclo, replicar o Data Cloud, multi-BU numa mesma jornada.

### 1.3 Regras SDD para o agente implementador (Fable 5)
1. Implementar **na ordem dos milestones** (§9). Não avançar módulo com DoD aberto.
2. Para cada módulo: primeiro contratos (OpenAPI + Pydantic + DDL/migração + testes de aceite), depois implementação.
3. Toda divergência necessária → editar este SDD na seção afetada + entrada no `CHANGELOG-SDD.md` (data, motivo, impacto) no mesmo PR.
4. Critérios de aceite (Given/When/Then) viram testes automatizados com o mesmo ID (ex.: `test_M5_A3`).
5. Nunca inventar endpoint/campo fora do SDD; nunca colocar PII em prompt de LLM; nunca chamar SFMC/Data Cloud reais em teste (usar mocks §11).
6. Commits convencionais (`feat(m5): ...`); 1 PR por entrega de módulo ou fatia coerente.

---

## 2. Arquitetura

### 2.1 Diamante 4D + Hexagonal
- **Data** — adapters de fontes (Data Cloud, Hike, telemetria ENS/extracts), read model de ativação com TTL, catálogo com SLA de frescor, RAG pgvector.
- **Domain** — entidades e serviços puros (sem I/O): Campanha/OS, JornadaVersão(JGC), Segmento, Criativo, Experimento, Snapshot, pendência, SLA engine, TarifaCanal, Política.
- **Decision** — mesh de agentes (LangGraph), simulador, Guard determinístico, Contact Governor, modelos STO/frequência, uplift.
- **Delivery** — API FastAPI, compilador SFMC (REST+SOAP), link mágico, Notification Hub, SPA React.

Hexagonal: `domain/` não importa nada de `adapters/`. Portas = `Protocol`s Python em `application/ports/`. Adapters implementam portas. LLM, SFMC, Data Cloud, e-mail/Teams, relógio e RNG ficam atrás de portas (RNG/clock injetáveis → simulador reprodutível por seed).

### 2.2 Estrutura de pastas (monorepo)
```
jornada/
├── SDD-Jornada.md  CHANGELOG-SDD.md  readme.txt  requirements.txt  .env.example
├── docker-compose.yml           # api, web, db(pgvector), mock-sfmc, mock-datacloud, mailpit
├── backend/
│   ├── app/main.py              # FastAPI factory + routers /api/v1
│   ├── app/config.py            # pydantic-settings (lê .env — §3)
│   ├── domain/<contexto>/       # campanha, jornada, audiencia, criativo, experimento, governanca, custo
│   ├── application/ports/       # LLMPort, EmbeddingPort, SFMCPort, DataCloudPort, NotifyPort, ClockPort, RngPort
│   ├── application/services/    # casos de uso (orquestram domain via ports)
│   ├── adapters/{llm,sfmc,datacloud,hike,notify,persistence}/
│   ├── agents/{skills/*.skill.md, graphs/, harness/, guard/}   # guard NÃO usa LLM
│   ├── api/v1/                  # routers por módulo (§8) — nomes = tags OpenAPI
│   ├── migrations/              # alembic
│   └── tests/{unit,contract,acceptance}/
├── frontend/                    # Vite + React + TS (§12)
└── mocks/{sfmc-server/, datacloud-server/, seeds/}   # FastAPI apps de simulação + fixtures demo
```

### 2.3 Eventos de domínio
Tabela `domain_event` (outbox) + `LISTEN/NOTIFY` do Postgres no v1 (porta `EventBusPort` permite trocar por Redis Streams sem tocar o domínio). Todo evento: `{id, tenant_id, os_id?, type, payload_json, actor, via_ai, created_at}`. Tipos mínimos: `os.phase_changed`, `pendencia.opened|resolved|accepted`, `gate.passed|blocked`, `snapshot.created|approved`, `sync.applied`, `drift.detected`, `launch.wave_advanced|breaker_tripped|killed`, `telemetry.ingested`, `agent.invoked`, `policy.published`.

---

## 3. Configuração — LLM HubGPU, embeddings e `.env`

Endpoint OpenAI-compatible: `POST {base_url}/chat/completions`. `api_key = "not-needed"` é **válido** (proxy autentica por outra via) — o client `openai` recebe essa string literal. Roteamento por perfil: **120B** = especialistas, judge do harness, Insight NL→SQL; **20B** = triagens, classificações leves, resumos de UI. Embeddings: client adiciona sufixo `/embeddings` — não incluir no base_url.

### 3.1 `.env.example` (copiar integralmente; valores do HubGPU conforme anexo)
```env
# --- App ---
APP_ENV=dev                      # dev|homolog|prod
APP_SECRET=change-me             # JWT/link mágico (prod: injetar via vault)
APP_BASE_URL=http://localhost:8000
WEB_BASE_URL=http://localhost:5173
DEFAULT_TENANT=torre-movel

# --- Banco ---
DATABASE_URL=postgresql+asyncpg://jornada:jornada@db:5432/jornada

# --- LLM HubGPU (OpenAI-compatible) ---
LLM_120B_BASE_URL=https://hub-gpus.claro.com.br/gpt120/v1
LLM_120B_MODEL=openai/gpt-oss-120b
LLM_20B_BASE_URL=https://hub-gpus.claro.com.br/gpt20/v1
LLM_20B_MODEL=openai/gpt-oss-20b
LLM_API_KEY=not-needed
LLM_TIMEOUT_S=300                # default 300s (config do hub)
LLM_MAX_RETRIES=2
LLM_DEGRADED_MODE=auto           # auto|forced_off — §10.6 (fila + modo manual)

# --- Embeddings (Qwen3 via hub interno; reusa scheme://host do OSS-120B se path relativo) ---
EMBED_BASE_URL=https://hub-gpus.claro.com.br/embed06b/v1
EMBED_MODEL=Qwen/Qwen3-Embedding-0.6B
EMBED_DIM=1024                   # padrão do modelo; mudar exige re-embed da collection (§10.4)
EMBED_TIMEOUT_S=30               # emenda A11: timeout próprio (curto) do POST /embeddings
RAG_COLLECTION=agente_evidence   # pgvector

# --- SFMC (dev aponta para o mock) ---
SFMC_AUTH_URL=http://mock-sfmc:8080/v2/token
SFMC_REST_URL=http://mock-sfmc:8080/rest
SFMC_SOAP_URL=http://mock-sfmc:8080/soap
SFMC_CLIENT_ID=mock  SFMC_CLIENT_SECRET=mock  SFMC_ACCOUNT_MID=mock
SFMC_API_BUDGET_PER_APPLY=200    # orçamento de chamadas por apply

# --- Data Cloud (dev aponta para o mock) ---
DC_AUTH_URL=http://mock-datacloud:8081/oauth/token
DC_API_URL=http://mock-datacloud:8081/api/v2
DC_CLIENT_ID=mock  DC_CLIENT_SECRET=mock

# --- Notificações / dev ---
SMTP_URL=smtp://mailpit:1025     TEAMS_WEBHOOK_URL=
DEMO_MODE=true                   # carrega seeds OS-2026-0457 (§11.4)

# --- Observabilidade (Langfuse self-hosted — §10.8) ---
LANGFUSE_HOST=http://langfuse:3000
LANGFUSE_PUBLIC_KEY=pk-lf-dev
LANGFUSE_SECRET_KEY=sk-lf-dev
LANGFUSE_ENABLED=true            # false → no-op (app nunca depende do Langfuse)
```

### 3.2 `requirements.txt` inicial (backend)
```
fastapi~=0.115  uvicorn[standard]~=0.30  pydantic~=2.9  pydantic-settings~=2.5
sqlalchemy[asyncio]~=2.0  alembic~=1.13  asyncpg~=0.29  psycopg2-binary~=2.9  pgvector~=0.3
langgraph~=0.2  langgraph-checkpoint-postgres~=2.0  deepagents
openai~=1.50  httpx~=0.27  tenacity~=9.0  zeep~=4.2  langfuse~=2.53
python-jose[cryptography]~=3.3  structlog~=24.4  python-docx~=1.1  orjson~=3.10
pytest~=8.3  pytest-asyncio~=0.24  respx~=0.21  ruff~=0.6  mypy~=1.11
```
(Formato real: uma dependência por linha. `zeep` = SOAP SFMC; `deepagents` = Deep-Agent Harness; `python-docx` = documentos executivos dos portões; `psycopg2-binary` = driver síncrono dos repositórios SQL — emenda A7, §4.)

### 3.3 Seleção de ferramentas (critério GitHub: manutenção ativa, adoção, licença permissiva)
| Necessidade | Escolha | Por quê (GitHub) |
|---|---|---|
| API/OpenAPI | FastAPI + Pydantic v2 | padrão de-facto, OpenAPI nativo em `/docs` |
| Orquestração de agentes | LangGraph + checkpoint-postgres | grafos com `interrupt()` humano e estado durável — exigência dos portões |
| Harness de agentes | deepagents (Deep-Agent Harness) | pedido da spec; complementa LangGraph em agentes de longa duração |
| LLM/Embeddings client | openai (base_url custom) | endpoint do hub é OpenAI-compatible |
| RAG | pgvector | mantém PostgreSQL como banco único |
| SOAP SFMC | zeep | cliente SOAP Python mais mantido |
| Retry/backoff | tenacity | rate limits SFMC/hub |
| Canvas | @xyflow/react (React Flow 12) | referência do mock; MIT |
| Front | Vite+React+TS, Tailwind, TanStack Query+Table, zustand, Recharts | ecossistema dominante; gráficos previsto×realizado |
| Qualidade | ruff, mypy, pytest, respx, pre-commit | lint+type+test padrão |

---

## 4. Modelo de dados (PostgreSQL — migração Alembic `0001_core`)

Convenções: PK `id UUID default gen_random_uuid()`; todas as tabelas de negócio têm `tenant_id text not null` + índice; `created_at/updated_at timestamptz`; soft-delete não — histórico via event sourcing/versões. Extensões: `pgcrypto`, `vector`.

**Persistência SQL ativa (emenda A7 partes 1 e 2, 2026-08-05 — ver CHANGELOG-SDD.md):** TODOS os agregados do DDL §4.1 são persistidos em Postgres pelo adapter `adapters/persistence/sql.py` (`RepositorioSql`, engine **síncrono** psycopg2; as portas de repositório §2.1 são síncronas) sobre o schema aplicado pelas migrações alembic (nunca `create_all`): núcleo OS/governança, intake, esteira, twin (`jornada_versao` com simulação/Previsto), `snapshot`/`aprovacao`, audiência (`segmento`/`certificado_elegibilidade`/`dc_segment_cache`), `criativo`, `experimento`, compilador (`sync_run`/`resource_registry`/`drift_check`/`preflight_run`), lançamento (`launch`/`telemetry_event`/`incidente`), otimização (`proposta_otimizacao`/`aprendizado`/`calibracao_prior`), Ateliê (`agente`/`skill_versao`/`harness_*`/`policy_versao`), o ledger `invocacao` e o outbox `domain_event` (§2.3). **`agente_evidence` (emenda A11, 2026-08-05):** também persistida — o adapter grava `embedding vector(1024)` (via EmbeddingPort §3/§7.4) e busca top-k por cosseno (`cosine_distance`, índice HNSW da migração 0001) filtrada por tenant + bases; evidência promovida SEM vetor (apuração M11 — caminho determinístico §10.6 que nunca depende do hub) cai no fallback em memória do processo até o `rag reindex` (§7.4). Seleção por config no startup: `DATABASE_URL` setado no ambiente **e** alcançável → repos SQL; senão repositório em memória (fallback dev sem docker). Escritas `adicionar_*`/`salvar_*` são **upsert por `id`** (identity do banco em `domain_event`/`telemetry_event`) — com os ids uuid5 determinísticos das seeds (§11.4/A15), restart re-semeia sem duplicar. Listas com contrato "o último é o corrente" (`segmentos[-1]`, `aprovacoes[-1]`, `experimento_da_os`, launch de referência) ordenam pela coluna `created_at` de ordem de inserção (migração `0012_a7_ordem_estavel` — escrita SÓ pelo default `now()` do banco e preservada no upsert; as dataclasses de domínio não mudam). Com SQL ativo o boot semeia roster+política v1 do Ateliê (idempotente — a FK `invocacao.agente_id → agente` exige as linhas antes do primeiro ledger; em memória segue a semeadura tardia das rotas). Mutação pós-leitura exige `salvar_*` explícito — por isso a porta ganhou `salvar_certificado` (re-varredura last-mile do pré-voo).

### 4.1 DDL núcleo (integral)
```sql
create table os (                            -- Campanha/Ordem de Serviço
  id uuid primary key default gen_random_uuid(),
  tenant_id text not null, codigo text unique not null,        -- ex. OS-2026-0457
  nome text not null, tshirt text not null check (tshirt in ('P','M','G','GG')),
  fase text not null default 'pensada' check (fase in
    ('pensada','discutida','criada','avaliada','configurada','disparada','monitorada','encerrada')),
  briefing jsonb not null default '{}',                        -- 14 campos (§8.M3)
  frozen jsonb,                    -- congelado no GO: {agent_versions, policy_version, tarifario_id, slas}
  created_by uuid not null, created_at timestamptz default now(), updated_at timestamptz default now()
);
create table sla_clock (
  id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
  etapa text not null, prazo timestamptz not null,
  estado text not null default 'correndo' check (estado in ('correndo','pausado_cliente','bloqueado_pendencia','concluido')),
  pausas jsonb not null default '[]'                            -- [{de,ate,motivo}]
);

create table pendencia (
  id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
  numero int not null, tipo text check (tipo in ('risk','assumption','issue','dependency')),
  titulo text not null, descricao text, severidade text check (severidade in ('baixa','media','alta')),
  bloqueante boolean default true, bloqueia_etapa text,
  status text default 'aberta' check (status in ('aberta','resolvida','aceita')),
  accountable uuid, aceite jsonb,                               -- {por, em, justificativa}
  origem text, via_ai boolean default false, created_at timestamptz default now()
);

-- Saúde NUNCA é coluna: view derivada (atraso vs SLA + pendências abertas + breakers + incidentes)
-- (definida após sla_clock/pendencia, que ela referencia — emenda M0, ver CHANGELOG-SDD.md)
create view os_saude as
  select o.id as os_id,
    case when exists(select 1 from pendencia r where r.os_id=o.id and r.status='aberta' and r.bloqueante)
      or exists(select 1 from sla_clock s where s.os_id=o.id and s.estado='correndo' and now()>s.prazo)
    then 'em_risco' else 'normal' end as saude
  from os o;

create table jornada_versao (                 -- o TWIN: versões do grafo canônico
  id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
  versao int not null, grafo jsonb not null,                    -- JGC (§5), validado por JSON Schema
  hash char(64) not null,                                       -- sha256 do JGC canonicalizado (RFC 8785)
  estado text default 'rascunho' check (estado in ('rascunho','simulado','aprovado','publicado','arquivado')),
  premissas jsonb default '[]', custo_projetado numeric(12,2),
  simulacao jsonb, previsto jsonb,            -- saída do Ensaio Geral (§6) e Previsto congelado (emenda M8, migração 0005)
  created_at timestamptz default now(),       -- quando a versão nasceu (emenda M7 versionamento, migração 0010)
  unique(os_id, versao)
);

create table snapshot (                       -- pacote imutável de aprovação
  id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
  hash char(64) unique not null,              -- hash composto: JGC+SQL+criativos+políticas+custo+experimento
  conteudo jsonb not null, previsto jsonb,    -- Previsto congelado da simulação
  created_at timestamptz default now()
);

create table aprovacao (                      -- link mágico
  id uuid primary key default gen_random_uuid(), snapshot_id uuid references snapshot not null,
  token_hash char(64) unique not null, expira_em timestamptz not null, alcada text not null,
  decisao text check (decisao in ('aprovado','aprovado_ressalvas','reprovado')),
  decidido_em timestamptz, decidido_meta jsonb,                 -- ip, device, otp?
  ressalvas jsonb default '[]',                                 -- viram pendências automaticamente
  invalidada_em timestamptz, invalidada_motivo text,            -- A4: custo >10% pós-aprovação (emenda M8 parte 2, migração 0006)
  created_at timestamptz default now()        -- ordem de inserção durável (emenda A7 parte 2, migração 0012)
);

create table segmento (
  id uuid primary key default gen_random_uuid(), os_id uuid references os,
  origem text not null check (origem in ('estudio_sql','data_cloud')),
  dc_segment_id text, sql_publico text, criterios_resumo text,
  contagem_bruta int, contagem_liquida int, waterfall jsonb,    -- [{etapa, corte, restante, motivo}]
  volume_abordagem jsonb,                                        -- {email:{n,pct},sms:{...},push:{...},whatsapp:{...}}
  holdout_pct numeric(4,1) default 10.0, frescor jsonb,          -- {fonte: ultima_atualizacao}
  created_at timestamptz default now()        -- ordem de inserção durável (emenda A7 parte 2, migração 0012)
);

create table experimento (
  id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
  holdout_pct numeric(4,1) not null, n_minimo int not null, mde_pp numeric(5,2) not null,
  janela_dias int not null, metricas jsonb not null, travado_em timestamptz,
  estado text default 'pre_registrado' check (estado in ('pre_registrado','em_apuracao','apurado')),
  resultado jsonb,                                               -- {lift, ic95:[a,b], significativo, roas}
  created_at timestamptz default now()        -- ordem de inserção durável (emenda A7 parte 2, migração 0012)
);

create table etapa_workflow (                 -- T4a: esteira ex-Hike
  id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
  ordem int not null, nome text not null,     -- briefing|discovery|audiencia|criativos|configuracao|disparo|acompanhamento
  responsavel uuid, sla_dias int, estado text default 'pendente'
    check (estado in ('pendente','em_andamento','concluida','bloqueada')),
  checklist jsonb default '[]',               -- [{item, feito, por, em}] — subtarefas de Criativos/Acompanhamento
  dependencias jsonb default '[]', hike_ref jsonb               -- {card_id, importado_em, url_arquivada}
);

create table sync_run (                       -- compilador plan/apply
  id uuid primary key default gen_random_uuid(), snapshot_id uuid references snapshot not null,
  ambiente text check (ambiente in ('homolog','prod')), fase text check (fase in ('plan','apply')),
  plano jsonb,                                -- [{recurso, acao: criar|alterar|manter|destruir, aviso?}]
  resultado jsonb, estado text default 'pendente'
    check (estado in ('pendente','ok','parcial','revertido','falhou')),
  api_calls int default 0, created_at timestamptz default now()
);

create table resource_registry (              -- twin ↔ SFMC
  id uuid primary key default gen_random_uuid(), tenant_id text not null,
  no_jgc text not null, tipo_sfmc text not null,               -- dataExtension|eventDefinition|journey|asset|automation
  external_key text not null, sfmc_id text, ambiente text, snapshot_hash char(64),
  unique(tenant_id, ambiente, external_key)
);

create table drift_check (
  id uuid primary key default gen_random_uuid(), snapshot_id uuid references snapshot,
  recurso text, estado text check (estado in ('em_sincronia','drift_sfmc','twin_a_frente')),
  diff jsonb, resolucao text check (resolucao in ('adopt','enforce','excecao') or resolucao is null),
  checked_at timestamptz default now()
);

create table launch (                         -- T12
  id uuid primary key default gen_random_uuid(), snapshot_id uuid references snapshot not null,
  ondas jsonb not null default '[{"pct":1},{"pct":10},{"pct":100}]', onda_atual int default 0,
  estado text default 'armado' check (estado in ('armado','em_rampa','pausado_breaker','morto','concluido')),
  breakers jsonb not null,                    -- limites da política congelada
  eventos jsonb default '[]',
  created_at timestamptz default now()        -- ordem de inserção durável (emenda A7 parte 2, migração 0012)
);

create table telemetry_event (
  id bigint generated always as identity primary key, tenant_id text not null,
  os_id uuid, no_jgc text, canal text, tipo text,               -- sent|delivered|open|click|bounce|optout|conversion
  contato_hash char(64),                      -- NUNCA msisdn/e-mail em claro
  fonte text check (fonte in ('ens','extract')), ts timestamptz not null, payload jsonb
);
create index on telemetry_event (os_id, tipo, ts);

-- ===== Mesh de agentes =====
create table agente (
  id uuid primary key default gen_random_uuid(), tenant_id text not null,
  nome text unique not null,                  -- consultor|engineer|activate|flow|visual|copy|content|sync|publish|simulate|persona|insight|optimize|calibrate|cost|doc|maestro|triagem_*
  camada text check (camada in ('maestro','triagem','especialista')),
  etapa_workflow text, modelo_perfil text check (modelo_perfil in ('120b','20b')),
  deterministico boolean default false        -- guard=true (NÃO invoca LLM)
);
create table skill_versao (
  id uuid primary key default gen_random_uuid(), agente_id uuid references agente not null,
  versao text not null, skill_md text not null, execution_profile jsonb,
  bases_rag text[] default '{}', estado text default 'draft' check (estado in ('draft','em_revisao','publicada')),
  harness_score numeric(5,2), publicada_em timestamptz, unique(agente_id, versao)
);
create table harness_case (                   -- golden dataset
  id uuid primary key default gen_random_uuid(), agente_id uuid references agente not null,
  input jsonb not null, esperado jsonb not null, dimensoes text[] default '{correcao,evidencia,compliance,formato}'
);
create table harness_run (
  id uuid primary key default gen_random_uuid(), skill_versao_id uuid references skill_versao not null,
  resultados jsonb not null, score numeric(5,2), passou boolean, created_at timestamptz default now()
);
create table invocacao (                      -- ledger via_ai (LGPD Art. 20 — reconstruível)
  id uuid primary key default gen_random_uuid(), tenant_id text not null, os_id uuid,
  agente_id uuid references agente, skill_versao text, usuario_portador uuid not null,
  input jsonb, output jsonb, evidencias jsonb default '[]',     -- ids de chunks RAG citados
  judge jsonb, aceito_por uuid, aceito_em timestamptz,
  tokens int, latencia_ms int, created_at timestamptz default now()
);
create table agente_evidence (                -- RAG (collection única, filtrada por metadados)
  id uuid primary key default gen_random_uuid(), tenant_id text not null,
  base text not null,                         -- dicionario_dados|criativos|governanca|inventario_jornadas|resultados|historico_campanhas|ofertas|tarifario
  ref text, chunk text not null, meta jsonb default '{}',
  embedding vector(1024) not null             -- Qwen3-Embedding-0.6B; EMBED_DIM
);
create index on agente_evidence using hnsw (embedding vector_cosine_ops);

-- ===== Governança/plataforma =====
create table policy_versao (
  id uuid primary key default gen_random_uuid(), tenant_id text not null, versao int not null,
  conteudo jsonb not null,  -- {frequency_cap, quiet_hours, blackout, holdout_min, alcadas:[{ate,papel}], retencao_dias, breakers, precedencia}
  estado text default 'draft' check (estado in ('draft','publicada')), publicada_em timestamptz
);
create table lista_supressao (                -- 7 listas
  tenant_id text not null, lista text not null check (lista in
    ('blacklist','fraude','nao_perturbe','optout','procon','inadimplente','reprovado_credito')),
  contato_hash char(64) not null, atualizado_em timestamptz default now(),
  primary key (tenant_id, lista, contato_hash)
);
create table certificado_elegibilidade (
  id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
  hash char(64) not null, suprimidos jsonb not null,            -- {lista: contagem}
  liquido int not null, emitido_em timestamptz default now(), valido_ate timestamptz,
  last_mile jsonb                                                -- re-varredura no disparo
);
create table tarifa_canal (
  tenant_id text not null, canal text not null, custo_unit numeric(10,6) not null,
  vigencia daterange not null, primary key (tenant_id, canal, vigencia)
);
create table pedido (                         -- intake do Consultor (T2; criação na app)
  id uuid primary key default gen_random_uuid(), tenant_id text not null,
  solicitante jsonb not null, conteudo jsonb not null default '{}',
  completude numeric(4,1) default 0, faltantes text[] default '{}',
  -- emenda 2026-08-05 (CRUD §8-M3): + 'arquivado' (soft) e created/updated_at (migração 0011)
  estado text default 'rascunho' check (estado in ('rascunho','completo','convertido','arquivado')),
  os_id uuid references os, created_at timestamptz default now(), updated_at timestamptz default now()
);
create table dc_segment_cache (               -- T5a (consulta, não cópia)
  id text primary key, tenant_id text not null, nome text, criterios_resumo text,
  membros int, dmos text[], republicado_em timestamptz, ciclo text, status text, atualizado_em timestamptz
);
create table calibracao_prior (
  id uuid primary key default gen_random_uuid(), tenant_id text, tipo_campanha text,
  versao int, priors jsonb not null, score numeric(4,2), backtest jsonb, publicada_em timestamptz
);
create table usuario (id uuid primary key, tenant_id text, nome text, email text unique, papeis text[]);
create table domain_event (id bigint generated always as identity primary key, tenant_id text,
  os_id uuid, type text not null, payload jsonb, actor text, via_ai boolean default false,
  created_at timestamptz default now());
```
Tabelas auxiliares (colunas óbvias, criar na migração do módulo que as usa): `criativo` (matriz canal×variante, estado por célula, kv_master_ref), `incidente` (sev1..3, kill/retomada 2 aprovadores), `notificacao`, `custo_realizado`, `hike_import_log`, `documento_portao` (docx gerados), `preflight_run` (bateria do pré-voo M9: itens pass/warn/fail com evidência + resultado verde/amarelo/vermelho por snapshot×ambiente), `proposta_otimizacao` (M11: proposta do optimize — diff JGC + impacto pré-simulado + esforço/risco/score; aprovar referencia a nova jornada_versao), `aprendizado` (M11: memória da retro — origem proposta/experimento, status aceito/sinal/promovido, `herdado_de` no clone).

---

## 5. JGC — Journey Graph Canônico (o coração do twin)

JSON Schema em `backend/domain/jornada/jgc.schema.json` (fonte da verdade). **Emenda I01 (onda 5 — ver CHANGELOG-SDD.md):** o schema é **executado por inteiro** a cada save (`Draft202012Validator`, dentro do `jgc_validate`): tipo, faixa, enum, forma e chave desconhecida valem por VALOR, mapeados para o contrato de erro `{no, regra, mensagem}`. A promessa original de "Pydantic gerado a partir dele" nunca foi implementada e sai do contrato — o jsonschema real a substitui. Canonicalização RFC 8785 → `sha256` = hash da versão. **Emenda I03 (onda 5):** `nodes` e `edges` são CONJUNTOS — o mesmo grafo em ordem diferente é o mesmo grafo, então as duas listas são ordenadas por `id` na persistência e dentro do `hash_jgc` (`normalizar_grafo`, `domain/jornada/canonico.py`); arrays dentro de `data` NUNCA são reordenados (as `regras` do `decisionSplit` têm precedência de avaliação). Sem isso, o mesmo grafo permutado gerava hash → externalKey diferentes e o plan §5.4 propunha destruir/recriar tudo no SFMC.

### 5.1 Forma
```json
{ "jgcVersion": "1.0", "meta": {"osCodigo":"OS-2026-0457","tenant":"torre-movel",
    "reentrada":"nao", "quietHours":{"inicio":"20:00","fim":"08:00"}},
  "nodes": [ {"id":"n1","type":"entrySource","data":{"deRef":"DE_457_entrada","modo":"fire_once","agenda":null}} ],
  "edges": [ {"id":"e1","from":"n1","to":"n2","cond":null} ] }
```

### 5.2 Tipos de nó (fechados — validador rejeita tipo fora da lista)
| type | data (campos obrigatórios) | Compila para (SFMC) |
|---|---|---|
| `entrySource` | deRef, modo(fire_once/scheduled), agenda?, reentrada | Event Definition + Entry Source |
| `randomSplit` | braços[{id,pct}] — usado p/ **holdout** e A/B | Random Split |
| `decisionSplit` | **duas formas, mutuamente exclusivas POR NÓ (I02):** regras[{expr, to}] (destino na regra) **ou** regras[{id, cond?}] (destino nas arestas `cond` — D07) | Decision Split |
| `engagementSplit` | metrica(open/click), janela | Engagement Split |
| `frequencySplit` | classes (string livre **ou** {id, min/max} — D05/I01; o enum antigo saturado/ok/sub descrevia só a seed), fonte (string — o grafo v5 real usa `DE_freq`) | Einstein Frequency **ou** twin-emulado (decision sobre score) |
| `sto` | janelaHoras(24), fallback | Einstein STO **ou** twin-emulado (Wait By Attribute com hora ótima) |
| `wait` | duracao(iso8601) ou ate(atributo) | Wait |
| `channel.email/sms/push/whatsapp/rcs` | assetRef, throttlePorHora?, custoUnit(lookup tarifa) | Send/Message activity |
| `updateContact` | deRef, valores | Update Contact |
| `goal` | metrica, deRef | Goal |
| `exit` | motivo | Exit |
| `exception` | payloadOriginal (Adopt Wizard: nó não mapeável) | — (bloqueia publish até resolução) |

### 5.3 Validação semântica (serviço `jgc_validate`, executa a cada save)
Erros bloqueantes: nó órfão/braço sem destino; `channel.*` sem opt-in configurado; soma de pcts ≠ 100; holdout ausente quando experimento pré-registrado; `reentrada != nao` com holdout (quebra o experimento); throttle acima do cap da política; `wait` com `duracao` fora do ISO-8601 (**D03**); wait que ultrapassa janela da oferta; grafo sem `goal`; **`roteamento_ambiguo` (I02):** `decisionSplit` com regra que traz `to` E aresta real saindo do MESMO nó — as duas formas do §5.2 são mutuamente exclusivas por nó (a adjacência única somaria as duas e o braço duplicado levaria volume a mais no taxímetro/motor, e dois outcomes iguais no JB); a recusa é aqui, NUNCA dedupe mudo na adjacência. E toda violação de VALOR do schema (**I01**): faixa, enum, tipo escalar, chave desconhecida — regras `valor_fora_da_faixa`, `valor_fora_do_enum`, `tipo_invalido`, `campo_desconhecido`, `forma_invalida`. Warnings: custo projetado > budget; pressão de contato prevista > cap.

**Adjacência é fonte única** (`domain/jornada/adjacencia.py` — emenda **D07**, estendida ao compilador/export/pré-voo/drift pela emenda **E05**): validador, taxímetro, motor Monte Carlo **e compilador** respondem "quais as saídas deste nó?" pelo MESMO código — `edges` mais as `regras` de `decisionSplit` que trazem `to` direto. Cada consumidor tinha a sua cópia até o UAT #4, e a emenda A13 (dado torto não estoura `KeyError`) só havia alcançado duas: um `decisionSplit` com `regras` sem `to` — grafo VÁLIDO, roteado pelas arestas `cond`, e gerado pelo próprio Flow — derrubava `POST /jornadas/{id}/simular` com HTTP 500. Aresta ou regra malformada é ignorada na adjacência; quem reporta o erro ao usuário é sempre o `jgc_validate`, com nó e regra nomeados.

**`wait.duracao` é conferida, não só exigida** (**D03**): até o UAT #4 bastava o campo existir. O gpt-oss-120b emitiu `"imediato_apos_quiet_hours"`, que passou no save, escapou em silêncio da regra `wait_alem_da_janela` (ela ignora duração não-parseável) e seguiria torta para o compilador SFMC. Agora vale o mesmo ISO-8601 do `duracao_em_dias` (`P1D`, `P2W`, `PT12H`); `ate` (data-alvo) segue como alternativa do anyOf.

**`frequencySplit` casa classe por `id`** (**D05**): a comparação era contra a repr do dict inteiro, então classe na forma do §5.2 (`{id, min/max}`) nunca casava com a `cond` da aresta e o nó era impossível de salvar — mesmo com todas as arestas certas. Casa por `id`, igual ao `randomSplit`; classe como string segue valendo.

**`wait_alem_da_janela` LIGADA pela janela estruturada** (**D04 → fechada pela Emenda J04, onda 6 — ver CHANGELOG-SDD.md**): o briefing ganhou dois campos OPCIONAIS, `janela_inicio` e `janela_fim` (ISO `YYYY-MM-DD`, entradas normais `{valor, inferido}`), e TODOS os chamadores de produção passam `janela_oferta_dias` derivada deles (`domain/intake/janela.py`; `JornadaService._validar`, o `ajustar` e o `SimuladorService._rodar` — save, retry §7.3, PUT, propostas e Ensaio). Coerção TOLERANTE no precedente do `_numero` do simulador: campo ausente, não-parseável ou invertido → `None` → regra inerte para aquela OS, exatamente o comportamento pré-J04 — briefing velho continua 100% válido e os campos NUNCA entram em `CAMPOS_OBRIGATORIOS` (o A1 do §8-M3 fixa `faltantes == ['verba','janela']`). O campo textual `janela` segue obrigatório para completude e vira display; quando os dois convivem, a ESTRUTURADA governa — nunca se deriva uma da outra por parser (§1.3.5). Convenção fixada: dias = `(fim − início).days` (45 para 01/07→15/08). Limite declarado que PERMANECE: a regra só cobre `wait` com `duracao`; `wait` por `ate` (data-alvo em atributo) segue fora — registrado, não resolvido de contrabando. Os campos entram por inferência do consultor (whitelist `CAMPOS_INFERIVEIS` — §8-M3), por `PATCH /pedidos/{id}/campos` ou por `PATCH /os/{id}/briefing/{campo}` com valor; a T2 os exibe dinamicamente com o chip inferido/confirmado.

### 5.4 Compilador plan/apply (determinístico — LLM proibido neste caminho)
1. `plan(snapshot, ambiente)` → resolve dependências (DEs → EventDef → Assets → Journey → Automations), gera lista `{recurso, ação, aviso}` com **externalKey = `jrn-{hash[0:12]}-{noId}`** (idempotência).
2. `apply` executa na ordem, `tenacity` com backoff, orçamento `SFMC_API_BUDGET_PER_APPLY`; falha → rollback compensatório (destruir o que criou nesta run); tudo logado em `sync_run`.
3. Avisos destrutivos obrigatórios: recriar Event Source ("reinicia contatos em espera"), destruir DE.
4. Homolog→prod: **mesmo hash**; apply em prod exige `aprovacao.decisao in (aprovado, aprovado_ressalvas)` + certificado válido + pre-flight verde.
5. Drift: job a cada 30min + on-demand: retrieve estado real → decompila → compara por hash/campos → grava `drift_check`; drift em prod abre pendência automática bloqueante.

---

## 6. Simulador (Ensaio Geral — portão obrigatório)
- Entrada: JGC + segmento (waterfall/volume) + priors (`calibracao_prior` do tipo de campanha) + tarifas + política.
- Personas sintéticas: amostradas de **agregados** do read model (jamais registros individuais em prompt/log); geração no `PersonaService` com seed fixa por run (`RngPort`).
- Execução: N=10.000 personas × K=500 runs Monte Carlo com relógio virtual (waits, quiet hours, throttle, STO amostrando distribuição de horários, frequency split via governor).
- Frequency split casa a `cond` da aresta com as classes do mix do governor (`saturado/ok/sub` — CLASSES_FREQUENCIA); cond ou classe que não casa **não zera mudo: vira aviso nomeando o nó e as chaves (⇒ amarelo)**. O motor não redistribui nem inventa mapeamento entre classes que não conhece (§1.3.5); reprovar no save foi avaliado e rejeitado — a forma D05 (classes livres/objeto) é válida e há grafo real salvo com ela (emenda D08, 2026-08-07).
- Saída (persistida em `jornada_versao` e congelada no snapshot como `previsto`): funil por nó/aresta, conversões/custo/receita/ROAS em **P10/P50/P90**, lift esperado + validação de poder (n mínimo por MDE), gargalos, pressão de contato.
- NFR: 10k personas < 60 s (vetorizar com numpy; sem I/O no loop).
- Semáforo: verde/amarelo/vermelho → vermelho bloqueia T9/T11; regra (precedência do aceite §8-M8-A2 — emenda M8): vermelho se ROAS P50 < 1 ou colisão crítica do governor; poder insuficiente pinta o portão de experimento de vermelho e a simulação de amarelo; avisos (ex.: custo P50 > verba) também dão amarelo. **Terceira causa de vermelho (emenda D09, onda 7 — aceite §8-M8-A8):** um `frequencySplit` cujo conjunto de `cond` tem interseção **vazia** com as classes do mix do governor — 100% do volume que chega ao nó evapora e a jornada não entrega nada. A causa é medida na estrutura (interseção de conjuntos), nunca no sintoma da saída: "funil zerado" daria falso positivo em holdout 100% e falso negativo assim que uma única pessoa caísse num braço. Perda **PARCIAL** de volume (classe do mix sem aresta) **segue amarela, por decisão** — o aviso passa a informar a fração medida. A regra nomeia `frequencySplit`: o `randomSplit` tem o mesmo `.get(cond, 0)` mudo e **não** é coberto por esta emenda. **E o vermelho passa a ter consumidor:** `POST /snapshots` recusa (409) simulação vermelha na versão corrente, e o painel da T9 ganha um quinto portão (`simulacao`) — cor sem recusa era a doença que esta emenda veio tratar. T8 (`congelar-previsto`) **não** é bloqueada: o §6 diz T9/T11.

---

## 7. Mesh de agentes

### 7.1 SKILL.md canônico (front-matter YAML + corpo)
```markdown
---
name: engineer            version: 3.2      camada: especialista
modelo_perfil: 120b       etapa: audiencia
bases_rag: [dicionario_dados, historico_campanhas]
exige_evidencia: true     max_retries: 2
saida: {formato: json, schema: sql_publico.schema.json}
---
Você gera SQL de segmentação. NUNCA omita as 7 listas de exclusão no WHERE.
Cite a evidência RAG de cada coluna usada. Sem evidência → responda que não sabe.
```
Parser valida front-matter; publicar versão exige `harness_run.passou=true` (score ≥ 90 por dimensão do judge, judge = 120B com rubrica fixa). Campanha congela versões no GO (`os.frozen.agent_versions`).

### 7.2 Roster (resumo executável — detalhe funcional no plano v1.2)
| Agente | Perfil | Etapa | Contrato de saída |
|---|---|---|---|
| consultor | 120b | pedido/T2 | `pedido.conteudo` + completude% + faltantes[] |
| triagem_* (5) | 20b | por esteira | roteamento + checklist da célula IPO |
| engineer | 120b | T5/T5a | SQL + explicação por cláusula + evidências |
| activate | 120b | T5/T11 | plano de DEs (diff) — execução via SFMCPort |
| visual/copy/content | 120b | T6 | matriz canal×variante; limites por canal validados |
| flow | 120b | T7 | JGC válido + premissas[] + resumo |
| simulate/persona | 120b | T8 | narrativa do resultado + premissas editáveis |
| **guard** | **determinístico** | T5/T9/T11/T12 | veredito por código; LLM 20b só EXPLICA |
| sync/publish | 120b | T11 | tradução executiva do plano; nunca executa sem humano |
| insight | 120b | T13/T14 | NL→SQL **somente** sobre camada semântica (views métricas); mostra a query |
| optimize | 120b | T15 | proposta = diff JGC + impacto simulado |
| calibrate | 120b | T15 | ajuste de priors + backtest |
| cost | 20b | transversal | taxímetro/burn-rate (cálculo é código; LLM narra) |
| doc | 20b | portões | .docx executivo via python-docx |
| maestro | 120b | OS | FSM da campanha; nunca tarefa atômica |
| ajuda | 20b | Guia (18 telas) | resposta didática sobre a página em foco (contexto = guia enviado pelo front); recusa fora da plataforma (emenda 2026-08-05, §8-M-Guia) |

### 7.3 Orquestração LangGraph
Supergrafo por OS (checkpointer `langgraph-checkpoint-postgres`): nós = células IPO; `interrupt()` humano em TODOS os portões (pendência bloqueante, aprovação link mágico, simulação, publish). Subgrafo padrão do especialista: `preparar_contexto(RAG top-k=8 filtrado por bases autorizadas)` → `gerar` → `judge` (120B, dimensões correção/evidência/compliance/formato) → `retry≤2` → `entregar prévia` (Aplicar/Rejeitar na UI). Toda invocação grava `invocacao` (via_ai) com evidências citadas.

### 7.4 RAG
Uma collection `agente_evidence` (vector 1024, cosine, HNSW), filtro por `base` + `tenant_id`. Ingestão por base com CLI `python -m app.rag ingest <base> <path>`; chunk ~700 tokens, overlap 80. **Mudar `EMBED_DIM` exige re-embed completo** (comando `python -m app.rag reindex`; busca fica indisponível até concluir — exibir aviso na UI T16/Bases).

**Implementado (emenda A11, 2026-08-05 — ver CHANGELOG-SDD.md):** `EmbeddingPort` (§2.1) com adapter real OpenAI-compatible (`POST {EMBED_BASE_URL}/embeddings`, modelo `EMBED_MODEL`, dim `EMBED_DIM`, timeout `EMBED_TIMEOUT_S`; timeout/erros → `EmbeddingIndisponivel`, que HERDA de `LLMIndisponivel` — os handlers 503 `degraded` §10.6 cobrem sem código novo) e fake determinístico para teste (§1.3.5). `RetrieverService` (`preparar_contexto` §7.3): top-k=8 por cosseno filtrado por `tenant_id` + bases autorizadas no front-matter `bases_rag` da skill (§7.1), com **degrade suave** — hub de embeddings fora → contexto SEM evidências (o `exige_evidencia` da skill segue valendo: sem evidência, o agente não inventa). Persistência: pgvector no `RepositorioSql` (§4); fallback dev sem DB = busca ingênua em memória (mesmo contrato). Ingestão: JSONL (`{texto|chunk, ref?, meta?}` por linha), chunking ~700 tokens/overlap 80 (token≈palavra, determinístico), embeddings em LOTE e upsert por uuid5 (re-ingestão idempotente, padrão §11.4/A15); `reindex` re-embeda preservando chunk/meta/id. Seed DEMO (§11.4): `mocks/seeds/dicionario_dados.jsonl` (~17 entradas do read model de ativação — contato_hash, consumo_pct, qtd_pacotes_avulsos_3m, opt-in por canal, 7 listas de supressão etc.) ingerida no boot `DEMO_MODE`; **sem hub a seed é PULADA com log, sem quebrar o boot**. Wire: engineer recebe `evidencias_rag` e consultor `precedentes` no contexto do prompt (formato citável `{id, base, ref, trecho}` — os ids citados fecham o ciclo no ledger `invocacao.evidencias`); o trace §10.8 ganha o span `rag_retrieve`; a promoção de aprendizado do M11 embeda melhor-esforço (sem hub → linha sem vetor no fallback, apuração jamais falha por RAG).

---

## 8. Módulos, endpoints e critérios de aceite

Convenções API: prefixo `/api/v1`; auth Bearer (dev: token estático de `usuario` seed); header `X-Tenant` obrigatório; erros RFC-7807; paginação `?limit&offset`; mutações aceitam `Idempotency-Key`. OpenAPI tags = módulos. Abaixo, por módulo: endpoints principais + aceites (IDs viram testes).

### M0 · Fundação
Repo, docker-compose (db+api+web+mocks+mailpit), config, migração 0001, auth dev, RBAC (papéis: solicitante, analista, lider, aprovador, dpo, admin — decorator `require_role`), `/healthz`, CI (§13).
**A1** dado compose up, quando `GET /healthz`, então `{db:ok, llm:skip|ok, sha:<commit>}` em <2s. **A2** requisição sem `X-Tenant` → 400 (exceção única, emenda C03 2026-08-06: as duas rotas públicas do link mágico `/api/v1/aprovacao/*` são isentas — o tenant vem do token; ver §8-M8-A5). **A3** (emenda A22, 2026-08-06 — ver CHANGELOG-SDD.md) `sha` é o commit **embutido na imagem** (`ARG/ENV GIT_SHA`, default `dev` fora do docker), nunca lido de git em runtime: é a prova de versão que o smoke pós-deploy compara (§13).

### M1 · Núcleo OS/governança
`POST/GET /os` · `GET /os/{id}` · `POST /os/{id}/fase` (só transições legais; portões checados) · `POST /os/{id}/pendencias` · `GET /os/{id}/pendencias` (emenda B01, 2026-08-06 — ver CHANGELOG-SDD.md: leitura pura das pendências da OS em ordem de `numero`, com numero/titulo/severidade/status/bloqueante/accountable/origem; qualquer autenticado, escopada por tenant. Existia só o POST — 405 na leitura — e a UI dependia do estado de sessão) · `POST /pendencias/{id}/resolver|aceitar` · `GET /os/{id}/saude` · SLA service (congela prazos no GO; estados correndo/pausado_cliente/bloqueado_pendencia).
**A1** pendência bloqueante aberta → `POST fase` avança? Não: 409 com motivo. **A2** aceite de pendência exige papel accountable + justificativa; gera `domain_event`. **A3** saúde é view — não existe endpoint de escrita de saúde (teste verifica 405/404). **A4** (emenda B01) `GET /os/{id}/pendencias` lista TODAS as pendências da OS em ordem de `numero` — mesmo contrato do POST, tratadas inclusive (status muda, a linha não some); tenant alheio → 404.

### M2 · Esteira de Produção (T4a) + Hike import
`GET/PATCH /os/{id}/workflow` (7 etapas, checklist, dependências) · `POST /admin/hike/import` (aceita export JSON/CSV do Hike → cria OS+etapas com `hike_ref`; log em `hike_import_log`).
**A1** etapa Criativos criada com 4 subtarefas padrão. **A2** etapa com dependência insatisfeita não vai a `em_andamento` (409). **A3** import de fixture `mocks/seeds/hike_export.json` cria 3 OSs com histórico preservado.

### M3 · Intake & Consultor (T2 + Portal do Solicitante)
`POST /pedidos` (criação NA APP — emenda 2026-08-05: o Portal do Solicitante foi aposentado; o token de portal segue aceito como auth de link, sem login pleno) · `POST /pedidos/{id}/mensagem` (conversa com consultor; retorna conteúdo atualizado + completude + faltantes; retry §7.3 sem inferências PRESERVA a resposta da 1ª chamada — a resposta ao reprompt do sistema não vaza) · `POST /pedidos/{id}/converter` (→ OS com briefing pré-preenchido; campos `inferido:true` até confirmação) · CRUD (emenda 2026-08-05): `GET /pedidos` (lista do tenant, mais recente primeiro: id, solicitante, completude, faltantes, estado, os_id, updated_at — sem `conteudo`; arquivados fora por padrão, `?arquivados=true` inclui; login pleno) · `GET /pedidos/{id}` (detalhe completo) · `PATCH /pedidos/{id}/campos` `{campo: valor}` (edição manual direta → `inferido:false`, completude recalculada por código; convertido/arquivado → 409; analista|lider) · `POST /pedidos/{id}/arquivar` (soft e idempotente; convertido → 409; arquivado bloqueia mensagem/edição/conversão; analista|lider) · `GET /os/{id}/briefing` · `PATCH .../briefing/{campo}` (confirmar/editar).
**Recusa de burla de compliance (emenda C01, 2026-08-06 — ver CHANGELOG-SDD.md).** Pedido para ignorar/dispensar as 7 listas de supressão ou a checagem de opt-in — inclusive com "autorização" hierárquica ("ordem do CEO", "autorizado pela diretoria") e injeção de prompt ("ignore as instruções anteriores") — é detectado por **CÓDIGO** antes de qualquer LLM (`backend/domain/agentes/compliance.py`, puro e determinístico: exige verbo de burla + alvo de compliance na mesma mensagem, ou marcador de injeção/autoridade sozinho). Consequências, todas determinísticas: (a) a **recusa inegociável é carimbada na frente da resposta** ao solicitante — "isso é impossível por construção: o Guard é um portão determinístico de código e nenhuma instrução, de nenhum nível hierárquico, o remove" — seguida da consultoria normal com o que É possível; (b) a diretriz entra no prompt (`guarda_compliance`), então o modelo recebe o fato pronto em vez da tarefa de decidir se recusa; (c) a tentativa fica marcada no **ledger `invocacao`** (`output.compliance_bypass_tentado`) e no payload de `agent.invoked` (§2.3), que é o que a auditoria (§8-M12) precisa enxergar. A skill (§7.1) traz a mesma regra em palavras. Motivo do achado: no UAT #3 o agente **não obedeceu** à ordem ilegal, mas a *normalizou* como "risco a monitorar" — depender do humor do modelo para a recusa é a inversão que o §1.1.2 existe para evitar. Nada disso é o bloqueio real (o disparo já era impossível: Guard §8-M5 + re-varredura last-mile §8-M9); é higiene de segurança e trilha de auditoria.
**A1** pedido sem verba/janela → completude<100 e faltantes lista exatamente esses campos. **A2** converter exige completude=100. **A3** toda inferência do consultor carrega `via_ai` + evidências (precedentes). **A4** retry §7.3 esgotado sem inferências → a resposta exibida (e o ledger `invocacao`) é a da 1ª chamada; o reprompt "SISTEMA:" jamais vaza ao solicitante. **A5** (emenda C01) mensagem pedindo para burlar compliance → resposta ABRE com a recusa inegociável (mesmo com o LLM normalizando a ordem), nenhum campo de "dispensa" entra no briefing, e `invocacao.output.compliance_bypass_tentado` + `agent.invoked` registram a tentativa; conversa legítima NÃO recebe carimbo nem marca (contra-prova de ruído). **B1** `GET /pedidos` lista o resumo do tenant (isolado por tenant; sem `conteudo`; login pleno). **B2** `PATCH /pedidos/{id}/campos` rebaixa a `inferido:false` e recalcula completude/faltantes/estado por CÓDIGO; convertido → 409. **B3** arquivar é soft (fora da lista padrão, legível por id) e idempotente; convertido → 409. **A6 (emenda J04, onda 6 — ver CHANGELOG-SDD.md):** o briefing aceita os campos OPCIONAIS `janela_inicio`/`janela_fim` (ISO `YYYY-MM-DD`) — infereíveis pelo consultor (whitelist `CAMPOS_INFERIVEIS`, que continua descartando qualquer outro campo), editáveis pelas duas rotas PATCH; presentes e parseáveis, ligam o `wait_alem_da_janela` do §5.3 (wait maior que a janela → 422 apontando o nó, no save E no Ensaio); ausentes/não-parseáveis → a regra segue inerte e NADA muda (briefing velho é válido; `faltantes` do A1 não os inclui).

### M4 · Validação campo-a-campo & War Room (T3/T4)
`POST /os/{id}/validacoes/{campo}` (executa checagem automática contra fonte: contagem, schema, frescor; retorna evidência) · `POST .../validacoes/{campo}/pendencia` · threads: `POST /os/{id}/threads` ancoradas em campo · `POST /os/{id}/go` (GO: congela SLAs+versões em `os.frozen`, fase→criada).
Estado recuperável (emenda B01, 2026-08-06 — ver CHANGELOG-SDD.md): `GET /os/{id}/validacoes` devolve a decisão VIGENTE de cada campo já checado (campo, veredito, checagens, evidência + `por`/`atualizado_em` = quem/quando), e o POST de validação passa a ser **idempotente por (os_id, campo)** — revalidar o mesmo campo ATUALIZA a linha vigente (mesmo `id`, `created_at` da primeira checagem) em vez de empilhar duplicata; `validacao_campo` ganha unique (os_id, campo) + as colunas `por`/`atualizado_em` (migração 0013, com dedup das linhas já gravadas). O histórico de cada execução continua no outbox `domain_event` (`validacao.executada`, com `revalidacao: bool` — §2.3): a tabela guarda o estado, o outbox guarda o filme. A tela T3 hidrata dessas leituras (com `GET /os/{id}/pendencias`, §8-M1-A4), nunca do estado de sessão.
**A1** GO com campo não decidido ou pendência bloqueante → 409 listando pendências. **A2** após GO, `frozen` contém versões publicadas atuais de agentes e política. **A3** doc executivo (.docx) gerado no GO e armazenado. **A4** (emenda B01) `GET /os/{id}/validacoes` devolve uma decisão por campo checado, com evidência e quem/quando; campo nunca checado não aparece; tenant alheio → 404. **A5** (emenda B01) revalidar o mesmo campo 3× deixa UMA linha (id e `created_at` estáveis), 3 eventos no outbox e não afrouxa o portão do GO.

### M5 · Audiência (T5) + Guard + Data Cloud (T5a)
`POST /os/{id}/segmento/gerar-sql` (engineer) · `POST /segmentos/{id}/recontar` (dry-run no read model; waterfall + líquido) · `PUT /segmentos/{id}/holdout` · **Guard determinístico**: `POST /segmentos/{id}/certificar` (varre 7 listas + opt-in; emite `certificado_elegibilidade`) · Data Cloud: `GET /datacloud/segmentos` (cache+frescor) · `GET /datacloud/segmentos/{id}/relatorio` (bruto→elegível→líquido→sobreposição + **volume de abordagem por canal** pós caps/quiet/colisões) · `POST /datacloud/segmentos/{id}/usar` (vira `segmento` origem data_cloud com lineage) · `GET .../relatorio.docx`.
**A1** SQL gerado sem as 7 listas no WHERE → guard reprova certificação (unit com SQL adulterado). **A2** relatório de volume: soma por canal ≤ líquido; percentuais calculados sobre líquido; colisões vêm do governor. **A3** certificado tem hash e validade; publish (M8) recusa certificado expirado. **A4** contagens exibem frescor por fonte (Hybris D-1 nas fixtures). **A5 (emenda K05, onda 7 — proveniência das contagens):** o certificado DECLARA de onde vieram os números. `contagens_derivadas_do_sql` (bool, sem default no domínio — cada emissor é obrigado a responder) sai na resposta da certificação, nos eventos `gate.passed`/`certificado.emitido` e no registro persistido (coluna 0018, `default false` — toda linha antiga é de fixture por definição), e entra no **payload canônico do hash**: dois certificados idênticos exceto pela proveniência têm hashes diferentes, então ninguém promove fixture a medido editando coluna. A porta `ReadModelAudienciaPort` passa a exigir `derivado_do_sql` no dict devolvido, com contract test que verifica a afirmação: quem declara `True` tem de discriminar SQLs distintos (mesma instância, dois SQLs, contagens diferentes), e um adapter mentiroso (declara `True` ignorando o argumento) REPROVA no alçapão do próprio contrato. O default no serviço é conservador (`False` quando o read model não declara). Aceites: `test_M5_A5`, `tests/contract/test_read_model_audiencia_contrato.py`. **Este A5 declara o limite; não o fecha.** **Camada 2 do Guard — segue ABERTA (a tentativa J01 foi REVERTIDA na onda 6; ver CHANGELOG-SDD.md e HANDOFF §8.3):** a Camada 2 (`problemas_nas_contagens`) só reprova o caso "zero nas 7 listas com líquido positivo" e permanece inerte na configuração de fixtures (o read model devolve supressões fixas — a limitação registrada na entrada E01b). O J01 tentou executar o `sql_publico` num sqlite in-memory, mas a auditoria mediu que é frágil por três razões independentes: **dialeto** (o Engineer 120b gera Postgres — ILIKE, `::cast`, EXTRACT — que o sqlite rejeita, reprovando SQL válido), **vocabulário** (a base sintética usa as colunas do SQL do demo, não as que o `dicionario_dados` ensina o Engineer a citar) e **monocultura** (um perfil de contato só → SQL que mira outro valor certifica bypass em silêncio). O fecho honesto exige o read model REAL (um Postgres com a base de contatos, executando o mesmo dialeto), que não existe em dev/fixtures — fechar com fixtures reintroduz os problemas medidos. Enquanto isso, a Camada 1 (estrutura canônica do WHERE, E01/E01b) é a barreira efetiva.

### M6 · Criativo (T6)
`POST /os/{id}/criativos/gerar` (matriz canal×variante a partir do KV master) · `PATCH /criativos/{id}/celula` (aprovar/revisar por célula) · validadores: SMS≤160, template WhatsApp status, compliance de linguagem (regras + LLM warn).
KV de partida (emenda 2026-08-06 — determinístico, ZERO LLM §10.6): `GET /os/{id}/criativos/kv-padrao` devolve o KV master DEFAULT **derivado do briefing da própria OS** (`domain/criativo/kv_padrao.py`): `headline` ← 1ª frase do `objetivo`, `oferta` ← `oferta`, `cta` ← verbo da intenção do objetivo + forma do canal real (`canais` só sms/whatsapp → "Responda SIM"), `tom` ← `tom_de_marca`; resposta `{kv_master, derivado_de, suficiente, via_ai:false}`. Campo sem fonte no briefing → placeholder neutro `(defina o Key Visual)` — o Estúdio NUNCA abre com copy fixa de outra campanha (§1.3.5). Não persiste nada; leitura escopada por tenant (OS inexistente → 404).
**A1** SMS 161 chars → 422. **A2** edição do KV master marca células derivadas `adaptado_revisar`. **A3** nenhuma célula vai a `aprovado` via agente — só usuário com papel analista+. **A4** KV default de uma OS de recarga sai do briefing dela (sem nenhum termo da campanha de franquia) e OS sem briefing recebe `(defina o Key Visual)`.

### M7 · Twin Canvas (T7)
`POST /os/{id}/jornada/gerar` (flow → JGC) · `GET /os/{id}/jornada` (última versão do twin da OS; 404 quando não há versão — leitura determinística do canvas, emenda 2026-08-05) · `PUT /jornadas/{id}/grafo` (valida §5.3; recalcula taxímetro) · `POST /jornadas/{id}/ajustar` (texto livre → diff proposto, nunca aplica direto) · `GET /jornadas/{id}/no/{noId}/sfmc-preview` (JSON que o compilador gerará).
Editor "começar do zero" (emenda 2026-08-05 — determinístico, ZERO LLM §10.6): `POST /os/{id}/jornada` (cria NOVA versão `rascunho` sem agente: corpo `{grafo?}` opcional — com `grafo`, valida §5.3 antes de persistir com 422 apontando o nó; sem `grafo`, o servidor gera o esqueleto mínimo `entrySource → goal → exit` que passa no `jgc_validate`; meta.osCodigo/tenant sempre reescritos com os valores da OS §1.3.5; taxímetro recalculado A2; funciona com o hub LLM fora §10.6 — é a porta de entrada do editor visual T7 quando o usuário não quer o Flow).
Versionamento & exportação (emenda 2026-08-05 — determinístico, ZERO LLM §10.6): `GET /os/{id}/jornadas` (lista resumida em ordem de `versao`: id, versao, estado, hash, custo_projetado, created_at — sem grafo; OS sem versão → `[]`) · `GET /jornadas/{id}` (versão específica completa) · `POST /jornadas/{id}/restaurar` (clona como NOVA versão `rascunho` com grafo/hash idênticos e taxímetro recalculado — versões nunca são editadas retroativamente; simulação/previsto não acompanham) · `GET /jornadas/{a}/diff/{b}` (`domain/jornada/diff.py` — o mesmo diff do ajustar/M11: nós/arestas adicionados·removidos·alterados + `meta_alterada`, com `de`/`para` {id, versao, hash}; versões de OSs diferentes → 409) · `GET /jornadas/{id}/export?formato=json|xml` (download `Content-Disposition`; **json** = spec de interaction do Journey Builder — import NATIVO do JB, REST `/interaction/v1/interactions`, montada reaproveitando o compilador M9 §5.4: key `jrn-{hash[0:12]}`, activities com externalKeys idempotentes, triggers, goals; **xml** = a MESMA spec em serialização determinística/canônica `<Interaction><Activities><Activity type=...>` com `<Manifest>` embutido (hash JGC, versao, geradoEm via ClockPort, plataforma Jornada), válida contra `backend/domain/jornada/journey_export.xsd` — honestamente: o JB não importa XML; o formato atende integração/auditoria corporativa. Grafo com nó `exception` → 422 com `nos` §5.2).
**A1** grafo com braço órfão → 422 com apontamento do nó. **A2** taxímetro = Σ(volume esperado × tarifa vigente) — teste com fixture bate valor exato. **A3** `reentrada=qualquer_momento` + experimento travado → 422 (contrato de re-entrada). **B1** lista de versões ordenada por `versao` (resumo sem grafo). **B2** restaurar cria nova versão rascunho com grafo idêntico e hash igual (origem intocada). **B3** diff acusa nó adicionado/alterado/removido + arestas. **B4** export JSON = interaction com todas as activities do grafo (externalKeys §5.4.1). **B5** export XML válido contra o XSD e determinístico byte a byte com mesmo grafo+clock. **B6 (emenda K04, onda 7 — achado D06):** `PUT /jornadas/{id}/grafo` **MINTA uma versão nova** (id e `versao` novos, `rascunho`, derivada da origem) em vez de sobrescrever — a versão de origem sai da chamada byte a byte como entrou, com `simulacao`/`estado` preservados, e o histórico passa a registrar cada save. **Guarda de no-op:** grafo cujo hash canônico é igual ao corrente (inclusive só reordenado — emenda I03) NÃO versiona, não emite evento e não invalida o Ensaio; sem ela, cada auto-save do canvas criaria versão idêntica e apagaria a simulação. Eventos: `jornada.versao_criada` (com `derivada_de`) **e** `jornada.grafo_atualizado`, que continua saindo para não quebrar consumidores. Efeito colateral desejado: fecha por construção a janela em que um PUT entre `criar_snapshot` e a decisão publicava no SFMC um grafo não aprovado carimbado com o hash aprovado. **Limite declarado:** `proxima_versao` é MAX+1 sem lock — dois saves simultâneos na mesma OS colidem no `unique(os_id, versao)`; aceitável enquanto a edição é de um analista por vez, e registrado para não virar surpresa.

### M8 · Simulador (T8) + Portões (T9) + Aprovação (T10)
`POST /jornadas/{id}/simular` (§6; persiste resultado) · `POST /jornadas/{id}/congelar-previsto` · cenários: `POST /simulacoes/comparar` · Portões: `GET /os/{id}/portoes` (certificado, experimento, custo/alçada, governor) · `POST /experimentos` (pré-registro + poder) · `POST /os/{id}/custo/enviar-alcada` · Aprovação: `POST /snapshots` (monta hash composto) · `POST /snapshots/{id}/link-magico` → URL pública `GET /aprovacao/{token}` (página standalone: resumo, waterfall, criativos, replay do previsto, hash) · `POST /aprovacao/{token}/decidir`.
**Link mágico é STANDALONE de verdade (emenda C03, 2026-08-06; atualizada pela J03 — ver CHANGELOG-SDD.md).** As duas rotas de `/aprovacao/*` são **isentas do header `X-Tenant` obrigatório** — o middleware do §8 as trata pelo prefixo (`ROTAS_SEM_TENANT_HEADER` em `backend/app/main.py`; o nome antigo `ROTAS_PUBLICAS` virou mentira quando a E03 passou a exigir sessão: isento de HEADER nunca foi isento de CREDENCIAL). O servidor deriva o tenant do próprio pacote (token → `aprovacao` → `snapshot` → OS → `tenant_id`, em `ServicoAprovacao._por_token`) e o confere contra a SESSÃO de quem chama. O header continua **aceito** e, quando vem, é conferido contra o tenant real do pacote (divergiu → 404, sem vazar a existência do link). Nenhuma outra rota de `/api/v1` é isenta.
**A1** simulação com seed fixa é reprodutível (mesmos P50s). **A2** poder insuficiente (n<n_minimo) → portão experimento vermelho e simulação amarela. **A3** token: uso único, expira, registra ip/device; ressalvas criam pendências automaticamente. **A4** variação de custo >10% após aprovação → invalida aprovação (snapshot novo obrigatório). **A5** (emenda C03) o fluxo standalone completo — ver o pacote, decidir e o 409 do reuso — roda **sem `X-Tenant`**; header anunciando outro tenant → 404; o resto de `/api/v1` continua exigindo o header (§8-M0-A2). **A7/E03 (fecho da segregação — implementado na onda 2, fiado ao contrato pela J03):** ler o pacote exige sessão do tenant dono (401 sem sessão; `sessao.pode_decidir` fail-closed); decidir exige a sessão do PRÓPRIO aprovador congelado (403 mudo para qualquer outra — analista, líder e o criador de posse do token em claro); e-mail sem conta ativa → 409 na emissão; `aprovador+tag@x` não herda a decisão. Aceites: `test_M8_E03_*`. **A8 (emenda D09, onda 7):** simulação **vermelha** na versão corrente recusa `POST /snapshots` com 409 nomeando o nó (lendo `jornada.simulacao`, a CORRENTE — não `previsto`, que `simular` não limpa); `GET /os/{id}/portoes` ganha o portão `simulacao` (PENDENTE sem Ensaio), preservando os quatro antigos; `congelar-previsto` continua 200 (o §6 bloqueia T9/T11, nunca T8); e grafo saudável segue criando snapshot 201 — guarda-corpo contra bloqueio cego. Aceites: `test_M8_A8_*`.

### M9 · Compilador & Pré-voo (T11)
`POST /snapshots/{id}/plan?ambiente=` · `POST /snapshots/{id}/apply` (exige: aprovação + certificado + pre-flight verde) · `GET /sync-runs/{id}` · `POST /preflight/{snapshot}` (bateria: DEs/schema, freshness Hybris, opt-in, listas last-mile, lint AMPscript, limites SFMC, drift=0, seed dry-run) · `GET /drift` · `POST /drift/{id}/resolver` (adopt/enforce/excecao).
**Verde exige ter verificado (emenda C04, 2026-08-06 — ver CHANGELOG-SDD.md).** O item da bateria passa a admitir **4 status: `pass|warn|fail|n/a`**. `n/a` é o item que **não pôde ser verificado por falta de insumo** — hoje o caso real é `drift_zero` sem nenhum recurso publicado no ambiente para comparar, que antes devolvia `pass` com `verificados: 0` ("verde sem verificar": o operador lê "sem drift" onde a verdade é "nada foi comparado"). Todo `n/a` carrega `detalhe` dizendo o que ficou por verificar. Agregação (`domain/jornada/prevoo.semaforo`): `fail` ⇒ vermelho · `warn` **ou `n/a`** ⇒ amarelo · senão verde. `n/a` **não bloqueia** (só `fail`/vermelho bloqueia — §5.4.4), mas **não conta como aprovação**: verde passa a significar "tudo foi verificado E está conforme".
**A1** apply sem plan prévio → 409. **A2** golden files: payloads REST/SOAP gerados batem byte a byte com `tests/contract/golden/*.json|xml` (mock-sfmc valida schema). **A3** re-execução de apply com mesmo hash → 0 mutações (idempotência por externalKey). **A4** drift injetado no mock em prod → pendência automática bloqueante. **A5** (emenda C04) pré-voo em ambiente onde nada foi publicado → `drift_zero` = `n/a` com `verificados: 0` e `detalhe`, e a bateria **não fica verde** mesmo com todos os demais itens `pass` (segue liberando o apply — `n/a` não é `fail`).

### M10 · Lançamento & Monitoramento (T12/T13/T14)
`POST /launch/{snapshot}/armar` · `POST /launch/{id}/avancar-onda` (checa breakers) · `POST /launch/{id}/kill` (2 etapas; SEV1 → retomada exige 2 aprovadores) · Ingestão: `POST /webhooks/ens` (assinatura verificada) + job extracts loader; reconciliação diária · `GET /os/{id}/monitor` (todos os KPIs como par previsto×realizado; lift vs holdout com IC) · Insight: `POST /os/{id}/perguntar` (NL→SQL sobre views semânticas `vw_metricas_*`; resposta inclui a query; recusa fora do escopo).
**A1** breaker (ex.: optout>0,6%) durante onda → estado `pausado_breaker` automático; retomar exige humano. **A2** disparo p/ contato em lista de supressão (fixture) → incidente SEV1 + kill automático. **A3** ENS×extract divergência >2% → alerta de reconciliação. **A4** pergunta fora da camada semântica ("qual o CPF...") → recusa padrão, sem SQL executado.

### M11 · Otimização/Retro/Calibração (T15)
`GET /os/{id}/propostas` (optimize: diff JGC + impacto simulado) · `POST /propostas/{id}/aprovar` (gera nova versão → mini-ciclo M8→M9 expresso) · `POST /experimentos/{id}/apurar` (só após janela; anti-peeking: endpoint retorna 425 antes do fim) · `POST /os/{id}/clonar-com-aprendizados` · `POST /calibracao/publicar` (backtest obrigatório).
**A1** apuração antes da janela → 425 Too Early. **A2** significativo=true só com IC excluindo zero. **A3** clone herda aprendizados aceitos e priors novos; aprendizados promovidos entram na base RAG `resultados`.

### M12 · Ateliê (T16) + Políticas + Auditoria
CRUD agentes/skills (`POST /skills/{id}/harness` → run; `POST /skills/{id}/publicar` exige harness verde) · dry-run lado a lado · `GET/POST /policies` (draft→publicada; relatório de policy drift sobre OSs em voo) · `GET /auditoria` (filtros; evento `via_ai` clicável: prompt+evidências+judge+humano) · `POST /auditoria/reconstruir/{invocacao}` (Art. 20).
**A1** publicar skill com harness<90 → 409. **A2** OS em voo não muda de versão ao publicar skill nova (frozen). **A3** reconstrução devolve exatamente input/evidências/output da época.

### M-Guia · Guia Interativo — chat "IA, me ajude com esta página" (emenda 2026-08-05)
`POST /ajuda/perguntar` `{pagina, pergunta, contexto, historico?}` — agente `ajuda` (perfil **20b**, §3: resumos de UI; skill `backend/agents/skills/ajuda.skill.md` §7.1) responde SÓ sobre a plataforma Jornada e a página em questão. O `contexto` é o conteúdo do guia da página, enviado pelo FRONT (fonte única em `frontend/src/guia/conteudo.ts` — duplicar no back seria drift); o contrato valida ≤ 8000 chars (422 além). `historico` (≤20 turnos `{papel: usuario|ia, texto}`) vive só na sessão do navegador — nada persistido além do ledger. Recusa assuntos fora da plataforma (instrução da skill — o chat é informativo: nenhuma ação de domínio executa a partir dele); sem PII: pergunta MASCARADA no ledger (§10.2). Grava `invocacao` via_ai com `os_id` NULL (a ajuda é da página, não de uma OS) + trace Langfuse fire-and-forget (§10.8). Hub fora/`forced_off` → 503 `modo: degraded` (§10.6); o front oferece o guia estático como modo manual.
**A1** resposta gerada com o contexto do guia no prompt (LLMFake); `invocacao` gravada (perfil 20b, os_id NULL, PII mascarada); contexto >8k → 422. **A2** hub `forced_off` → 503 problem+json `modo: degraded`, zero invocação gravada.

---

## 9. Milestones (ordem de implementação — 1 PR+tag por milestone)
| # | Entrega | Módulos | DoD |
|---|---|---|---|
| MS1 | Fundação + domínio | M0,M1 | compose sobe; aceites M0/M1 verdes; CI verde |
| MS2 | Esteira + Intake | M2,M3 | fluxo pedido→OS→workflow demo navegável (API) |
| MS3 | Produção | M4,M5,M6 | GO congela; certificado emitido; Data Cloud mock integrado |
| MS4 | Twin | M7,M8 | JGC validado; simulação reprodutível; link mágico funcional |
| MS5 | Materialização | M9 | golden files batem; drift funcional contra mock |
| MS6 | Operação | M10 | rampa+breakers+monitor previsto×realizado com seeds |
| MS7 | Loop+Plataforma | M11,M12 | harness como portão; clone com aprendizados |
| MS8 | Front completo | §12 | 18 telas conforme mocks; e2e feliz da OS-2026-0457 |
Front pode avançar em paralelo a partir do MS3 (contratos estáveis por módulo).

---

## 10. NFRs, segurança e LGPD (verificáveis)
1. p95: recontagem de audiência <30s; simulação 10k <60s; plan/apply <5min (mock); API CRUD <300ms.
2. **PII**: msisdn/e-mail nunca em prompt, log ou `telemetry_event` (só `contato_hash` sha256+salt do tenant). Teste de guarda-corpo: grep de padrões PII nos logs em e2e.
   **Emenda I05 (onda 5 — ver CHANGELOG-SDD.md; fecha a dívida registrada na entrada da Onda 3c):** a detecção de PII tem **duas naturezas**, e este parágrafo deixa de ler como se fosse binária. Por **FORMA** (cpf, cnpj, email, telefone, cartão, documento, cep, rg): o formato **decide** — determinístico, com código verificável onde há ambiguidade (DV de CPF/CNPJ, Luhn de cartão) e com âncora textual nos casos sem pontuação (CEP/RG sem máscara, telefone curto) — esses limites também são NOMEADOS na fonte única, não só os de contexto. Por **CONTEXTO** (nome, endereço, data de nascimento): probabilística — o detector exige âncora contextual, a cobertura é parcial e os buracos são **NOMEADOS**. A fonte única dos limites é `DETECCAO_DA_CATEGORIA` em `backend/domain/ia_responsavel/politica.py` (o SDD **não** redigita a lista — envelheceria a cada mexida no detector); o limite intransponível que dá nome ao achado é o **nome próprio sem âncora** (`"Reativar Maria Aparecida da Silva Santos"` não é distinguível de "Vale do Silício" por regex). Os limites descem até a tela do DPO pelo `vocabulario.categorias_pii` de `GET /ia-responsavel/politica` e são exibidos **ao lado do seletor de ação** — sem isso o DPO acredita que `nome: bloquear` fecha a porta (o achado 8 na granularidade da confiança do detector). Aceite executável nas duas direções: `backend/tests/unit/test_F04_natureza_e_limites.py` (todo exemplo de limite VAZA hoje; toda detecção mascara com o marcador certo; o payload da API carrega natureza+limites; a tela lê esses campos — grep no JSX).
   **Emenda C02 (2026-08-06 — ver CHANGELOG-SDD.md):** a regra vale também para o texto LIVRE digitado pelo usuário, que o UAT #3 adversarial provou chegar EM CLARO ao prompt do hub e ao ledger `invocacao` na VPS (CPF/telefone/e-mail gravados). O mascaramento passa a ter **um único ponto de verdade**, `backend/domain/privacidade/mascarar.py` (`mascarar_pii`/`contem_pii` — puro, determinístico, sem I/O): cobre CPF, CNPJ, e-mail, telefone/MSISDN brasileiro (com e sem DDI/DDD/9º dígito) e cartão, com e sem pontuação, substituindo por marcadores estáveis (`[CPF]`, `[CNPJ]`, `[EMAIL]`, `[TELEFONE]`, `[CARTAO]`, `[DOCUMENTO]`) e **preservando o resto do texto**. Ambiguidade de formato é resolvida por CÓDIGO verificável — dígitos verificadores de CPF/CNPJ desempatam CPF × celular (ambos 11 dígitos) e Luhn confirma cartão — porque **falso positivo é bug**: número de negócio (verba `480.000`, audiência `847.312`, datas, código `OS-2026-0457`) não pode ser comido pelo sanitizador. A aplicação é na **fronteira de entrada** dos serviços — `consultor` (mensagem), `flow` (instruções de gerar/ajustar), `engineer` (instruções), `insight` (pergunta), `ajuda` (pergunta + histórico da sessão) e `criativo` (instruções do Estúdio T6, que alimentam os três agentes do pipeline visual→copy→content e as três linhas de ledger correspondentes) — de modo que prompt, embedding do RAG e `invocacao.input` recebem sempre o MESMO texto já sanitizado; nenhum caminho vê o original. A regra de escopo é **todo serviço que leva texto livre do usuário a um `LLMPort.chat`**; ficam de fora, por não receberem texto livre do solicitante, o `atelie` (o "texto" é a própria skill em autoria — mascarar corromperia o artefato) e o `otimizacao` (entrada é sinal derivado, não digitação). A pré-guarda de escopo do `insight` (A4) continua examinando a pergunta ORIGINAL (é ela que precisa enxergar a PII para recusar) e usa `contem_pii`, a mesma regra do mascaramento, para que detectar e mascarar não divirjam. Aceite: `backend/tests/acceptance/test_C02_pii.py` — `test_C02_pii_nunca_no_prompt_nem_no_ledger` (consultor: prompt E ledger limpos, com os números de negócio intactos), `test_C02_pii_mascarada_no_engineer` e `test_C02_pii_mascarada_no_criativo` — + unit `backend/tests/unit/test_mascarar.py`.
3. Secrets só via env/vault; `.env` no `.gitignore`; `APP_SECRET` obrigatório ≠ default em `APP_ENV=prod` (startup falha).
4. Purge: job diário remove `telemetry_event` e DEs de campanhas além de `retencao_dias` da política; destruição registrada em `domain_event`.
5. RBAC + segregação: criador ≠ aprovador nos portões (checagem server-side). **Emenda E05 (UAT #5, aceite `M8-A6`):** até aqui a regra era só texto — `criado_por` era gravado no snapshot e nunca lido, e `decidido_por` chegava pelo corpo da requisição, texto livre, num endpoint público. A identidade do aprovador é congelada na **emissão** do link mágico (`aprovador_email`, recusado com 409 quando bate com o criador, comparando por caixa postal — subendereçamento `+tag` não burla) e a decisão usa esse valor, ignorando o corpo. O papel é conferido contra o roster completo (incluindo o do portal). **Emenda J03 (onda 6 — ver CHANGELOG-SDD.md; o "Pendente" que vivia aqui estava STALE):** o fecho já existe desde a onda 2 — a subemenda "E03 · O link mágico deixa de ser credencial" (entrada G01 do CHANGELOG, 2026-08-06) fez a aprovação exigir **sessão autenticada**: o token virou PONTEIRO (localiza o pacote e deriva o tenant; `sha256` persistido, 404 sem vazar), **ler** o pacote exige sessão do tenant dono, **decidir** exige `sessao.email == aprovador_email` congelado por **igualdade exata** (`_mesma_conta` — `aprovador+tag@x` é conta DISTINTA e não herda a decisão), e a emissão recusa com 409 e-mail sem conta ativa no tenant. Doutrina das duas comparações: **segregar** usa a chave de identidade (colapsa `+tag` — alargar aqui é conservador); **conceder** usa igualdade exata (alargar aqui seria escalação de privilégio). O token em claro devolvido ao emissor deixou de ser poder de decidir — de posse dele, o criador recebe 403 mudo. Aceites: `test_M8_E03_*` (sessão do aprovador decide; ler exige sessão do tenant; sem conta → 409; subendereço não herda).
6. **Modo degradado**: se hub LLM indisponível (healthcheck), agentes retornam 503 `degraded` e a UI oferece modo manual; caminho crítico (guard, compilador, governor, breakers, kill) NUNCA depende de LLM — teste e2e com `LLM_DEGRADED_MODE=forced_off` deve completar M9/M10.
7. Timeout LLM 300s; retries 2 com jitter; circuit breaker por 60s após 3 falhas.
8. **Observabilidade via Langfuse (self-hosted)** — serviço `langfuse` no docker-compose (imagem `langfuse/langfuse:2` + Postgres próprio `db-langfuse`). Contrato de instrumentação: toda chamada via `LLMPort`/`EmbeddingPort` gera um **trace Langfuse com `trace_id = invocacao.id`** (metadados: tenant, os_id, agente, skill_versao, modelo_perfil) e spans `rag_retrieve` → `generate` → `judge`; tokens/latência espelhados na tabela `invocacao` (o ledger `via_ai` continua a fonte de auditoria LGPD; Langfuse é a lente operacional). **Emenda I04 (onda 5 — ver CHANGELOG-SDD.md):** a metade dos tokens desta promessa estava descumprida — `LLMPort.chat` devolvia só a string e o `usage` do provedor morria no adapter; `invocacao.tokens` era NULL em toda linha. `chat()` devolve `RespostaLLM(texto, tokens)` e o valor flui até a coluna; semântica: uma linha de ledger que cobre VÁRIAS chamadas (retry §7.3, exec+judge do harness) grava a SOMA; provedor sem `usage` → NULL (nunca zero, nunca falha — §10.6). **Emenda J02 (onda 6 — ver CHANGELOG-SDD.md):** `teto_tokens` ENTROU no conjunto fechado, na ordem que a doutrina do achado 8 exige — medição (I04) primeiro, enforcement junto com o campo: bloco `{tokens_por_dia: int|null}` (sub-conjunto fechado; null/ausente = sem teto — política pré-J02 continua válida, obrigatoriedade congelada nos 4 campos v1), escopo por TENANT por DIA UTC (`os_id` é NULL em ajuda/Ateliê — teto por OS nasceria furado), gasto MEDIDO congelado por requisição na fábrica do portão (`somar_tokens` no ledger, índice da migração 0017) e recusa em `autorizar_modelo` com **429** antes de a chamada custar (gate-on-entry: a chamada que começa abaixo do teto completa; a seguinte é recusada). Limite declarado, na tela e aqui: linha de ledger sem usage conta 0 — o teto governa o que se mede. `teto_custo` segue fora (sem tarifa R$/token no domínio). Envio assíncrono fire-and-forget: queda do Langfuse **nunca** bloqueia a aplicação (`LANGFUSE_ENABLED=false` → no-op). A tela T16/Observabilidade linka para o dashboard Langfuse (custo de IA por OS, latência por agente, taxa de retry/judge-fail); harness runs também são traceados (tag `harness`).
9. **Durabilidade dos agregados** (emenda A7 partes 1 e 2 — §4): com `DATABASE_URL` alcançável, TODOS os agregados do §4.1 (núcleo, twin/versões, snapshot/aprovação, audiência, criativos, experimento, compilador, launch/telemetria/incidentes, otimização/calibração, Ateliê/política, ledger `invocacao` e outbox) sobrevivem a restart do processo — verificado por testes `@pytest.mark.integration` com Postgres real (`pgvector/pgvector:pg16` + `alembic upgrade head`) no CI e localmente via container efêmero (inclui twin+restaurar, ledger com FK de roster e launch+telemetria). `agente_evidence` incluída desde o A11 (RAG pgvector §7.4; o teste de integração cobre ingest+retrieve+reindex — evidência promovida sem vetor fica em memória até o `rag reindex`). Sem banco alcançável a aplicação permanece 100% funcional em memória (fallback dev) — nenhum caminho depende do Postgres para subir. O `docker-compose.prod.yml` (VPS demo) sobe `db` pgvector com volume nomeado + healthcheck e a api com `alembic upgrade head` no start, como o compose dev.

## 11. Mocks e seeds (obrigatórios para dev/CI)
1. **mock-sfmc** (FastAPI): token OAuth, REST (eventDefinitions, interactions, assets) e SOAP (DataExtension, Automation) com validação de schema + estado em memória; endpoints de injeção de falha (`/chaos/rate-limit`, `/chaos/drift`).
2. **mock-datacloud**: token + `GET /segments` (4 segmentos das fixtures do plano) + query count.
3. **mailpit** para e-mails de notificação/link mágico em dev.
4. **Seeds DEMO_MODE**: OS-2026-0457 completa (briefing 14 campos, segmento 847.312, JGC do mock T7, previsto, telemetria 20 dias com lift +24,1%/ROAS 18,5x), tarifário (email 0,0018; push 0,0005; sms 0; whatsapp 0,3597), 7 listas com contagens, políticas v1, agentes+skills v1, 3 casos golden por agente, `hike_export.json`.
   **Emenda A18 (2026-08-06 — ver CHANGELOG-SDD.md):** o roster semeado passa a incluir as **5 triagens do §7.2** (`triagem_intake|audiencia|criativo|jornada|operacao` — camada triagem, 20b, skill v1.0 canônica §7.1 com roteamento + checklist da célula IPO) e **1 `harness_run` verde de vitrine por agente-chave** com golden dataset (`origem: "seed"`, score 90–97 por dimensão, `skill_md_hash` do texto semeado — nenhum LLM roda na seed), o que também preenche o `harness_score` da v1.0 exibido no T16. A semeadura deixa de ser "no-op se houver qualquer agente" e passa a **convergir por entidade** (ids uuid5 §11.4/A15 + upsert por id): banco de deploy anterior recebe roster novo sem duplicar nada.

## 12. Frontend (SPA — fidelidade aos mocks é critério de aceite)
Vite+React+TS; Tailwind com tokens do artifact (chrome **vermelho Claro #D0271C/#A81E14**, layout 3 zonas: rail esquerdo colapsável / centro / painel direito contextual = casa do copiloto); React Flow com a paleta Journey Builder (entry verde #2E844A, mensagens teal #0B827C, flow laranja #DD7A01, otimização roxa #9050E9, updates azul #0176D3); Recharts para previsto×realizado (barra fantasma + sólida). Rotas: `/` T1 · `/os/:id/(briefing|validacao|warroom|workflow|audiencia|datacloud|criativo|twin|simulacao|portoes|prevoo|lancamento|monitor|perguntas|retro)` · `/aprovacao/:token` (standalone, sem shell) · `/atelie/*`. Contrato de UX da IA em toda tela: prévia/diff + Aplicar/Rejeitar + chips de premissas + badge `via_ai` clicável. i18n pt-BR; teclas ⌘K busca. E2E (Playwright): jornada feliz completa da OS demo pelas 18 telas.

## 13. Qualidade & CI (GitHub Actions)
`ci.yml`: ruff + mypy + pytest (unit/contract) + build front + e2e compose em PR para main; cobertura mínima backend 80% (gate). Job backend com service Postgres (`pgvector/pgvector:pg16`) e step dedicado `pytest -m integration` (persistência A7 — §4/§10.9; o step de unit/aceite roda SEM `DATABASE_URL`, sempre em memória). `pre-commit` com ruff/format. Branches: `main` protegida; `feat/msN-*`. Releases por tag `vMS{n}`.

**Workflow `configurar-vps` (emenda I06, 2026-08-07 — ver CHANGELOG-SDD.md).** `APP_ENV` é decisão consciente do servidor desde a onda 4 (`docker-compose.prod.yml` recusa a ausência). Quando a máquina de operação não tem a chave SSH da VPS (troca de máquina), o único acesso é o do CI — o workflow `configurar-vps.yml` (`workflow_dispatch`) grava `APP_ENV`/`DEMO_MODE` no `.env` do servidor com valores escolhidos EXPLICITAMENTE por quem dispara, nunca sobrescreve variável existente e loga só nomes, jamais valores. A decisão continua humana e auditável; só o transporte é o CI.

**Version-stamp de deploy (emenda A22, 2026-08-06 — ver CHANGELOG-SDD.md).** O commit viaja DENTRO das imagens e o smoke pós-deploy **falha o job** se o ar responder outro SHA — fim do "deploy-fantasma" (2026-08-05: o smoke dizia verde validando uma imagem antiga, porque só checava HTTP 200). Cadeia completa, cada elo obrigatório: `deploy/deploy.sh` e o job `deploy` exportam `GIT_SHA=$(git rev-parse --short HEAD)` → `docker-compose.prod.yml` repassa como **build arg** para `api` e `web` → `backend/Dockerfile` (`ARG GIT_SHA=dev` + `ENV GIT_SHA`) e `frontend/Dockerfile` (`ARG GIT_SHA` + `ENV VITE_GIT_SHA`, antes do `npm run build`, para o SHA entrar no bundle) → `GET /healthz.sha` (§8-M0-A3) e rodapé do rail (`build <sha>`). O smoke bate no host público via `location = /healthz` do nginx (`frontend/nginx.conf`, proxy para `api:8000` — mesma origem da SPA, senão não há como comparar de fora) e compara com o SHA do run: divergiu → `::error::deploy-fantasma` e exit 1. Fora do docker o default é `dev` (nenhum comando git roda em runtime).

## 14. Glossário mínimo
OS (campanha/ordem de serviço) · JGC (grafo canônico) · Snapshot (pacote imutável por hash) · Portão / QA (gate bloqueante — na UI o termo visível é "QA") · Pendência (item bloqueante herdado do Hike; equivale ao “RAID” da referência IBM) · Guard (validador determinístico de elegibilidade) · Governor (árbitro de pressão de contato cross-campanha) · via_ai (ledger de ação de agente) · Previsto (baseline congelado da simulação) · Drift (divergência twin↔SFMC).

---
*SDD v1.0.0 · consome o plano Martech v1.2 (artifact acima) como especificação funcional e visual; em conflito, o SDD prevalece no técnico e o artifact no visual.*
