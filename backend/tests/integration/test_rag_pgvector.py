"""A11 — RAG no Postgres REAL (@integration): ingest + retrieve na collection
`agente_evidence` (§4.1/§7.4) com pgvector (cosine, índice HNSW da migração 0001).

Embeddings SEMPRE pelo fake determinístico (§1.3.5 — dim 1024, a mesma do DDL);
o que se prova aqui é o ADAPTER: upsert idempotente por uuid5, hidratação
vector↔list[float], top-k ordenado por `cosine_distance` filtrado por tenant+bases,
e durabilidade (engine novo = restart).
"""

import uuid

import pytest

from adapters.embedding.fake import EmbeddingFake
from adapters.persistence.sql import RepositorioSql, criar_engine
from app.rag import SEED_DICIONARIO, ingerir_jsonl, reindexar
from application.services.retriever_service import RetrieverService
from domain.agentes.modelos import AgenteEvidence

pytestmark = pytest.mark.integration

TENANT = "torre-movel"


def _repositorio_novo(url: str) -> RepositorioSql:
    """Engine NOVO — simula um restart do processo (nada em cache/na memória)."""
    return RepositorioSql(criar_engine(url))


def test_ingest_e_retrieve_pgvector(banco_limpo: str) -> None:
    repo = _repositorio_novo(banco_limpo)
    fake = EmbeddingFake()  # dim 1024 = DDL §4.1
    total = ingerir_jsonl(
        repo, fake, tenant_id=TENANT, base="dicionario_dados", caminho=SEED_DICIONARIO
    )
    assert total >= 15
    # idempotência: re-ingestão upserta pelos MESMOS uuid5 — nada duplica
    assert (
        ingerir_jsonl(
            repo, fake, tenant_id=TENANT, base="dicionario_dados", caminho=SEED_DICIONARIO
        )
        == total
    )
    assert len(repo.listar_evidencias(TENANT, "dicionario_dados")) == total

    # retrieve num engine NOVO (restart): hidratação vector→list[float] + top-k=8
    repo2 = _repositorio_novo(banco_limpo)
    retriever = RetrieverService(repo2, fake)
    resultado = retriever.buscar(
        TENANT, "consumo_pct franquia de dados no ciclo", bases=["dicionario_dados"]
    )
    assert len(resultado) == 8
    assert "consumo_pct" in resultado[0].chunk  # cosine_distance ordena de verdade
    assert isinstance(resultado[0].embedding, list) and len(resultado[0].embedding) == 1024

    # filtros: tenant errado e base não autorizada → nada
    [vetor_x] = fake.embed(["x"])
    assert repo2.buscar_evidencias("outro-tenant", ["dicionario_dados"], vetor_x, 8) == []
    assert retriever.buscar(TENANT, "consumo_pct", bases=["ofertas"]) == []


def test_reindex_e_fallback_sem_vetor(banco_limpo: str) -> None:
    repo = _repositorio_novo(banco_limpo)
    fake = EmbeddingFake()
    [vetor] = fake.embed(["Campanha upgrade 5G: ROAS 12x"])
    persistida = AgenteEvidence(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        base="resultados",
        ref="aprendizado:x",
        chunk="Campanha upgrade 5G: ROAS 12x",
        meta={"lift": 24.1},
        embedding=vetor,
    )
    repo.adicionar_evidencia(persistida)
    # M11 promove SEM vetor (caminho §10.6 sem hub) → fallback memória, sem quebrar
    repo.adicionar_evidencia(
        AgenteEvidence(
            id=uuid.uuid4(), tenant_id=TENANT, base="resultados", ref=None, chunk="sem vetor"
        )
    )
    listadas = repo.listar_evidencias(TENANT, "resultados")
    assert {e.chunk for e in listadas} == {"Campanha upgrade 5G: ROAS 12x", "sem vetor"}

    # restart: só a linha com vetor é durável (a sem vetor era o fallback do processo)
    repo2 = _repositorio_novo(banco_limpo)
    duraveis = repo2.listar_evidencias(TENANT, "resultados")
    assert [e.ref for e in duraveis] == ["aprendizado:x"]
    assert dict(duraveis[0].meta) == {"lift": 24.1}

    # reindex (§10.4): re-embeda tudo preservando chunk/meta/id (upsert)
    assert reindexar(repo2, fake, tenant_id=TENANT) == 1
    assert repo2.listar_evidencias(TENANT, "resultados")[0].id == persistida.id
