"""Erros do contexto Ateliê (M12) — herdam o mapa HTTP do M1 (api/v1/os_governanca.py)
e ganham traduções próprias no router do M12 (api/v1/atelie.py):
SkillMdInvalido→422 (com a lista `erros` do parser §7.1) · demais EstadoInvalido/
CodigoDuplicado→409 · NaoEncontrado→404."""

from __future__ import annotations

from domain.campanha.erros import CodigoDuplicado, ErroDominio, EstadoInvalido


class SkillMdInvalido(ErroDominio):
    """SKILL.md fora do canônico §7.1 — 422 com a lista de erros do parser."""

    def __init__(self, motivo: str, erros: list[str] | None = None) -> None:
        super().__init__(motivo)
        self.erros = erros or []


class AgenteDuplicado(CodigoDuplicado):
    """`agente.nome` é unique (§4.1) — 409."""


class VersaoDuplicada(CodigoDuplicado):
    """unique(agente_id, versao) em `skill_versao` (§4.1) — 409."""


class EstadoSkillInvalido(EstadoInvalido):
    """Operação fora do ciclo draft→em_revisao→publicada (§8-M12) — 409."""


class SemCasosGolden(EstadoInvalido):
    """Harness sem golden dataset (`harness_case` §4.1; seeds §11.4) — 409."""


class HarnessNaoAprovado(EstadoInvalido):
    """Portão de publicação (§8-M12-A1): sem harness_run VERDE (passou com score ≥ 90
    por dimensão §7.1) sobre o skill_md ATUAL → 409."""
