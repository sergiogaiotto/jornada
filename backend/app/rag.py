"""Ingestão RAG (§7.4 — A11): CLI `python -m app.rag ingest <base> <arquivo.jsonl>`
e `python -m app.rag reindex`, + seed DEMO da base `dicionario_dados` (§11.4).

Formato do JSONL: um objeto por linha com `texto` (ou `chunk`), `ref` (opcional) e
`meta` (opcional). Cada texto é dividido em chunks de ~700 tokens com overlap 80
(§7.4; aproximação determinística token≈palavra — sem dependência de tokenizer).
Ids uuid5 determinísticos por tenant/base/ref/índice: re-ingestão faz UPSERT sem
duplicar (mesma semântica das seeds §11.4/A15).

Embeddings SEMPRE via EmbeddingPort (§2.1): CLI usa o adapter real HubGPU; a seed
DEMO no startup usa o port injetado (testes: fake — §1.3.5) e, sem hub, PULA com log
sem quebrar o boot.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import uuid
from pathlib import Path

from application.ports.embedding import EmbeddingPort
from application.ports.repositorio_evidencia import RepositorioEvidencia
from domain.agentes.modelos import AgenteEvidence
from domain.atelie.skill_parser import BASES_RAG_VALIDAS

logger = logging.getLogger(__name__)

SEED_DICIONARIO = Path(__file__).resolve().parents[2] / "mocks" / "seeds" / "dicionario_dados.jsonl"
CHUNK_TOKENS = 700  # §7.4
CHUNK_OVERLAP = 80  # §7.4


def dividir_em_chunks(
    texto: str, *, max_tokens: int = CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """Chunks de ~`max_tokens` com overlap (§7.4). Token ≈ palavra (aproximação
    determinística); texto vazio → []."""
    if max_tokens <= 0 or not 0 <= overlap < max_tokens:
        raise ValueError(f"chunking inválido (max_tokens={max_tokens}, overlap={overlap} — §7.4)")
    palavras = texto.split()
    if not palavras:
        return []
    if len(palavras) <= max_tokens:
        return [" ".join(palavras)]
    chunks: list[str] = []
    passo = max_tokens - overlap
    for inicio in range(0, len(palavras), passo):
        chunks.append(" ".join(palavras[inicio : inicio + max_tokens]))
        if inicio + max_tokens >= len(palavras):
            break
    return chunks


def _id_evidencia(tenant_id: str, base: str, ref: str, indice: int) -> uuid.UUID:
    """uuid5 determinístico (padrão das seeds §11.4/A15) — re-ingestão upserta."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"jornada/evidencia/{tenant_id}/{base}/{ref}/{indice}")


def ingerir_jsonl(
    repositorio: RepositorioEvidencia,
    embedding: EmbeddingPort,
    *,
    tenant_id: str,
    base: str,
    caminho: Path,
) -> int:
    """Ingere um .jsonl na collection (§7.4): chunking + embeddings em lote (uma
    chamada ao hub) + upsert por id determinístico. Devolve o nº de chunks gravados.
    Linha malformada é REJEITADA com o número da linha (fail-fast: collection nunca
    fica meio-ingerida por lixo silencioso)."""
    if base not in BASES_RAG_VALIDAS:
        raise ValueError(f"base {base!r} fora do conjunto fechado §4.1: {list(BASES_RAG_VALIDAS)}")
    evidencias: list[AgenteEvidence] = []
    with caminho.open(encoding="utf-8") as arquivo:
        for numero, linha in enumerate(arquivo, start=1):
            if not linha.strip():
                continue
            try:
                registro = json.loads(linha)
            except ValueError as erro:
                raise ValueError(f"{caminho.name}:{numero}: JSON inválido ({erro})") from erro
            if not isinstance(registro, dict):
                raise ValueError(f"{caminho.name}:{numero}: esperado objeto JSON por linha")
            texto = str(registro.get("texto") or registro.get("chunk") or "").strip()
            if not texto:
                raise ValueError(f"{caminho.name}:{numero}: campo `texto` (ou `chunk`) vazio")
            meta = registro.get("meta") or {}
            if not isinstance(meta, dict):
                raise ValueError(f"{caminho.name}:{numero}: `meta` deve ser objeto JSON")
            ref = str(registro.get("ref") or "").strip() or None
            rotulo = ref or hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]
            for indice, chunk in enumerate(dividir_em_chunks(texto)):
                evidencias.append(
                    AgenteEvidence(
                        id=_id_evidencia(tenant_id, base, rotulo, indice),
                        tenant_id=tenant_id,
                        base=base,
                        ref=ref,
                        chunk=chunk,
                        meta=dict(meta),
                    )
                )
    if not evidencias:
        return 0
    vetores = embedding.embed([e.chunk for e in evidencias])  # lote: 1 chamada ao hub
    for evidencia, vetor in zip(evidencias, vetores, strict=True):
        evidencia.embedding = vetor
        repositorio.adicionar_evidencia(evidencia)
    return len(evidencias)


