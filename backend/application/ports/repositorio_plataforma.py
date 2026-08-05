"""RepositorioPlataforma — porta de persistência do M12 parte 2 (§2.1, §4.1:
`policy_versao`, `domain_event`, `invocacao`) + leituras de OS/segmento/snapshot/
launch para o relatório de policy drift (§8-M12) e do roster (§4.1 `agente`) para
resolver o nome do agente no detalhe de auditoria.

Implementada por `RepositorioOsMemoria` na MESMA instância das demais portas
(tipagem estrutural §2.1). `RepositorioPoliticas` é o subconjunto que o adapter de
publicações (GO §8-M4-A2) precisa: a política publicada ATUAL.
"""

import uuid
from typing import Protocol

from domain.agentes.modelos import Invocacao
from domain.atelie.modelos import Agente
from domain.audiencia.modelos import Segmento
from domain.campanha.modelos import OS, EventoDominio, Pendencia
from domain.governanca.modelos import PolicyVersao, Snapshot
from domain.lancamento.modelos import Launch


class RepositorioPoliticas(Protocol):
    def politica_publicada_atual(self, tenant_id: str | None = None) -> PolicyVersao | None:
        """Última `policy_versao` publicada (maior `versao`); None → fallback seed
        v1 do domínio (mesmos valores). `tenant_id=None` → dev single-tenant (§3),
        espelhando `versoes_skills_publicadas` (RepositorioAtelie)."""
        ...


class RepositorioPlataforma(RepositorioPoliticas, Protocol):
    # --- policy_versao (§4.1) ---
    def adicionar_policy(self, policy: PolicyVersao) -> None: ...

    def obter_policy(self, tenant_id: str, policy_id: uuid.UUID) -> PolicyVersao | None: ...

    def listar_policies(self, tenant_id: str) -> list[PolicyVersao]: ...

    def salvar_policy(self, policy: PolicyVersao) -> None: ...

    # --- auditoria (§8-M12: domain_event + ledger `invocacao` §4.1) ---
    def listar_eventos(
        self, os_id: uuid.UUID | None = None, tipo: str | None = None
    ) -> list[EventoDominio]: ...

    def adicionar_evento(self, evento: EventoDominio) -> None: ...

    def listar_invocacoes(self, tenant_id: str) -> list[Invocacao]: ...

    def obter_invocacao(self, invocacao_id: uuid.UUID) -> Invocacao | None: ...

    def listar_agentes(self, tenant_id: str) -> list[Agente]: ...

    # --- leituras do relatório de policy drift (OSs em voo §8-M12) ---
    def listar_os(self, tenant_id: str, limit: int, offset: int) -> list[OS]: ...

    def obter_os(self, tenant_id: str, os_id: uuid.UUID) -> OS | None: ...

    def listar_pendencias(self, os_id: uuid.UUID) -> list[Pendencia]:
        """Pendências da OS (dedupe das pendências de adequação por `origem`)."""
        ...

    def listar_segmentos(self, os_id: uuid.UUID) -> list[Segmento]: ...

    def listar_snapshots(self, os_id: uuid.UUID) -> list[Snapshot]: ...

    def listar_launches(self, snapshot_id: uuid.UUID) -> list[Launch]: ...
