"""Erros do contexto lançamento — herdam o mapa HTTP do M1 (api/v1/os_governanca.py)
e ganham traduções específicas no router do M10 (api/v1/lancamento.py):
BreakerDisparado→409 com `disparos` no corpo · TelemetriaInvalida→422 ·
AprovadorRepetido (AcaoNaoPermitida)→403 · ApplyNecessario/LaunchJaAtivo/
LaunchNaoOperavel/ConfirmacaoInvalida (EstadoInvalido)→409.
"""

from __future__ import annotations

from typing import Any

from domain.campanha.erros import AcaoNaoPermitida, ErroDominio, EstadoInvalido


class ApplyNecessario(EstadoInvalido):
    """Armar exige apply ok do snapshot (§8-M10: 'exige apply ok') — 409."""


class LaunchJaAtivo(EstadoInvalido):
    """Snapshot já tem launch ativo (armado|em_rampa|pausado_breaker) — 409."""


class LaunchNaoOperavel(EstadoInvalido):
    """Operação incompatível com o estado do launch (ex.: avançar pausado/morto) — 409."""


class BreakerDisparado(EstadoInvalido):
    """Portão automático entre ondas (§8-M10): breaker disparou — o launch foi
    pausado (ou morto, se SEV1) AUTOMATICAMENTE; `disparos` vai no problem+json."""

    def __init__(self, disparos: list[dict[str, Any]], estado: str) -> None:
        nomes = ", ".join(str(d["breaker"]) for d in disparos)
        super().__init__(
            f"Breaker(s) disparado(s): {nomes} — launch {estado} automaticamente; "
            "retomar exige humano (§8-M10-A1)."
        )
        self.disparos = disparos
        self.estado = estado


class ConfirmacaoInvalida(EstadoInvalido):
    """Kill etapa 2: confirmação ausente/não corresponde à solicitação pendente — 409."""


class AprovadorRepetido(AcaoNaoPermitida):
    """Retomada SEV1 exige 2 aprovadores DISTINTOS (§8-M10; segregação §10.5) — 403."""


class PrevistoAusente(EstadoInvalido):
    """Monitor (§8-M10) exige snapshot com Previsto congelado — a régua do
    previsto×realizado (§1.1.2); OS sem snapshot/previsto — 409."""


class TelemetriaInvalida(ErroDominio):
    """Evento de telemetria fora do contrato (§4.1) ou com PII (§10.2) — 422."""


class ConsultaForaDaCamada(EstadoInvalido):
    """Defesa em profundidade da camada semântica (§7.2/§8-M10 parte 3): só consultas
    nomeadas `vw_metricas_*` do dicionário executam — nome/parâmetro fora ⇒ nada
    executa. O serviço RECUSA antes (recusa padrão 200); chegar aqui é 409."""
