"""Erros do domínio esteira — especializam a hierarquia de domain/campanha/erros.py.

Herdam de classes já mapeadas para HTTP no router (api/v1/os_governanca.py), portanto
nenhum mapa novo é necessário: DependenciaInsatisfeita/TransicaoEtapaIlegal→409
(EstadoInvalido) · ChecklistItemDesconhecido→404 (NaoEncontrado).
"""

from domain.campanha.erros import EstadoInvalido, NaoEncontrado


class DependenciaInsatisfeita(EstadoInvalido):
    """§8-M2-A2: etapa com dependência não concluída não vai a `em_andamento` (409)."""


class TransicaoEtapaIlegal(EstadoInvalido):
    """Mudança de estado fora do ciclo pendente→em_andamento→concluida (bloqueio à parte)."""


class ChecklistItemDesconhecido(NaoEncontrado):
    """Marcação de subtarefa inexistente no checklist da etapa."""
