"""SLA clock — máquina de estados correndo/pausado_cliente/bloqueado_pendencia/concluido (§4.1).

Semântica de pausa: tempo pausado/bloqueado NÃO conta contra o prazo — ao retomar,
o prazo é estendido pela duração da pausa; cada pausa fica registrada em
`pausas` como {de, ate, motivo} (ate=None enquanto aberta). A view de saúde (§4.1)
só considera clocks `correndo`, logo um clock pausado nunca põe a OS em risco.
Relógio SEMPRE injetado (`agora`) — domínio não lê o relógio do sistema (§2.1).
"""

from datetime import datetime

from domain.campanha.erros import EstadoInvalido
from domain.campanha.modelos import SlaClock


def _pausar(clock: SlaClock, estado_destino: str, agora: datetime, motivo: str) -> None:
    if clock.estado != "correndo":
        raise EstadoInvalido(
            f"Clock da etapa {clock.etapa!r} não está correndo (estado={clock.estado!r})."
        )
    clock.estado = estado_destino
    clock.pausas.append({"de": agora.isoformat(), "ate": None, "motivo": motivo})


def pausar_cliente(clock: SlaClock, agora: datetime, motivo: str = "aguardando cliente") -> None:
    """correndo → pausado_cliente."""
    _pausar(clock, "pausado_cliente", agora, motivo)


def bloquear_por_pendencia(clock: SlaClock, agora: datetime, motivo: str) -> None:
    """correndo → bloqueado_pendencia (pendência bloqueante aberta na OS)."""
    _pausar(clock, "bloqueado_pendencia", agora, motivo)


def retomar(clock: SlaClock, agora: datetime) -> None:
    """pausado_cliente|bloqueado_pendencia → correndo; prazo estendido pela pausa."""
    if clock.estado not in ("pausado_cliente", "bloqueado_pendencia"):
        raise EstadoInvalido(
            f"Clock da etapa {clock.etapa!r} não está pausado (estado={clock.estado!r})."
        )
    pausa = clock.pausas[-1]  # invariante: pausar sempre abre uma pausa
    inicio = datetime.fromisoformat(pausa["de"])
    pausa["ate"] = agora.isoformat()
    clock.prazo = clock.prazo + (agora - inicio)
    clock.estado = "correndo"


def concluir(clock: SlaClock, agora: datetime) -> None:
    """qualquer estado não-concluído → concluido (fecha pausa aberta, se houver)."""
    if clock.estado == "concluido":
        raise EstadoInvalido(f"Clock da etapa {clock.etapa!r} já está concluído.")
    if clock.pausas and clock.pausas[-1].get("ate") is None:
        clock.pausas[-1]["ate"] = agora.isoformat()
    clock.estado = "concluido"
