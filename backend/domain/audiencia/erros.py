"""Erros do contexto audiência — herdam a base do M1 para reusar o mapa RFC-7807.

Mapa (api/v1/audiencia.py): SaidaDoEngineerInvalida/HoldoutForaDaPolitica/
CertificadoReprovado→422 (tratados no route_class, com extras no corpo) ·
SegmentoSemSql/CertificadoExpirado herdam EstadoInvalido→409 (mapa do M1).
"""

from __future__ import annotations

from domain.campanha.erros import ErroDominio, EstadoInvalido


class SaidaDoEngineerInvalida(ErroDominio):
    """Saída do LLM sem SQL utilizável (ou sem evidências com `exige_evidencia`) —
    guarda-corpo determinístico do agente engineer (§1.3.5): nada é inventado."""


class HoldoutForaDaPolitica(ErroDominio):
    """PUT holdout abaixo do `holdout_min` da política publicada (§4.1 policy_versao)."""


class SegmentoSemSql(EstadoInvalido):
    """Operação que exige `sql_publico` num segmento sem SQL (origem/estado incompatível)."""


class CertificadoReprovado(ErroDominio):
    """Veredito do Guard determinístico (§8-M5-A1): SQL sem as 7 listas/opt-in no WHERE.

    Carrega `listas_faltantes` e `problemas` para o corpo do problem+json (422).
    """

    def __init__(self, motivo: str, listas_faltantes: list[str], problemas: list[str]) -> None:
        super().__init__(motivo)
        self.listas_faltantes = listas_faltantes
        self.problemas = problemas


class CertificadoExpirado(EstadoInvalido):
    """Certificado fora da validade (§8-M5-A3) — publish (M8/M9) recusa via helper
    `agents.guard.elegibilidade.exigir_certificado_vigente`."""
