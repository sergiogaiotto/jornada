# CHANGELOG-SDD

Registro de emendas e decisões sobre o SDD-Jornada.md (regra §1.3.3: toda divergência
necessária edita o SDD na seção afetada + entrada aqui, no mesmo PR).

## 2026-08-04 — Adoção do Langfuse self-hosted como observabilidade de LLM (§10.8)
- **Motivo:** necessidade de lente operacional sobre toda chamada LLM/Embedding (custo de IA
  por OS, latência por agente, taxa de retry/judge-fail) sem depender de SaaS externo e sem
  substituir o ledger `invocacao` (`via_ai`), que permanece a fonte de auditoria LGPD (Art. 20).
- **Impacto:**
  - `docker-compose.yml` ganha os serviços `langfuse` (imagem `langfuse/langfuse:2`) e
    `db-langfuse` (Postgres próprio, isolado do banco da aplicação).
  - `.env.example` ganha o bloco `LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY/ENABLED` (§3.1);
    `LANGFUSE_ENABLED=false` → no-op (a aplicação nunca depende do Langfuse).
  - `requirements.txt` inclui `langfuse~=2.53` (§3.2).
  - Contrato de instrumentação (§10.8): trace por invocação com `trace_id = invocacao.id`,
    spans `rag_retrieve` → `generate` → `judge`, envio assíncrono fire-and-forget; harness
    runs traceados com tag `harness`. Implementação do adapter ocorre junto ao `LLMPort` (M5+).

## 2026-08-04 — M0 · Emenda §4.1: ordem da view `os_saude` no DDL
- **Motivo:** no DDL original a view `os_saude` era declarada antes das tabelas `sla_clock` e
  `pendencia`, que ela referencia — a execução top-down da migração `0001_core` falharia.
- **Impacto:** bloco `create view os_saude` movido no §4.1 para depois de `pendencia`.
  Nenhuma mudança semântica (mesmas colunas/regra de saúde). Migração `0001_core` segue a
  nova ordem.

## 2026-08-04 — M0 · Notas de implementação (sem mudança de contrato)
- `.env.example` e `requirements.txt` materializados "um item por linha" (o §3.1/§3.2 compacta
  linhas por legibilidade; o próprio §3.2 indica o formato real).
- Aceite `test_M0_A1` roda via `TestClient` **sem docker**: o ping de banco do `/healthz` é
  substituído por dublê via `dependency_overrides` para simular a pré-condição "compose up"
  (db saudável). A validação real com `docker compose up` permanece no DoD do MS1 (§9) e no
  job de e2e do CI (a ativar no MS8 §13). Máquina de dev atual possui docker; a limitação é
  apenas do modo de execução dos testes unit/aceite.
- Serviço `web` do compose (§2.2/§8-M0) deixado comentado até o frontend existir (MS3+, §9) —
  compose precisa subir verde no MS1 sem build de frontend.
- CI (§13): jobs de build do front e e2e compose ficam condicionados/pendentes até MS3/MS8;
  ruff + mypy + pytest (cobertura ≥ 80%) ativos desde o M0. `pytest-cov` instalado só no CI
  (não consta do §3.2).
