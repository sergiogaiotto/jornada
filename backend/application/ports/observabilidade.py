"""TracerPort — observabilidade de LLM via Langfuse (§10.8), atrás de porta (§2.1).

Contrato: `trace()` é FIRE-AND-FORGET — nunca bloqueia nem levanta exceção; queda do
Langfuse jamais afeta a aplicação (`LANGFUSE_ENABLED=false` → no-op). Toda chamada via
LLMPort gera um trace com `trace_id = invocacao.id` e metadados
{tenant, os_id, agente, skill_versao, modelo_perfil}; spans `rag_retrieve` → `generate`
→ `judge` (no M3 apenas `generate` existe). O ledger `invocacao` continua a fonte de
auditoria LGPD; Langfuse é a lente operacional.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TracerPort(Protocol):
    def trace(
        self,
        *,
        trace_id: str,
        nome: str,
        metadados: dict[str, Any],
        spans: list[dict[str, Any]],
    ) -> None:
        """Emite um trace (assíncrono, fire-and-forget). Nunca levanta exceção."""
        ...
