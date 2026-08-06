"""RetrieverService — `preparar_contexto` do subgrafo do especialista (§7.3/§7.4, A11).

Top-k=8 por similaridade de cosseno na collection `agente_evidence`, FILTRADO por
`tenant_id` + bases autorizadas à skill (front-matter `bases_rag` §7.1). Degrada
SUAVE: hub de embeddings fora/degradado (§10.6) → lista vazia (o agente continua —
com `exige_evidencia: true` a skill responde "não sei" em vez de inventar; RAG nunca
derruba o caminho do agente nem vira 500).
"""

import logging
from collections.abc import Sequence

from application.ports.embedding import EmbeddingPort
from application.ports.llm import LLMIndisponivel
from application.ports.repositorio_evidencia import RepositorioEvidencia
from domain.agentes.modelos import AgenteEvidence

logger = logging.getLogger(__name__)

TOP_K_PADRAO = 8  # §7.3: RAG top-k=8 filtrado por bases autorizadas


def evidencias_para_contexto(evidencias: Sequence[AgenteEvidence]) -> list[dict[str, str]]:
    """Formato citável no prompt (o SKILL.md pede citação da evidência por cláusula):
    id (rastreável no ledger `invocacao.evidencias`), base, ref e o trecho."""
    return [
        {"id": str(e.id), "base": e.base, "ref": e.ref or "", "trecho": e.chunk} for e in evidencias
    ]


class RetrieverService:
    def __init__(
        self,
        repositorio: RepositorioEvidencia,
        embedding: EmbeddingPort,
        *,
        top_k: int = TOP_K_PADRAO,
    ) -> None:
        self._repo = repositorio
        self._embedding = embedding
        self._top_k = top_k

    def buscar(
        self, tenant_id: str, consulta: str, *, bases: Sequence[str]
    ) -> list[AgenteEvidence]:
        """Top-k evidências para a consulta, só nas `bases` autorizadas do tenant.
        Sem base autorizada, consulta vazia ou hub degradado → [] (degrade suave)."""
        if not bases or not consulta.strip():
            return []
        if not self._embedding.disponivel():
            logger.warning("RAG pulado: embeddings em modo degradado (§10.6)")
            return []
        try:
            vetor = self._embedding.embed([consulta.strip()])[0]
        except LLMIndisponivel as exc:  # EmbeddingIndisponivel herda (§10.6)
            logger.warning("RAG pulado: hub de embeddings indisponível (%s)", exc)
            return []
        semanticas = self._repo.buscar_evidencias(tenant_id, list(bases), vetor, self._top_k)
        return self._com_pinadas(tenant_id, bases, semanticas)

    def _com_pinadas(
        self, tenant_id: str, bases: Sequence[str], semanticas: list[AgenteEvidence]
    ) -> list[AgenteEvidence]:
        """Evidências `meta.sempre_incluir` entram SEMPRE, à frente do top-k.

        O Guard determinístico exige em TODA segmentação as 7 listas de supressão e o
        opt-in por canal — evidência obrigatória não pode depender de sorte semântica:
        na VPS, "público pós-pago 5G com ARPU alto" trazia só colunas de plano e o
        Engineer recusava por falta de evidência de compliance (achado A24), embora as
        entradas existissem na base. Dedup por id preserva a ordem do top-k."""
        pinadas: list[AgenteEvidence] = []
        for base in bases:
            for evidencia in self._repo.listar_evidencias(tenant_id, base):
                if (evidencia.meta or {}).get("sempre_incluir"):
                    pinadas.append(evidencia)
        if not pinadas:
            return semanticas
        vistos = {e.id for e in pinadas}
        return pinadas + [e for e in semanticas if e.id not in vistos]
