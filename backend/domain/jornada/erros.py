"""Erros do contexto jornada — herdam o mapa HTTP do M1 (api/v1/os_governanca.py) e
ganham traduções específicas no router do M7 (api/v1/jornada.py):
GrafoInvalido→422 com `erros[{no, regra, mensagem}]` apontando o nó (A1/A3) ·
SaidaDoFlowInvalida→422 · EstadoInvalido (herdado)→409.
M9 (compilador §5.4, api/v1/compilador.py): GrafoNaoCompilavel→422 ·
SemPlanPrevio/AprovacaoNecessaria/CertificadoNecessario (EstadoInvalido)→409.
M9 fatia 2 (pré-voo/drift, api/v1/prevoo.py): PrevooReprovado/DriftJaResolvido
(EstadoInvalido)→409 · ExcecaoSemPrazo (JustificativaObrigatoria)→422.
"""

from __future__ import annotations

from typing import Any

from domain.campanha.erros import ErroDominio, EstadoInvalido, JustificativaObrigatoria


class GrafoInvalido(ErroDominio):
    """Validação §5.3 reprovou o grafo — `erros` aponta nó e regra bloqueante (A1)."""

    def __init__(self, erros: list[dict[str, Any]]) -> None:
        nos = sorted({str(e["no"]) for e in erros if e.get("no")})
        super().__init__(
            "Grafo JGC inválido (§5.3): "
            + " · ".join(str(e["mensagem"]) for e in erros)
            + (f" [nós: {', '.join(nos)}]" if nos else "")
        )
        self.erros = erros


class SaidaDoFlowInvalida(ErroDominio):
    """Agente flow não devolveu JGC utilizável (guarda-corpo §1.3.5: nada é inventado)."""


class GrafoNaoCompilavel(ErroDominio):
    """Nó `exception` presente (§5.2): não compila — bloqueia publish até resolução.

    `nos` aponta os nós de exceção (422 com apontamento, padrão do M7-A1).
    """

    def __init__(self, nos: list[str]) -> None:
        super().__init__(
            "Grafo não compilável (§5.2): nó(s) de exceção bloqueiam o publish até "
            f"resolução — [{', '.join(nos)}]."
        )
        self.nos = nos


class SemPlanPrevio(EstadoInvalido):
    """M9-A1: apply sem plan prévio para o snapshot/ambiente — 409."""


class AprovacaoNecessaria(EstadoInvalido):
    """Apply exige aprovação `aprovado|aprovado_ressalvas` válida (§5.4.4) — 409."""


class CertificadoNecessario(EstadoInvalido):
    """Apply exige certificado de elegibilidade VÁLIDO (M5-A3: expirado recusa) — 409."""


class OrcamentoEstourado(EstadoInvalido):
    """Orçamento `SFMC_API_BUDGET_PER_APPLY` excedido (§5.4.2) — dispara rollback."""


class PrevooReprovado(EstadoInvalido):
    """§8-M9: pré-voo com FAIL bloqueia apply; prod exige pré-voo executado (§5.4.4) — 409."""


class DriftJaResolvido(EstadoInvalido):
    """Drift check já resolvido (ou em sincronia — nada a resolver) — 409."""


class ExcecaoSemPrazo(JustificativaObrigatoria):
    """Resolução `excecao` de drift EXIGE prazo (§8-M9: 'excecao com prazo') — 422."""
