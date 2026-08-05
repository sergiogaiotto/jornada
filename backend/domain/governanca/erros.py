"""Erros do contexto governança (portões T9 + aprovação T10) — herdam o mapa HTTP do
M1 (`domain/campanha/erros.py`): NaoEncontrado→404 · EstadoInvalido→409. Exceções
próprias do router de portões/aprovação: LinkExpirado→410 Gone ·
HoldoutAbaixoDaPolitica/RessalvasObrigatorias→422 (mapeadas em api/v1/portoes.py)."""

from domain.campanha.erros import ErroDominio, EstadoInvalido, NaoEncontrado


class TokenInvalido(NaoEncontrado):
    """Token sem aprovação correspondente no tenant (404 — não vaza existência)."""


class LinkExpirado(ErroDominio):
    """Link mágico além de `expira_em` (A3) — 410 Gone (mapa do router de portões)."""


class LinkJaUtilizado(EstadoInvalido):
    """Uso único (A3): decisão já registrada neste link (409)."""


class AprovacaoInvalidada(EstadoInvalido):
    """A4: aprovação invalidada por variação de custo >10% — snapshot novo obrigatório."""


class ForaDeAlcada(EstadoInvalido):
    """Custo previsto acima da maior faixa de alçada da política (§11.4) — 409."""


class PreRequisitoAusente(EstadoInvalido):
    """Pré-requisito do fluxo M8 ausente (simulação/previsto congelado) — 409."""


class HoldoutAbaixoDaPolitica(ErroDominio):
    """Pré-registro com holdout_pct abaixo do `holdout_min` da política — 422."""


class RessalvasObrigatorias(ErroDominio):
    """`aprovado_ressalvas` exige ressalvas (e `aprovado` não as aceita) — 422."""


class PolicyInvalida(ErroDominio):
    """Conteúdo fora do formato `policy_versao.conteudo` §4.1 (M12 parte 2) —
    422 com a lista `erros` acumulada (padrão do parser §7.1)."""

    def __init__(self, motivo: str, erros: list[str] | None = None) -> None:
        super().__init__(motivo)
        self.erros = erros or []


class EstadoPolicyInvalido(EstadoInvalido):
    """Operação fora do ciclo draft→publicada da política (§8-M12) — 409."""
