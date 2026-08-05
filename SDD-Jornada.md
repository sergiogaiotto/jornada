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
sqlalchemy[asyncio]~=2.0  alembic~=1.13  asyncpg~=0.29  pgvector~=0.3
langgraph~=0.2  langgraph-checkpoint-postgres~=2.0  deepagents
openai~=1.50  httpx~=0.27  tenacity~=9.0  zeep~=4.2  langfuse~=2.53
python-jose[cryptography]~=3.3  structlog~=24.4  python-docx~=1.1  orjson~=3.10
pytest~=8.3  pytest-asyncio~=0.24  respx~=0.21  ruff~=0.6  mypy~=1.11
```
(Formato real: uma dependência por linha. `zeep` = SOAP SFMC; `deepagents` = Deep-Agent Harness; `python-docx` = documentos executivos dos portões.)

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
  invalidada_em timestamptz, invalidada_motivo text             -- A4: custo >10% pós-aprovação (emenda M8 parte 2, migração 0006)
);

create table segmento (
  id uuid primary key default gen_random_uuid(), os_id uuid references os,
  origem text not null check (origem in ('estudio_sql','data_cloud')),
  dc_segment_id text, sql_publico text, criterios_resumo text,
  contagem_bruta int, contagem_liquida int, waterfall jsonb,    -- [{etapa, corte, restante, motivo}]
  volume_abordagem jsonb,                                        -- {email:{n,pct},sms:{...},push:{...},whatsapp:{...}}
  holdout_pct numeric(4,1) default 10.0, frescor jsonb           -- {fonte: ultima_atualizacao}
);

create table experimento (
  id uuid primary key default gen_random_uuid(), os_id uuid references os not null,
  holdout_pct numeric(4,1) not null, n_minimo int not null, mde_pp numeric(5,2) not null,
  janela_dias int not null, metricas jsonb not null, travado_em timestamptz,
  estado text default 'pre_registrado' check (estado in ('pre_registrado','em_apuracao','apurado')),
  resultado jsonb                                                -- {lift, ic95:[a,b], significativo, roas}
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
  eventos jsonb default '[]'
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

JSON Schema em `backend/domain/jornada/jgc.schema.json` (fonte da verdade; Pydantic gerado a partir dele). Canonicalização RFC 8785 → `sha256` = hash da versão.

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
| `decisionSplit` | regras[{expr sobre atributos/eventos, to}] | Decision Split |
| `engagementSplit` | metrica(open/click), janela | Engagement Split |
| `frequencySplit` | classes(saturado/ok/sub), fonte=governor | Einstein Frequency **ou** twin-emulado (decision sobre score) |
| `sto` | janelaHoras(24), fallback | Einstein STO **ou** twin-emulado (Wait By Attribute com hora ótima) |
| `wait` | duracao(iso8601) ou ate(atributo) | Wait |
| `channel.email/sms/push/whatsapp/rcs` | assetRef, throttlePorHora?, custoUnit(lookup tarifa) | Send/Message activity |
| `updateContact` | deRef, valores | Update Contact |
| `goal` | metrica, deRef | Goal |
| `exit` | motivo | Exit |
| `exception` | payloadOriginal (Adopt Wizard: nó não mapeável) | — (bloqueia publish até resolução) |

### 5.3 Validação semântica (serviço `jgc_validate`, executa a cada save)
Erros bloqueantes: nó órfão/braço sem destino; `channel.*` sem opt-in configurado; soma de pcts ≠ 100; holdout ausente quando experimento pré-registrado; `reentrada != nao` com holdout (quebra o experimento); throttle acima do cap da política; wait que ultrapassa janela da oferta; grafo sem `goal`. Warnings: custo projetado > budget; pressão de contato prevista > cap.

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
- Saída (persistida em `jornada_versao` e congelada no snapshot como `previsto`): funil por nó/aresta, conversões/custo/receita/ROAS em **P10/P50/P90**, lift esperado + validação de poder (n mínimo por MDE), gargalos, pressão de contato.
- NFR: 10k personas < 60 s (vetorizar com numpy; sem I/O no loop).
- Semáforo: verde/amarelo/vermelho → vermelho bloqueia T9/T11; regra (precedência do aceite §8-M8-A2 — emenda M8): vermelho se ROAS P50 < 1 ou colisão crítica do governor; poder insuficiente pinta o portão de experimento de vermelho e a simulação de amarelo; avisos (ex.: custo P50 > verba) também dão amarelo.

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
Uma collection `agente_evidence` (vector 1024, cosine, HNSW), filtro por `base` + `tenant_id`. Ingestão por base com CLI `python -m app.rag ingest <base> <path>`; chunk ~700 tokens, overlap 80. **Mudar `EMBED_DIM` exige re-embed completo** (comando `rag reindex`; busca fica indisponível até concluir — exibir aviso na UI T16/Bases).

---

## 8. Módulos, endpoints e critérios de aceite

Convenções API: prefixo `/api/v1`; auth Bearer (dev: token estático de `usuario` seed); header `X-Tenant` obrigatório; erros RFC-7807; paginação `?limit&offset`; mutações aceitam `Idempotency-Key`. OpenAPI tags = módulos. Abaixo, por módulo: endpoints principais + aceites (IDs viram testes).

### M0 · Fundação
Repo, docker-compose (db+api+web+mocks+mailpit), config, migração 0001, auth dev, RBAC (papéis: solicitante, analista, lider, aprovador, dpo, admin — decorator `require_role`), `/healthz`, CI (§13).
**A1** dado compose up, quando `GET /healthz`, então `{db:ok, llm:skip|ok}` em <2s. **A2** requisição sem `X-Tenant` → 400.

### M1 · Núcleo OS/governança
`POST/GET /os` · `GET /os/{id}` · `POST /os/{id}/fase` (só transições legais; portões checados) · `POST /os/{id}/pendencias` · `POST /pendencias/{id}/resolver|aceitar` · `GET /os/{id}/saude` · SLA service (congela prazos no GO; estados correndo/pausado_cliente/bloqueado_pendencia).
**A1** pendência bloqueante aberta → `POST fase` avança? Não: 409 com motivo. **A2** aceite de pendência exige papel accountable + justificativa; gera `domain_event`. **A3** saúde é view — não existe endpoint de escrita de saúde (teste verifica 405/404).

### M2 · Esteira de Produção (T4a) + Hike import
`GET/PATCH /os/{id}/workflow` (7 etapas, checklist, dependências) · `POST /admin/hike/import` (aceita export JSON/CSV do Hike → cria OS+etapas com `hike_ref`; log em `hike_import_log`).
**A1** etapa Criativos criada com 4 subtarefas padrão. **A2** etapa com dependência insatisfeita não vai a `em_andamento` (409). **A3** import de fixture `mocks/seeds/hike_export.json` cria 3 OSs com histórico preservado.

### M3 · Intake & Consultor (T2 + Portal do Solicitante)
`POST /pedidos` (criação NA APP — emenda 2026-08-05: o Portal do Solicitante foi aposentado; o token de portal segue aceito como auth de link, sem login pleno) · `POST /pedidos/{id}/mensagem` (conversa com consultor; retorna conteúdo atualizado + completude + faltantes; retry §7.3 sem inferências PRESERVA a resposta da 1ª chamada — a resposta ao reprompt do sistema não vaza) · `POST /pedidos/{id}/converter` (→ OS com briefing pré-preenchido; campos `inferido:true` até confirmação) · CRUD (emenda 2026-08-05): `GET /pedidos` (lista do tenant, mais recente primeiro: id, solicitante, completude, faltantes, estado, os_id, updated_at — sem `conteudo`; arquivados fora por padrão, `?arquivados=true` inclui; login pleno) · `GET /pedidos/{id}` (detalhe completo) · `PATCH /pedidos/{id}/campos` `{campo: valor}` (edição manual direta → `inferido:false`, completude recalculada por código; convertido/arquivado → 409; analista|lider) · `POST /pedidos/{id}/arquivar` (soft e idempotente; convertido → 409; arquivado bloqueia mensagem/edição/conversão; analista|lider) · `GET /os/{id}/briefing` · `PATCH .../briefing/{campo}` (confirmar/editar).
**A1** pedido sem verba/janela → completude<100 e faltantes lista exatamente esses campos. **A2** converter exige completude=100. **A3** toda inferência do consultor carrega `via_ai` + evidências (precedentes). **A4** retry §7.3 esgotado sem inferências → a resposta exibida (e o ledger `invocacao`) é a da 1ª chamada; o reprompt "SISTEMA:" jamais vaza ao solicitante. **B1** `GET /pedidos` lista o resumo do tenant (isolado por tenant; sem `conteudo`; login pleno). **B2** `PATCH /pedidos/{id}/campos` rebaixa a `inferido:false` e recalcula completude/faltantes/estado por CÓDIGO; convertido → 409. **B3** arquivar é soft (fora da lista padrão, legível por id) e idempotente; convertido → 409.

### M4 · Validação campo-a-campo & War Room (T3/T4)
`POST /os/{id}/validacoes/{campo}` (executa checagem automática contra fonte: contagem, schema, frescor; retorna evidência) · `POST .../validacoes/{campo}/pendencia` · threads: `POST /os/{id}/threads` ancoradas em campo · `POST /os/{id}/go` (GO: congela SLAs+versões em `os.frozen`, fase→criada).
**A1** GO com campo não decidido ou pendência bloqueante → 409 listando pendências. **A2** após GO, `frozen` contém versões publicadas atuais de agentes e política. **A3** doc executivo (.docx) gerado no GO e armazenado.

### M5 · Audiência (T5) + Guard + Data Cloud (T5a)
`POST /os/{id}/segmento/gerar-sql` (engineer) · `POST /segmentos/{id}/recontar` (dry-run no read model; waterfall + líquido) · `PUT /segmentos/{id}/holdout` · **Guard determinístico**: `POST /segmentos/{id}/certificar` (varre 7 listas + opt-in; emite `certificado_elegibilidade`) · Data Cloud: `GET /datacloud/segmentos` (cache+frescor) · `GET /datacloud/segmentos/{id}/relatorio` (bruto→elegível→líquido→sobreposição + **volume de abordagem por canal** pós caps/quiet/colisões) · `POST /datacloud/segmentos/{id}/usar` (vira `segmento` origem data_cloud com lineage) · `GET .../relatorio.docx`.
**A1** SQL gerado sem as 7 listas no WHERE → guard reprova certificação (unit com SQL adulterado). **A2** relatório de volume: soma por canal ≤ líquido; percentuais calculados sobre líquido; colisões vêm do governor. **A3** certificado tem hash e validade; publish (M8) recusa certificado expirado. **A4** contagens exibem frescor por fonte (Hybris D-1 nas fixtures).

### M6 · Criativo (T6)
`POST /os/{id}/criativos/gerar` (matriz canal×variante a partir do KV master) · `PATCH /criativos/{id}/celula` (aprovar/revisar por célula) · validadores: SMS≤160, template WhatsApp status, compliance de linguagem (regras + LLM warn).
**A1** SMS 161 chars → 422. **A2** edição do KV master marca células derivadas `adaptado_revisar`. **A3** nenhuma célula vai a `aprovado` via agente — só usuário com papel analista+.

### M7 · Twin Canvas (T7)
`POST /os/{id}/jornada/gerar` (flow → JGC) · `GET /os/{id}/jornada` (última versão do twin da OS; 404 quando não há versão — leitura determinística do canvas, emenda 2026-08-05) · `PUT /jornadas/{id}/grafo` (valida §5.3; recalcula taxímetro) · `POST /jornadas/{id}/ajustar` (texto livre → diff proposto, nunca aplica direto) · `GET /jornadas/{id}/no/{noId}/sfmc-preview` (JSON que o compilador gerará).
Editor "começar do zero" (emenda 2026-08-05 — determinístico, ZERO LLM §10.6): `POST /os/{id}/jornada` (cria NOVA versão `rascunho` sem agente: corpo `{grafo?}` opcional — com `grafo`, valida §5.3 antes de persistir com 422 apontando o nó; sem `grafo`, o servidor gera o esqueleto mínimo `entrySource → goal → exit` que passa no `jgc_validate`; meta.osCodigo/tenant sempre reescritos com os valores da OS §1.3.5; taxímetro recalculado A2; funciona com o hub LLM fora §10.6 — é a porta de entrada do editor visual T7 quando o usuário não quer o Flow).
Versionamento & exportação (emenda 2026-08-05 — determinístico, ZERO LLM §10.6): `GET /os/{id}/jornadas` (lista resumida em ordem de `versao`: id, versao, estado, hash, custo_projetado, created_at — sem grafo; OS sem versão → `[]`) · `GET /jornadas/{id}` (versão específica completa) · `POST /jornadas/{id}/restaurar` (clona como NOVA versão `rascunho` com grafo/hash idênticos e taxímetro recalculado — versões nunca são editadas retroativamente; simulação/previsto não acompanham) · `GET /jornadas/{a}/diff/{b}` (`domain/jornada/diff.py` — o mesmo diff do ajustar/M11: nós/arestas adicionados·removidos·alterados + `meta_alterada`, com `de`/`para` {id, versao, hash}; versões de OSs diferentes → 409) · `GET /jornadas/{id}/export?formato=json|xml` (download `Content-Disposition`; **json** = spec de interaction do Journey Builder — import NATIVO do JB, REST `/interaction/v1/interactions`, montada reaproveitando o compilador M9 §5.4: key `jrn-{hash[0:12]}`, activities com externalKeys idempotentes, triggers, goals; **xml** = a MESMA spec em serialização determinística/canônica `<Interaction><Activities><Activity type=...>` com `<Manifest>` embutido (hash JGC, versao, geradoEm via ClockPort, plataforma Jornada), válida contra `backend/domain/jornada/journey_export.xsd` — honestamente: o JB não importa XML; o formato atende integração/auditoria corporativa. Grafo com nó `exception` → 422 com `nos` §5.2).
**A1** grafo com braço órfão → 422 com apontamento do nó. **A2** taxímetro = Σ(volume esperado × tarifa vigente) — teste com fixture bate valor exato. **A3** `reentrada=qualquer_momento` + experimento travado → 422 (contrato de re-entrada). **B1** lista de versões ordenada por `versao` (resumo sem grafo). **B2** restaurar cria nova versão rascunho com grafo idêntico e hash igual (origem intocada). **B3** diff acusa nó adicionado/alterado/removido + arestas. **B4** export JSON = interaction com todas as activities do grafo (externalKeys §5.4.1). **B5** export XML válido contra o XSD e determinístico byte a byte com mesmo grafo+clock.

### M8 · Simulador (T8) + Portões (T9) + Aprovação (T10)
`POST /jornadas/{id}/simular` (§6; persiste resultado) · `POST /jornadas/{id}/congelar-previsto` · cenários: `POST /simulacoes/comparar` · Portões: `GET /os/{id}/portoes` (certificado, experimento, custo/alçada, governor) · `POST /experimentos` (pré-registro + poder) · `POST /os/{id}/custo/enviar-alcada` · Aprovação: `POST /snapshots` (monta hash composto) · `POST /snapshots/{id}/link-magico` → URL pública `GET /aprovacao/{token}` (página standalone: resumo, waterfall, criativos, replay do previsto, hash) · `POST /aprovacao/{token}/decidir`.
**A1** simulação com seed fixa é reprodutível (mesmos P50s). **A2** poder insuficiente (n<n_minimo) → portão experimento vermelho e simulação amarela. **A3** token: uso único, expira, registra ip/device; ressalvas criam pendências automaticamente. **A4** variação de custo >10% após aprovação → invalida aprovação (snapshot novo obrigatório).

### M9 · Compilador & Pré-voo (T11)
`POST /snapshots/{id}/plan?ambiente=` · `POST /snapshots/{id}/apply` (exige: aprovação + certificado + pre-flight verde) · `GET /sync-runs/{id}` · `POST /preflight/{snapshot}` (bateria: DEs/schema, freshness Hybris, opt-in, listas last-mile, lint AMPscript, limites SFMC, drift=0, seed dry-run) · `GET /drift` · `POST /drift/{id}/resolver` (adopt/enforce/excecao).
**A1** apply sem plan prévio → 409. **A2** golden files: payloads REST/SOAP gerados batem byte a byte com `tests/contract/golden/*.json|xml` (mock-sfmc valida schema). **A3** re-execução de apply com mesmo hash → 0 mutações (idempotência por externalKey). **A4** drift injetado no mock em prod → pendência automática bloqueante.

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
3. Secrets só via env/vault; `.env` no `.gitignore`; `APP_SECRET` obrigatório ≠ default em `APP_ENV=prod` (startup falha).
4. Purge: job diário remove `telemetry_event` e DEs de campanhas além de `retencao_dias` da política; destruição registrada em `domain_event`.
5. RBAC + segregação: criador ≠ aprovador nos portões (checagem server-side).
6. **Modo degradado**: se hub LLM indisponível (healthcheck), agentes retornam 503 `degraded` e a UI oferece modo manual; caminho crítico (guard, compilador, governor, breakers, kill) NUNCA depende de LLM — teste e2e com `LLM_DEGRADED_MODE=forced_off` deve completar M9/M10.
7. Timeout LLM 300s; retries 2 com jitter; circuit breaker por 60s após 3 falhas.
8. **Observabilidade via Langfuse (self-hosted)** — serviço `langfuse` no docker-compose (imagem `langfuse/langfuse:2` + Postgres próprio `db-langfuse`). Contrato de instrumentação: toda chamada via `LLMPort`/`EmbeddingPort` gera um **trace Langfuse com `trace_id = invocacao.id`** (metadados: tenant, os_id, agente, skill_versao, modelo_perfil) e spans `rag_retrieve` → `generate` → `judge`; tokens/latência espelhados na tabela `invocacao` (o ledger `via_ai` continua a fonte de auditoria LGPD; Langfuse é a lente operacional). Envio assíncrono fire-and-forget: queda do Langfuse **nunca** bloqueia a aplicação (`LANGFUSE_ENABLED=false` → no-op). A tela T16/Observabilidade linka para o dashboard Langfuse (custo de IA por OS, latência por agente, taxa de retry/judge-fail); harness runs também são traceados (tag `harness`).

## 11. Mocks e seeds (obrigatórios para dev/CI)
1. **mock-sfmc** (FastAPI): token OAuth, REST (eventDefinitions, interactions, assets) e SOAP (DataExtension, Automation) com validação de schema + estado em memória; endpoints de injeção de falha (`/chaos/rate-limit`, `/chaos/drift`).
2. **mock-datacloud**: token + `GET /segments` (4 segmentos das fixtures do plano) + query count.
3. **mailpit** para e-mails de notificação/link mágico em dev.
4. **Seeds DEMO_MODE**: OS-2026-0457 completa (briefing 14 campos, segmento 847.312, JGC do mock T7, previsto, telemetria 20 dias com lift +24,1%/ROAS 18,5x), tarifário (email 0,0018; push 0,0005; sms 0; whatsapp 0,3597), 7 listas com contagens, políticas v1, agentes+skills v1, 3 casos golden por agente, `hike_export.json`.

## 12. Frontend (SPA — fidelidade aos mocks é critério de aceite)
Vite+React+TS; Tailwind com tokens do artifact (chrome **vermelho Claro #D0271C/#A81E14**, layout 3 zonas: rail esquerdo colapsável / centro / painel direito contextual = casa do copiloto); React Flow com a paleta Journey Builder (entry verde #2E844A, mensagens teal #0B827C, flow laranja #DD7A01, otimização roxa #9050E9, updates azul #0176D3); Recharts para previsto×realizado (barra fantasma + sólida). Rotas: `/` T1 · `/os/:id/(briefing|validacao|warroom|workflow|audiencia|datacloud|criativo|twin|simulacao|portoes|prevoo|lancamento|monitor|perguntas|retro)` · `/aprovacao/:token` (standalone, sem shell) · `/atelie/*`. Contrato de UX da IA em toda tela: prévia/diff + Aplicar/Rejeitar + chips de premissas + badge `via_ai` clicável. i18n pt-BR; teclas ⌘K busca. E2E (Playwright): jornada feliz completa da OS demo pelas 18 telas.

## 13. Qualidade & CI (GitHub Actions)
`ci.yml`: ruff + mypy + pytest (unit/contract) + build front + e2e compose em PR para main; cobertura mínima backend 80% (gate). `pre-commit` com ruff/format. Branches: `main` protegida; `feat/msN-*`. Releases por tag `vMS{n}`.

## 14. Glossário mínimo
OS (campanha/ordem de serviço) · JGC (grafo canônico) · Snapshot (pacote imutável por hash) · Portão / QA (gate bloqueante — na UI o termo visível é "QA") · Pendência (item bloqueante herdado do Hike; equivale ao “RAID” da referência IBM) · Guard (validador determinístico de elegibilidade) · Governor (árbitro de pressão de contato cross-campanha) · via_ai (ledger de ação de agente) · Previsto (baseline congelado da simulação) · Drift (divergência twin↔SFMC).

---
*SDD v1.0.0 · consome o plano Martech v1.2 (artifact acima) como especificação funcional e visual; em conflito, o SDD prevalece no técnico e o artifact no visual.*
