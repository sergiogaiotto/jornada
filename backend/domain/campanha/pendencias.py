"""Ciclo de vida da pendência: aberta → resolvida | aceita (§4.1, §8-M1).

Aceite (A2): exige o usuário `accountable` da pendência + justificativa; grava
`aceite = {por, em, justificativa}`. Sem accountable definido não há aceite possível
(o caminho é resolver). Não há override de admin: segregação server-side (§10.5).
"""

import uuid
from datetime import datetime

from domain.campanha.erros import (
    AcaoNaoPermitida,
    EstadoInvalido,
    JustificativaObrigatoria,
)
from domain.campanha.modelos import Pendencia


def _exigir_aberta(pendencia: Pendencia) -> None:
    if pendencia.status != "aberta":
        raise EstadoInvalido(
            f"Pendência #{pendencia.numero} não está aberta (status={pendencia.status!r})."
        )


def resolver(pendencia: Pendencia) -> None:
    """aberta → resolvida (o fato que a originou foi tratado)."""
    _exigir_aberta(pendencia)
    pendencia.status = "resolvida"


def aceitar(pendencia: Pendencia, por: uuid.UUID, justificativa: str, em: datetime) -> None:
    """aberta → aceita — risco assumido conscientemente pelo accountable (§8-M1-A2)."""
    _exigir_aberta(pendencia)
    if not justificativa or not justificativa.strip():
        raise JustificativaObrigatoria("Aceite de pendência exige justificativa (§8-M1-A2).")
    if pendencia.accountable is None:
        raise AcaoNaoPermitida(
            f"Pendência #{pendencia.numero} não tem accountable definido; "
            "aceite indisponível — resolva a pendência."
        )
    if por != pendencia.accountable:
        raise AcaoNaoPermitida("Somente o accountable da pendência pode aceitá-la (§8-M1-A2).")
    pendencia.status = "aceita"
    pendencia.aceite = {
        "por": str(por),
        "em": em.isoformat(),
        "justificativa": justificativa.strip(),
    }
