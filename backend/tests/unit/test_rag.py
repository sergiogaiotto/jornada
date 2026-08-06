"""Units do A11 · RAG funcional (§7.4): EmbeddingFake determinístico, chunking
~700 tokens/overlap 80, busca ingênua do repositório em memória, RetrieverService
top-k=8 (filtro base+tenant, degrade suave §10.6) e ingestão JSONL idempotente.

Zero rede (§1.3.5): embeddings SEMPRE pelo fake determinístico.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from adapters.demo_seeds import OS_CODIGO_DEMO, semear_demo
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


def test_retriever_pina_evidencias_de_compliance(monkeypatch: pytest.MonkeyPatch) -> None:
    """A24: evidência `meta.sempre_incluir` entra SEMPRE, mesmo quando a consulta é
    semanticamente distante. Achado da VPS: buscar "pós-pago 5G ARPU alto" trazia só
    colunas de plano, o Guard exigia opt-in/supressão e o Engineer recusava — com as
    entradas presentes na base. Compliance obrigatório não depende de sorte semântica."""
    repo = RepositorioOsMemoria()
    for i in range(12):  # ruído semântico: plano/ARPU dominam o top-k
        repo.adicionar_evidencia(_evidencia(f"plano_5g arpu faixa {i} elegibilidade upgrade"))
    pinada = _evidencia("lista_supressao: as 7 listas obrigatórias em toda segmentação")
    pinada.ref = "lista_supressao"
    pinada.meta = {"sempre_incluir": True}
    repo.adicionar_evidencia(pinada)

    resultado = RetrieverService(repo, EmbeddingFake(dim=64)).buscar(
        TENANT, "plano 5g arpu alto", bases=["dicionario_dados"]
    )

    assert resultado[0].id == pinada.id, "pinada vem à frente do top-k"
    assert len({e.id for e in resultado}) == len(resultado), "sem duplicata (dedup por id)"
    assert 8 <= len(resultado) <= 9  # top-k 8 + a pinada, quando ela já não ranqueia


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


# ------------------------------------------- B02: a seed x o briefing da OS demo
# Cada critério do briefing da OS-2026-0457 (§11.4) → a coluna do dicionário que o
# sustenta. Sem a coluna, o Engineer com `exige_evidencia: true` recusa — e a recusa
# está CERTA: quem está incompleto é a seed.
_COLUNAS_EXIGIDAS_PELO_BRIEFING_DEMO = {
    "público pós-pago (modalidade)": "hybris_base_clientes.plano",
    "ativos há 12+ meses": "hybris_base_clientes.tempo_casa_meses",
    "sem 5G · plano vigente": "hybris_base_clientes.plano_5g",
    "sem 5G · aparelho compatível": "hybris_base_clientes.aparelho_5g",
    "sem 5G · cobertura de rede": "hybris_base_clientes.cobertura_5g",
    "ARPU ≥ R$ 80": "hybris_base_clientes.arpu_3m",
    "carência: sem upgrade nos últimos 6 meses": "hybris_base_clientes.flag_upgrade_6m",
    "data da última migração de plano": "hybris_base_clientes.data_ultimo_upgrade",
    "degrau de upgrade · origem": "hybris_base_clientes.plano_atual",
    "degrau de upgrade · destino": "hybris_base_clientes.plano_sugerido",
    "oferta com streaming incluso": "hybris_base_clientes.streaming_ativo",
    "dependência: batch Hybris D-1 (frescor)": "hybris_base_clientes.dt_carga",
    "opt-in por canal (WhatsApp no mix)": "hybris_base_clientes.opt_in_whatsapp",
    "restrição: sem abordagem a inadimplentes": "lista_supressao",
}


def _repo_com_seed_rag() -> RepositorioOsMemoria:
    repo = RepositorioOsMemoria()
    assert semear_rag_demo(repo, EmbeddingFake(), tenant_id=TENANT) > 0
    return repo


def test_seed_dicionario_cobre_todos_os_criterios_do_briefing_demo() -> None:
    """B02 (UAT #2): no caminho feliz da demo o Engineer recusou o SQL — corretamente,
    por `exige_evidencia` — porque faltava no dicionário a coluna de upgrade recente
    ("data_ultimo_upgrade ou flag_upgrade_6m"). Ancorado no briefing REAL da seed
    (§11.4): se alguém apertar um critério do briefing sem alimentar o dicionário, o
    demo volta a travar numa recusa honesta e este teste avisa antes do UAT."""
    repo_os = RepositorioOsMemoria()
    semear_demo(repo_os, tenant_id=TENANT, agora=datetime.now(UTC))
    briefing = repo_os.obter_os_por_codigo(OS_CODIGO_DEMO).briefing
    publico = briefing["publico"]["valor"]
    assert "5G" in publico and "ARPU" in publico and "12+" in publico  # o recorte da demo
    assert "5G" in briefing["oferta"]["valor"] and "streaming" in briefing["oferta"]["valor"]

    refs = {e.ref for e in _repo_com_seed_rag().listar_evidencias(TENANT, "dicionario_dados")}
    faltando = {
        criterio: coluna
        for criterio, coluna in _COLUNAS_EXIGIDAS_PELO_BRIEFING_DEMO.items()
        if coluna not in refs
    }
    assert not faltando, f"briefing demo sem coluna no dicionário (B02): {faltando}"


def test_seed_dicionario_pina_so_compliance() -> None:
    """A24: `sempre_incluir` é privilégio do que o Guard exige em TODA segmentação —
    7 listas, opt-in por canal e a chave de ativação. Pinar as colunas de negócio
    (5G, upgrade, ARPU) empurraria o top-k=8 para fora e a pinagem viraria ruído."""
    pinadas = {
        e.ref
        for e in _repo_com_seed_rag().listar_evidencias(TENANT, "dicionario_dados")
        if (e.meta or {}).get("sempre_incluir")
    }
    assert pinadas == {
        "lista_supressao",
        "hybris_base_clientes.contato_hash",
        "hybris_base_clientes.opt_in_email",
        "hybris_base_clientes.opt_in_sms",
        "hybris_base_clientes.opt_in_push",
        "hybris_base_clientes.opt_in_whatsapp",
    }


def test_retriever_acha_a_coluna_de_upgrade_recente_que_faltava() -> None:
    """B02 pelo comportamento: a MESMA pergunta que o Engineer fez ao recusar na VPS
    ("coluna que indique se o cliente fez upgrade nos últimos 6 meses") agora traz a
    evidência no top-k — sem pinagem, só ranking."""
    retriever = RetrieverService(_repo_com_seed_rag(), EmbeddingFake())
    resultado = retriever.buscar(
        TENANT,
        "coluna que indique se o cliente realizou upgrade de plano nos ultimos 6 meses",
        bases=["dicionario_dados"],
    )
    refs = [e.ref for e in resultado]
    assert "hybris_base_clientes.flag_upgrade_6m" in refs
    assert "hybris_base_clientes.data_ultimo_upgrade" in refs
