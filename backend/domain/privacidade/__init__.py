"""Contexto de domínio `privacidade` — guarda-corpos de LGPD que valem para TODA a
plataforma (SDD §10.2: PII nunca em prompt de LLM, log ou ledger).

Vive em `domain/` porque é REGRA, não infraestrutura: o mascaramento é puro,
determinístico e testável sem I/O — os serviços de aplicação apenas o aplicam na
fronteira de entrada do texto livre do usuário (emenda C02, CHANGELOG-SDD.md).
"""

from domain.privacidade.mascarar import contem_pii, mascarar_pii

__all__ = ["contem_pii", "mascarar_pii"]
