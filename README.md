# Jornada 🧬

**Digital Twin do Journey Builder (Salesforce Marketing Cloud) — acelerador fim-a-fim de campanhas.**

Toda campanha é *pensada, discutida, criada, avaliada, configurada e disparada* dentro do twin; o SFMC vira o runtime de execução. Construído por **Spec-Driven Development** — o contrato completo está em [`SDD-Jornada.md`](SDD-Jornada.md) e o histórico de decisões em [`CHANGELOG-SDD.md`](CHANGELOG-SDD.md).

## Os 3 princípios

1. **O twin é a fonte da verdade** — a jornada é um grafo canônico JSON (JGC) versionado, snapshot imutável por hash; um compilador determinístico plan/apply materializa no SFMC; monitor de drift acusa edição por fora. *Aprovado = publicado = em execução.*
2. **Nada dispara sem ensaio** — simulação Monte Carlo é portão obrigatório; o "Previsto" congelado é a régua do pós-disparo (todo KPI é previsto × realizado).
3. **IA copilota, humano aprova** — mesh de agentes (Maestro → Triagem → Especialista) sempre como prévia/diff com Aplicar/Rejeitar; ledger `via_ai` (LGPD Art. 20); **compliance é código determinístico, nunca LLM**.

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | Python · FastAPI · arquitetura hexagonal (Diamante 4D) |
| Agentes | LangGraph + Deep-Agent Harness · gpt-oss-120B/20B (HubGPU on-prem, OpenAI-compatible) |
| RAG | PostgreSQL + pgvector · Qwen3-Embedding-0.6B (1024 dims) |
| Frontend | Vite + React + TS · Tailwind · React Flow (paleta Journey Builder) · Recharts |
| Observabilidade | Langfuse self-hosted (trace por invocação: `rag_retrieve → generate → judge`) |
| Integrações | SFMC REST+SOAP (com mock server p/ dev) · Salesforce Data Cloud · importador Hike |

## Rodando

```bash
cp .env.example .env      # ajuste os endpoints do seu ambiente
docker compose up -d      # db(pgvector) · api · mock-sfmc · mock-datacloud · mailpit · langfuse
cd frontend && npm ci && npm run dev   # SPA em http://localhost:5173 (proxy /api → :8000)
```

Com `DEMO_MODE=true`, a campanha-exemplo **OS-2026-0457 · Estouro de Franquia** já vem semeada de ponta a ponta (briefing → GO → certificado LGPD → grafo → simulação → link mágico → plan/apply → rampa canário → monitor previsto × realizado).

```bash
cd backend && python -m pytest -m "not integration" -q   # 142 testes de aceite/unit
```

## Estado

Implementado por milestones auditados (tags `vMS5`–`vMS8`): **M0–M12 do SDD** — governança com pendências (ex-Hike) e SLAs blindados, Consultor de Campanhas, Guard determinístico das 7 listas, twin com simulador reprodutível por seed, compilador SFMC idempotente (golden files byte a byte), rampa com circuit breakers e kill switch, telemetria dupla sem PII, Insight sobre camada semântica, Ateliê com harness como portão de release — e as **18 telas** da SPA. HubGPU real e Langfuse validados (ver CHANGELOG de 2026-08-05).

---
*Cada critério de aceite do SDD é um teste com o mesmo ID (`test_M5_A3`). Divergir do SDD sem emendá-lo é bug.*
