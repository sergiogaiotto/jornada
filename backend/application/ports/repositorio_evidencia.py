"""Porta de persistência do RAG (`agente_evidence` §4.1/§7.4 — A11).

Collection única filtrada por metadados: `tenant_id` + `base` (conjunto fechado do
§4.1). Busca por similaridade de cosseno: no Postgres o adapter usa pgvector
(`vector_cosine_ops`, índice HNSW da migração 0001); em memória, similaridade
ingênua em Python puro (fallback dev sem DB — mesma semântica, sem índice).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (mesma instância por app — tipagem estrutural).
"""

from typing import Protocol

from domain.agentes.modelos import AgenteEvidence


class RepositorioEvidencia(Protocol):
    def adicionar_evidencia(self, evidencia: AgenteEvidence) -> None:
        """UPSERT por `id` — ingestão com ids uuid5 determinísticos re-executa sem
        duplicar (mesma semântica das seeds §11.4/A15)."""
        ...

    def listar_evidencias(self, tenant_id: str, base: str) -> list[AgenteEvidence]: ...

    def buscar_evidencias(
        self, tenant_id: str, bases: list[str], embedding: list[float], k: int
    ) -> list[AgenteEvidence]:
        """Top-k por similaridade de cosseno, FILTRADO por tenant + bases autorizadas
        (§7.3: preparar_contexto do subgrafo do especialista)."""
        ...
