"""Units do A11 · RAG funcional (§7.4): EmbeddingFake determinístico, chunking
~700 tokens/overlap 80, busca ingênua do repositório em memória, RetrieverService
top-k=8 (filtro base+tenant, degrade suave §10.6) e ingestão JSONL idempotente.

Zero rede (§1.3.5): embeddings SEMPRE pelo fake determinístico.
"""

import json
import uuid
from pathlib import Path

import pytest

from adapters.embedding.fake import EmbeddingFake, vetor_deterministico
from adapters.persistence.memoria import RepositorioOsMemoria, _cosseno
from app.rag import SEED_DICIONARIO, dividir_em_chunks, ingerir_jsonl, semear_rag_demo
from application.ports.embedding import EmbeddingIndisponivel
from application.ports.llm import LLMIndisponivel
from application.services.retriever_service import RetrieverService, evidencias_para_contexto
from domain.agentes.modelos import AgenteEvidence

TENANT = "torre-movel"


def _evidencia(
    texto: str, *, base: str = "dicionario_dados", tenant: str = TENANT, dim: int = 64
) -> AgenteEvidence:
    return AgenteEvidence(
        id=uuid.uuid4(),
        tenant_id=tenant,
        base=base,
        ref=None,
        chunk=texto,
        embedding=vetor_deterministico(texto, dim),
    )


# ------------------------------------------------------------- EmbeddingFake
def test_embedding_fake_deterministico_e_semanticamente_util() -> None:
    """Mesmo texto → mesmo vetor (entre instâncias); textos que compartilham tokens
    ficam mais próximos em cosseno do que textos disjuntos."""
    a = EmbeddingFake(dim=64)
    b = EmbeddingFake(dim=64)
    [v1] = a.embed(["consumo_pct da franquia"])
    [v2] = b.embed(["consumo_pct da franquia"])
    assert v1 == v2
    assert len(v1) == 64 and abs(sum(x * x for x in v1) - 1.0) < 1e-9  # L2-normalizado
    [consulta] = a.embed(["consumo_pct"])
    [perto] = a.embed(["consumo_pct percentual de consumo"])
    [longe] = a.embed(["blacklist fraude procon"])
    assert _cosseno(consulta, perto) > _cosseno(consulta, longe)
    assert a.chamadas  # ledger (como LLMFake)


def test_embedding_fake_indisponivel_e_llmindisponivel_like() -> None:
    """EmbeddingIndisponivel HERDA de LLMIndisponivel — os handlers 503 degraded
    (§10.6) já cobrem embeddings sem código novo."""
    fake = EmbeddingFake(disponivel=False)
    assert fake.disponivel() is False
    with pytest.raises(LLMIndisponivel):
        fake.embed(["x"])
    assert issubclass(EmbeddingIndisponivel, LLMIndisponivel)


# ------------------------------------------------------------------ chunking
def test_chunking_700_tokens_overlap_80() -> None:
    """§7.4: chunks de ~700 tokens com overlap 80 — o início de cada chunk repete as
    últimas 80 palavras do anterior; texto curto vira chunk único; vazio → []."""
    palavras = [f"w{i}" for i in range(1500)]
    chunks = [c.split() for c in dividir_em_chunks(" ".join(palavras))]
    assert [len(c) for c in chunks] == [700, 700, 260]  # passo 620: 0..699, 620..1319, 1240..1499
    assert chunks[1][:80] == chunks[0][-80:]  # overlap 80
    assert chunks[2][:80] == chunks[1][-80:]
    assert [p for c in chunks for p in c][-1] == "w1499"  # nada se perde no fim
    assert dividir_em_chunks("uma linha curta") == ["uma linha curta"]
    assert dividir_em_chunks("   ") == []
    with pytest.raises(ValueError):
        dividir_em_chunks("x", max_tokens=100, overlap=100)


# --------------------------------------------- busca ingênua (memória, §7.4)
def test_busca_em_memoria_filtra_tenant_base_e_ranqueia_por_cosseno() -> None:
    repo = RepositorioOsMemoria()
    alvo = _evidencia("consumo_pct percentual da franquia de dados no ciclo")
    outros = [
        _evidencia("lista_supressao blacklist fraude procon optout"),
        _evidencia("opt_in_email consentimento lgpd por canal"),
        _evidencia("consumo_pct de outro tenant", tenant="outro"),
        _evidencia("consumo_pct em outra base", base="ofertas"),
    ]
    for e in [alvo, *outros]:
        repo.adicionar_evidencia(e)
    [consulta] = EmbeddingFake(dim=64).embed(["consumo_pct franquia"])
    resultado = repo.buscar_evidencias(TENANT, ["dicionario_dados"], consulta, 2)
    assert resultado[0].id == alvo.id  # ranking real: o chunk que cita a coluna vem 1º
    assert all(e.tenant_id == TENANT and e.base == "dicionario_dados" for e in resultado)
    assert len(resultado) == 2
    # upsert por id (mesma semântica do SQL): re-adicionar não duplica
    repo.adicionar_evidencia(alvo)
    assert len(repo.listar_evidencias(TENANT, "dicionario_dados")) == 3
    # evidência sem embedding (legado M11) fica fora do ranking, mas na listagem
    repo.adicionar_evidencia(
        AgenteEvidence(
            id=uuid.uuid4(), tenant_id=TENANT, base="dicionario_dados", ref=None, chunk="sem vetor"
        )
    )
    assert len(repo.buscar_evidencias(TENANT, ["dicionario_dados"], consulta, 10)) == 3
    assert len(repo.listar_evidencias(TENANT, "dicionario_dados")) == 4


