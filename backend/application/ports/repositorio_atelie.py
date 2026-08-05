"""RepositorioAtelie — porta de persistência do Ateliê M12 (§2.1, §4.1: `agente`,
`skill_versao`, `harness_case`, `harness_run`).

Implementada por `RepositorioOsMemoria` na MESMA instância das demais portas
(tipagem estrutural §2.1) — inclui `obter_os` (resolução de versão por OS: frozen §4.1)
e o outbox (§2.3).
"""

import uuid
from typing import Protocol

from domain.atelie.modelos import Agente, HarnessCase, HarnessRun, SkillVersao
from domain.campanha.modelos import OS, EventoDominio


class RepositorioAtelie(Protocol):
    # --- agente (§4.1) ---
    def adicionar_agente(self, agente: Agente) -> None: ...

    def obter_agente(self, tenant_id: str, agente_id: uuid.UUID) -> Agente | None: ...

    def obter_agente_por_nome(self, nome: str) -> Agente | None:
        """`agente.nome` é unique GLOBAL no DDL §4.1 (dev é single-tenant §3)."""
        ...

    def listar_agentes(self, tenant_id: str) -> list[Agente]: ...

    # --- skill_versao (§4.1) ---
    def adicionar_skill(self, skill: SkillVersao) -> None: ...

    def obter_skill(self, skill_id: uuid.UUID) -> SkillVersao | None: ...

    def listar_skills(self, agente_id: uuid.UUID) -> list[SkillVersao]: ...

    def salvar_skill(self, skill: SkillVersao) -> None: ...

    def versoes_skills_publicadas(self) -> dict[str, str]:
        """{agente.nome: versão publicada ATUAL} — última `publicada_em` por agente
        (fonte do GO §8-M4-A2 via PublicacoesPort; vazio antes das seeds)."""
        ...

    # --- harness (§4.1) ---
    def adicionar_harness_case(self, caso: HarnessCase) -> None: ...

    def listar_harness_cases(self, agente_id: uuid.UUID) -> list[HarnessCase]: ...

    def adicionar_harness_run(self, run: HarnessRun) -> None: ...

    def listar_harness_runs(self, skill_versao_id: uuid.UUID) -> list[HarnessRun]: ...

    # --- resolução por OS (frozen §4.1) e outbox (§2.3) ---
    def obter_os(self, tenant_id: str, os_id: uuid.UUID) -> OS | None: ...

    def adicionar_evento(self, evento: EventoDominio) -> None: ...
