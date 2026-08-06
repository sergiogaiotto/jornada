"""Contexto de domínio `privacidade` — guarda-corpos de LGPD que valem para TODA a
plataforma (SDD §10.2: PII nunca em prompt de LLM, log ou ledger).

Vive em `domain/` porque é REGRA, não infraestrutura: o mascaramento é puro,
determinístico e testável sem I/O — os serviços de aplicação apenas o aplicam na
fronteira de entrada do texto livre do usuário (emenda C02, CHANGELOG-SDD.md).

`mascarar_pii`/`contem_pii` valem para uma string; `mascarar_estrutura`/
`contem_pii_estrutura` (emenda D01 — achado 9 do UAT #5) estendem a MESMA regra a
árvores de dados: `conteudo` do pedido, `briefing` da OS, `payload` de evento do
outbox e `metadados`/`spans` do trace Langfuse.
"""

from domain.privacidade.mascarar import contem_pii, mascarar_pii
from domain.privacidade.sanitizar import (
    contem_pii_estrutura,
    mascarar_campos,
    mascarar_estrutura,
)

__all__ = [
    "contem_pii",
    "contem_pii_estrutura",
    "mascarar_campos",
    "mascarar_estrutura",
    "mascarar_pii",
]