# ------------------------------------------------------------ RetrieverService
def test_retriever_top_k_8_e_degrade_suave() -> None:
    repo = RepositorioOsMemoria()
    for i in range(12):
        repo.adicionar_evidencia(_evidencia(f"coluna_{i} consumo_pct franquia dado {i}"))
    retriever = RetrieverService(repo, EmbeddingFake(dim=64))
    resultado = retriever.buscar(TENANT, "consumo_pct", bases=["dicionario_dados"])
    assert len(resultado) == 8  # §7.3: top-k=8
    # sem base autorizada / consulta vazia → [] sem tocar o embedding
    assert retriever.buscar(TENANT, "consumo_pct", bases=[]) == []
    assert retriever.buscar(TENANT, "   ", bases=["dicionario_dados"]) == []
    # hub degradado → [] (nunca explode; o agente segue sem RAG — §10.6)
    degradado = RetrieverService(repo, EmbeddingFake(dim=64, disponivel=False))
    assert degradado.buscar(TENANT, "consumo_pct", bases=["dicionario_dados"]) == []


def test_evidencias_para_contexto_formato_citavel() -> None:
    e = _evidencia("consumo_pct percentual")
    e.ref = "hybris_base_clientes.consumo_pct"
    [ctx] = evidencias_para_contexto([e])
    assert ctx == {
        "id": str(e.id),
        "base": "dicionario_dados",
        "ref": "hybris_base_clientes.consumo_pct",
        "trecho": "consumo_pct percentual",
    }


# ------------------------------------------------------------------ ingestão
def test_ingestao_jsonl_idempotente_e_seed_demo(tmp_path: Path) -> None:
    """Ids uuid5 determinísticos → re-ingestão upserta sem duplicar; a seed DEMO
    (mocks/seeds/dicionario_dados.jsonl, ~15 entradas) entra inteira; sem hub a
    seed PULA com log e devolve 0 (boot nunca quebra)."""
    repo = RepositorioOsMemoria()
    fake = EmbeddingFake(dim=64)
    arquivo = tmp_path / "mini.jsonl"
    arquivo.write_text(
        json.dumps({"ref": "t.a", "texto": "coluna a", "meta": {"tabela": "t"}})
        + "\n"
        + json.dumps({"texto": "sem ref tambem entra"})
        + "\n\n",
        encoding="utf-8",
    )
    assert ingerir_jsonl(repo, fake, tenant_id=TENANT, base="ofertas", caminho=arquivo) == 2
    assert ingerir_jsonl(repo, fake, tenant_id=TENANT, base="ofertas", caminho=arquivo) == 2
    evidencias = repo.listar_evidencias(TENANT, "ofertas")
    assert len(evidencias) == 2  # idempotente (upsert por uuid5)
    assert all(e.embedding is not None for e in evidencias)
    assert {e.ref for e in evidencias} == {"t.a", None}

    with pytest.raises(ValueError):  # base fora do conjunto fechado §4.1
        ingerir_jsonl(repo, fake, tenant_id=TENANT, base="qualquer", caminho=arquivo)
    quebrado = tmp_path / "quebrado.jsonl"
    quebrado.write_text('{"texto": ""}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="quebrado.jsonl:1"):  # fail-fast com linha
        ingerir_jsonl(repo, fake, tenant_id=TENANT, base="ofertas", caminho=quebrado)

    # seed DEMO: ~15 entradas realistas (SubscriberKey, msisdn, consumo_pct, opt-in…)
    total = semear_rag_demo(repo, fake, tenant_id=TENANT)
    assert total >= 15 and len(repo.listar_evidencias(TENANT, "dicionario_dados")) == total
    assert SEED_DICIONARIO.name == "dicionario_dados.jsonl"
    chunks = " ".join(e.chunk for e in repo.listar_evidencias(TENANT, "dicionario_dados"))
    assert "consumo_pct" in chunks and "qtd_pacotes_avulsos_3m" in chunks
    # sem hub → skip com log, sem levantar (A11)
    assert semear_rag_demo(repo, EmbeddingFake(disponivel=False), tenant_id=TENANT) == 0
