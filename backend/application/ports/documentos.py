"""GeradorDocumentoPort — documento executivo (.docx) dos portões (§8-M4-A3, roster §7.2).

Porta = Protocol (§2.1). O adapter python-docx gera os bytes em memória de forma
DETERMINÍSTICA (sem LLM — o agente `doc` 20b poderá NARRAR por cima no futuro, mas o
documento do portão nunca depende de LLM: caminho crítico §10.6).
"""

from typing import Any, Protocol

from domain.campanha.modelos import OS, Pendencia
from domain.validacao.modelos import ValidacaoCampo


class GeradorDocumentoPort(Protocol):
    def documento_go(
        self,
        *,
        os_: OS,
        validacoes: list[ValidacaoCampo],
        pendencias: list[Pendencia],
        frozen: dict[str, Any],
    ) -> bytes:
        """Bytes do .docx executivo do portão GO (armazenado em `documento_portao`)."""
        ...

    def relatorio_segmento(self, *, relatorio: dict[str, Any]) -> bytes:
        """Bytes do .docx do relatório de segmento Data Cloud (§8-M5 `GET
        .../relatorio.docx`): funil, waterfall, sobreposição, volume por canal, frescor."""
        ...
