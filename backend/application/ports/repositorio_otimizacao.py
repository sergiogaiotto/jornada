"""Porta de persistência do M11 · Otimização/Retro/Calibração (T15) —
`proposta_otimizacao`/`aprendizado` (tabelas auxiliares, migração 0009),
`experimento` (apuração §8-M11), `calibracao_prior` (§4.1), evidências RAG
(`agente_evidence` — stub de ingestão A3), leitura de jornada/segmento/snapshot/
telemetria (impacto pré-simulado, apuração e calibração) + ledger e outbox (§2.3).

Portas = Protocols Python (§2.1). `RepositorioOsMemoria` implementa esta porta E as
demais (mesma instância por app — tipagem estrutural).
"""

import uuid
from typing import Protocol

from domain.agentes.modelos import AgenteEvidence, Invocacao
from domain.audiencia.modelos import Segmento
from domain.campanha.modelos import OS, EventoDominio
from domain.experimento.modelos import Experimento
from domain.governanca.modelos import Snapshot
from domain.jornada.modelos import JornadaVersao
from domain.lancamento.modelos import TelemetryEvent
from domain.otimizacao.modelos import Aprendizado, CalibracaoPrior, PropostaOtimizacao


class RepositorioOtimizacao(Protocol):
    # --- OS (escopo de tenant §4.1; clone cria OS nova) ---
    def obter_os(self, tenant_id: str, os_id: uuid.UUID) -> OS | None: ...

    def obter_os_por_codigo(self, codigo: str) -> OS | None: ...

    def listar_os(self, tenant_id: str, limit: int, offset: int) -> list[OS]: ...

    def adicionar_os(self, os_: OS) -> None: ...

    def proximo_sequencial_os(self, ano: int) -> int: ...

    # --- Twin (`jornada_versao` §4.1 — base das propostas; aprovar gera versão nova) ---
    def obter_jornada(self, jornada_id: uuid.UUID) -> JornadaVersao | None: ...

    def listar_jornadas(self, os_id: uuid.UUID) -> list[JornadaVersao]: ...

    def adicionar_jornada(self, jornada: JornadaVersao) -> None: ...

    def proxima_versao(self, os_id: uuid.UUID) -> int: ...

    # --- Segmento (volume do taxímetro da versão nova — M7-A2) ---
    def listar_segmentos(self, os_id: uuid.UUID) -> list[Segmento]: ...

    # --- Experimento (apuração §8-M11: anti-peeking + lift IC95) ---
    def obter_experimento(self, experimento_id: uuid.UUID) -> Experimento | None: ...

    def experimento_da_os(self, os_id: uuid.UUID) -> Experimento | None: ...

    def salvar_experimento(self, experimento: Experimento) -> None: ...

    # --- Previsto congelado × realizado (calibração §8-M11) ---
    def listar_snapshots(self, os_id: uuid.UUID) -> list[Snapshot]: ...

    def listar_telemetria(
        self, os_id: uuid.UUID, apos_id: int | None = None
    ) -> list[TelemetryEvent]: ...

    # --- Propostas do optimize (`proposta_otimizacao` — migração 0009) ---
    def adicionar_proposta(self, proposta: PropostaOtimizacao) -> None: ...

    def obter_proposta(self, proposta_id: uuid.UUID) -> PropostaOtimizacao | None: ...

    def listar_propostas(
        self, os_id: uuid.UUID, estado: str | None = None
    ) -> list[PropostaOtimizacao]: ...

    def salvar_proposta(self, proposta: PropostaOtimizacao) -> None: ...

    # --- Aprendizados (`aprendizado` — migração 0009; clone herda A3) ---
    def adicionar_aprendizado(self, aprendizado: Aprendizado) -> None: ...

    def listar_aprendizados(
        self, os_id: uuid.UUID | None = None, status: str | None = None
    ) -> list[Aprendizado]: ...

    # --- Priors versionados (`calibracao_prior` §4.1) ---
    def adicionar_calibracao(self, calibracao: CalibracaoPrior) -> None: ...

    def listar_calibracoes(
        self, tenant_id: str, tipo_campanha: str | None = None
    ) -> list[CalibracaoPrior]: ...

    # --- RAG (`agente_evidence` §4.1 — STUB de ingestão, embedding None §7.4) ---
    def adicionar_evidencia(self, evidencia: AgenteEvidence) -> None: ...

    def listar_evidencias(self, tenant_id: str, base: str) -> list[AgenteEvidence]: ...

    # --- Ledger via_ai (§4.1 `invocacao`) e outbox (§2.3) ---
    def adicionar_invocacao(self, invocacao: Invocacao) -> None: ...

    def adicionar_evento(self, evento: EventoDominio) -> None: ...

    def listar_eventos(
        self, os_id: uuid.UUID | None = None, tipo: str | None = None
    ) -> list[EventoDominio]: ...
