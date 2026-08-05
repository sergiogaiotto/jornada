"""Transições legais de fase da OS + portão de pendências (§8-M1).

Regra: o ciclo de vida é linear (§1.1: pensada → discutida → criada → avaliada →
configurada → disparada → monitorada → encerrada); a única transição legal é avançar
exatamente UMA fase. Pendência `aberta` e `bloqueante` trava o avanço (gate §2.3);
`bloqueia_etapa` restringe o bloqueio à fase-alvo indicada (None = bloqueia qualquer avanço).
"""

from domain.campanha.erros import AvancoBloqueadoPorPendencia, TransicaoIlegal
from domain.campanha.modelos import FASES, Pendencia


def fase_seguinte(fase_atual: str) -> str | None:
    """Próxima fase do ciclo linear; None se `fase_atual` é terminal (encerrada)."""
    indice = FASES.index(fase_atual)
    return FASES[indice + 1] if indice + 1 < len(FASES) else None


def validar_transicao(fase_atual: str, fase_destino: str) -> None:
    """Só transições legais (§8-M1) — levanta TransicaoIlegal caso contrário."""
    if fase_destino not in FASES:
        raise TransicaoIlegal(f"Fase desconhecida: {fase_destino!r} (§4.1).")
    seguinte = fase_seguinte(fase_atual)
    if seguinte is None:
        raise TransicaoIlegal(f"OS em fase terminal {fase_atual!r} não admite transição.")
    if fase_destino != seguinte:
        raise TransicaoIlegal(
            f"Transição ilegal {fase_atual!r} → {fase_destino!r}; "
            f"a única transição legal a partir de {fase_atual!r} é {seguinte!r}."
        )


def pendencias_bloqueando(pendencias: list[Pendencia], fase_destino: str) -> list[Pendencia]:
    """Pendências que travam o avanço para `fase_destino` (abertas + bloqueantes)."""
    return [
        p
        for p in pendencias
        if p.status == "aberta"
        and p.bloqueante
        and (p.bloqueia_etapa is None or p.bloqueia_etapa == fase_destino)
    ]


def validar_portao_pendencias(pendencias: list[Pendencia], fase_destino: str) -> None:
    """Portão checado no POST /os/{id}/fase — levanta AvancoBloqueadoPorPendencia (409, A1)."""
    bloqueando = pendencias_bloqueando(pendencias, fase_destino)
    if bloqueando:
        resumo = "; ".join(f"#{p.numero} {p.titulo}" for p in bloqueando)
        raise AvancoBloqueadoPorPendencia(
            f"Avanço para {fase_destino!r} bloqueado por pendência(s) bloqueante(s) "
            f"aberta(s): {resumo}.",
            bloqueando,
        )
