"""Adapter do TracerPort — Langfuse self-hosted (§10.8), fire-and-forget.

`LANGFUSE_ENABLED=false` → no-op absoluto (nenhum import do SDK, nenhuma rede) — modo
usado em TODO teste. Habilitado, o envio ocorre em thread daemon com exceções engolidas:
queda do Langfuse NUNCA bloqueia nem quebra a aplicação (§10.8). Import do SDK é lazy.

PII (§10.2 — frente 3 do UAT #5): o Langfuse é um sistema EXTERNO à aplicação; o que sai
por aqui sai do perímetro. Hoje os chamadores mandam só identificadores e métricas
(tenant, os_id, nome do agente, versão da skill, latência), mas isso é CONVENÇÃO, e
convenção não é controle: bastava um `spans=[{"pergunta": pergunta}]` num serviço novo
para o dado mascarado no prompt sair em claro no trace. O sanitizador roda AQUI, na
saída do processo — último ponto antes da rede, e o único que nenhum chamador futuro
consegue esquecer. Custo: `mascarar_estrutura` é puro e não faz I/O; roda sobre
metadados/spans, que são pequenos por contrato.
"""

import threading
from typing import Any

from app.config import Settings
from domain.privacidade import mascarar_estrutura


class TracerLangfuse:
    """Implementa TracerPort. Trace com id = invocacao.id e spans nomeados (§10.8)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def trace(
        self,
        *,
        trace_id: str,
        nome: str,
        metadados: dict[str, Any],
        spans: list[dict[str, Any]],
    ) -> None:
        if not self._settings.langfuse_enabled:
            return  # no-op (§10.8): app nunca depende do Langfuse
        # §10.2: sanitiza ANTES de entregar à thread — o payload que atravessa a
        # fronteira do processo é o mascarado, e só ele. `trace_id` fica de fora de
        # propósito: é um UUID de invocação (chave de correlação com o ledger §4.1),
        # nunca texto do usuário.
        threading.Thread(
            target=self._enviar_seguro,
            kwargs={
                "trace_id": trace_id,
                "nome": mascarar_estrutura(nome),
                "metadados": mascarar_estrutura(metadados),
                "spans": mascarar_estrutura(spans),
            },
            daemon=True,  # fire-and-forget: nunca segura o processo
        ).start()

    # ------------------------------------------------------------------ interno
    def _enviar_seguro(self, **kwargs: Any) -> None:
        try:
            self._enviar(**kwargs)
        except Exception:  # noqa: BLE001 — contrato §10.8: falha de telemetria é silenciosa
            pass

    def _enviar(
        self,
        *,
        trace_id: str,
        nome: str,
        metadados: dict[str, Any],
        spans: list[dict[str, Any]],
    ) -> None:
        from langfuse import Langfuse  # lazy: jamais importado com LANGFUSE_ENABLED=false

        cliente = Langfuse(
            host=self._settings.langfuse_host,
            public_key=self._settings.langfuse_public_key,
            secret_key=self._settings.langfuse_secret_key,
        )
        trace = cliente.trace(id=trace_id, name=nome, metadata=metadados)
        for span in spans:
            trace.span(
                name=span.get("nome", "span"),
                metadata={k: v for k, v in span.items() if k != "nome"},
            )
        cliente.flush()
