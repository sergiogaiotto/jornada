Jornada — Digital Twin do Journey Builder (SFMC)
=================================================
Contrato tecnico: SDD-Jornada.md (Spec-Driven Development — codigo que diverge do SDD
esta errado ate que o SDD seja emendado; ver CHANGELOG-SDD.md).

Estrutura (SDD §2.2)
--------------------
  backend/    FastAPI (app factory, config, api/v1, domain, application, adapters,
              agents, migrations alembic, tests)
  frontend/   SPA Vite+React+TS (entra a partir do MS3 — §9/§12)
  mocks/      mock-sfmc, mock-datacloud (FastAPI stubs) + seeds demo
  docker-compose.yml  db(pgvector), api, mock-sfmc, mock-datacloud, mailpit,
                      langfuse + db-langfuse (§10.8)

Subir o ambiente dev (docker)
-----------------------------
  1. copie .env.example para .env (nunca commitar .env)
  2. docker compose up --build
     - API:      http://localhost:8000  (OpenAPI em /docs; health em /healthz)
     - Mailpit:  http://localhost:8025
     - Langfuse: http://localhost:3000  (login dev: dev@jornada.local / jornada-dev)
     - mock-sfmc http://localhost:8080 · mock-datacloud http://localhost:8081

Rodar testes SEM docker
-----------------------
  python -m venv .venv && .venv\Scripts\activate   (Windows)
  pip install -r requirements.txt
  python -m pytest -m "not integration"

Convencoes API (SDD §8)
-----------------------
  - prefixo /api/v1; OpenAPI tags = modulos
  - auth Bearer dev: tokens estaticos "dev-<papel>" com papeis
    solicitante|analista|lider|aprovador|dpo|admin (ex.: Authorization: Bearer dev-admin)
  - header X-Tenant obrigatorio em /api/v1/* (400 sem ele)
  - erros no formato RFC-7807 (application/problem+json)
  - GET /healthz → {"db": "ok|fail", "llm": "skip|ok"}

Qualidade
---------
  - pre-commit install            (ruff lint+format)
  - ruff check . ; mypy ; pytest  (CI: .github/workflows/ci.yml — §13)

Migracoes
---------
  cd backend && alembic upgrade head    (DATABASE_URL do ambiente/.env)
  0001_core = DDL integral do SDD §4.1
