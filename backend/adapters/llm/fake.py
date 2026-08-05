"""Adapter FAKE do LLMPort — ÚNICO adapter de LLM permitido em teste (§1.3.5).

Devolve respostas enlatadas e registra as chamadas; nenhuma rede. Também serve ao
DEMO_MODE quando o hub não está acessível.
"""

from application.ports.llm import LLMIndisponivel, PerfilModelo


class LLMFake:
    """Implementa LLMPort; `resposta` fixa (ou por perfil, ou sequencial) e ledger.

    `respostas` (sequencial) serve aos testes do retry §7.3: cada `chat` consome a
    próxima da lista; esgotada a lista, a ÚLTIMA se repete (simula modelo teimoso).
    """

    def __init__(
        self,
        resposta: str = "resposta-fake",
        *,
        respostas: list[str] | None = None,
        respostas_por_perfil: dict[str, str] | None = None,
        disponivel: bool = True,
    ) -> None:
        self._resposta = resposta
        self._fila = list(respostas or [])
        self._por_perfil = respostas_por_perfil or {}
        self._disponivel = disponivel
        self.chamadas: list[dict[str, object]] = []

    def disponivel(self) -> bool:
        return self._disponivel

    def chat(self, mensagens: list[dict[str, str]], *, perfil: PerfilModelo = "20b") -> str:
        if not self._disponivel:
            raise LLMIndisponivel("LLMFake configurado como indisponível (simula §10.6).")
        self.chamadas.append({"perfil": perfil, "mensagens": mensagens})
        if self._fila:
            return self._fila.pop(0) if len(self._fila) > 1 else self._fila[0]
        return self._por_perfil.get(perfil, self._resposta)
