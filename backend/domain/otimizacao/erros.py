"""Erros do contexto otimização/retro/calibração (M11) — herdam o mapa HTTP do M1
(api/v1/os_governanca.py) e ganham traduções próprias no router do M11
(api/v1/otimizacao.py): ApuracaoAntesDaJanela→425 Too Early (anti-peeking, A1) ·
MotivoObrigatorio/SaidaDoOptimizeInvalida→422 · demais EstadoInvalido→409."""

from __future__ import annotations

from datetime import datetime

from domain.campanha.erros import ErroDominio, EstadoInvalido, JustificativaObrigatoria


class ApuracaoAntesDaJanela(ErroDominio):
    """A1 (§8-M11): apurar antes do fim da janela pré-registrada → 425 Too Early.

    Anti-peeking: NENHUM lift é calculado nem exposto antes de `fim_janela`.
    """

    def __init__(self, motivo: str, fim_janela: datetime | None = None) -> None:
        super().__init__(motivo)
        self.fim_janela = fim_janela


class ExperimentoJaApurado(EstadoInvalido):
    """Apuração é única (anti-p-hacking: o resultado registrado é imutável) — 409."""


class PropostaJaDecidida(EstadoInvalido):
    """Proposta já aprovada/rejeitada — decisão é de uso único (§1.1.3) — 409."""


class MotivoObrigatorio(JustificativaObrigatoria):
    """Rejeitar proposta EXIGE motivo (§8-M11: 'motivo vira sinal') — 422."""


class SaidaDoOptimizeInvalida(ErroDominio):
    """Agente optimize não devolveu proposta utilizável (guarda-corpo §1.3.5) — 422."""


class BacktestReprovado(EstadoInvalido):
    """§8-M11: backtest é OBRIGATÓRIO e precisa MELHORAR o erro para publicar — 409."""


class SemDadosParaCalibrar(EstadoInvalido):
    """Calibração exige previsto congelado × realizado de ao menos uma OS — 409."""