def reindexar(
    repositorio: RepositorioEvidencia, embedding: EmbeddingPort, *, tenant_id: str
) -> int:
    """`rag reindex` (§7.4/§10.4): re-embeda TODOS os chunks do tenant (mudança de
    EMBED_DIM/modelo) — upsert por id preserva chunk/meta/ref."""
    total = 0
    for base in BASES_RAG_VALIDAS:
        evidencias = repositorio.listar_evidencias(tenant_id, base)
        if not evidencias:
            continue
        vetores = embedding.embed([e.chunk for e in evidencias])
        for evidencia, vetor in zip(evidencias, vetores, strict=True):
            evidencia.embedding = vetor
            repositorio.adicionar_evidencia(evidencia)
        total += len(evidencias)
    return total


def semear_rag_demo(
    repositorio: RepositorioEvidencia, embedding: EmbeddingPort, *, tenant_id: str
) -> int:
    """Seed DEMO_MODE (§11.4 — A11): ingere `mocks/seeds/dicionario_dados.jsonl` na
    base `dicionario_dados` no startup. SEM hub (indisponível/timeout/erro) → PULA
    com log e o boot segue (robustez §10.6: demo funciona sem RAG)."""
    try:
        total = ingerir_jsonl(
            repositorio,
            embedding,
            tenant_id=tenant_id,
            base="dicionario_dados",
            caminho=SEED_DICIONARIO,
        )
        logger.info("Seed RAG dicionario_dados: %d chunks ingeridos (DEMO_MODE §11.4)", total)
        return total
    except Exception as exc:  # noqa: BLE001 — sem hub → skip com log, sem quebrar (A11)
        logger.warning(
            "Seed RAG dicionario_dados PULADA (%s: %s) — demo segue sem RAG",
            type(exc).__name__,
            exc,
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    """CLI §7.4. Exemplos:
    python -m app.rag ingest dicionario_dados ../mocks/seeds/dicionario_dados.jsonl
    python -m app.rag reindex
    """
    from adapters.embedding.hubgpu import EmbeddingHubGPU
    from adapters.persistence.sql import RepositorioSql, criar_repositorio
    from app.config import get_settings

    settings = get_settings()
    parser = argparse.ArgumentParser(prog="python -m app.rag", description=main.__doc__)
    sub = parser.add_subparsers(dest="comando", required=True)
    p_ingest = sub.add_parser("ingest", help="ingere um .jsonl numa base (§7.4)")
    p_ingest.add_argument("base", choices=sorted(BASES_RAG_VALIDAS))
    p_ingest.add_argument("arquivo", type=Path)
    p_ingest.add_argument("--tenant", default=settings.default_tenant)
    p_reindex = sub.add_parser("reindex", help="re-embeda a collection (§10.4)")
    p_reindex.add_argument("--tenant", default=settings.default_tenant)
    args = parser.parse_args(argv)

    repositorio = criar_repositorio(os.environ.get("DATABASE_URL"))
    if not isinstance(repositorio, RepositorioSql):
        print(
            "AVISO: Postgres inalcançável — ingestão cai no repositório em memória "
            "(VOLÁTIL; útil só para smoke). Exporte DATABASE_URL para persistir.",
            file=sys.stderr,
        )
    embedding = EmbeddingHubGPU(settings)
    if args.comando == "ingest":
        total = ingerir_jsonl(
            repositorio, embedding, tenant_id=args.tenant, base=args.base, caminho=args.arquivo
        )
        print(f"ingest {args.base}: {total} chunks gravados (tenant {args.tenant})")
    else:
        total = reindexar(repositorio, embedding, tenant_id=args.tenant)
        print(f"reindex: {total} chunks re-embedados (tenant {args.tenant})")
    return 0


if __name__ == "__main__":  # pragma: no cover — entrypoint do CLI (§7.4)
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
