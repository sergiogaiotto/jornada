"""Enforcement do `teto_tokens` (pedido (d) — J02, onda 6). PURO, sem I/O.

A régua do módulo (achado 8): o campo só existe na política porque ESTE enforcement
existe. A medição veio do I04 (`invocacao.tokens`, somado por linha, NULL quando o
provedor não manda usage); a soma do dia chega pronta ao portão (congelada uma vez por
requisição na fábrica `portao_ia.de`) e aqui só se compara e se recusa.

Limite DECLARADO (o mesmo texto vale na tela do DPO): o teto governa o gasto MEDIDO —
linha com tokens NULL contribui 0, porque ausência de medida não vira medida
(`soma_tokens`, ports/llm.py). Um tenant atrás de proxy que suprime usage tem teto
inaplicável NA PRÁTICA, e a tela diz isso em vez de fingir que não.
"""

from datetime import UTC, datetime
from typing import Any

from domain.ia_responsavel.erros import TetoDeTokensExcedido


def inicio_do_dia_utc(agora: datetime) -> datetime:
    """Virada do orçamento: meia-noite UTC do dia corrente (via ClockPort, §2.1 —
    nunca `datetime.now()`; é o que deixa o teste provar o reset avançando o relógio).
    Instante naive é tratado como UTC (o mesmo pressuposto do restante do ledger)."""
    aware = agora if agora.tzinfo is not None else agora.replace(tzinfo=UTC)
    return aware.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def teto_tokens_diario(conteudo: dict[str, Any]) -> int | None:
    """`teto_tokens.tokens_por_dia` da política vigente — None = sem teto (default e
    também o comportamento de toda política publicada antes do J02)."""
    bloco = conteudo.get("teto_tokens")
    if not isinstance(bloco, dict):
        return None
    valor = bloco.get("tokens_por_dia")
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        return None
    return valor


def exigir_dentro_do_teto(gasto_medido: int, conteudo: dict[str, Any]) -> None:
    """Recusa (TetoDeTokensExcedido → 429) quando o gasto do dia JÁ atingiu o teto.

    Gate-on-entry: `>=` e não `>` — quem chega com o orçamento consumido não inicia
    chamada nova; a chamada que começou abaixo do teto completa, porque o custo dela
    só é conhecido depois (o provedor devolve o usage na resposta)."""
    teto = teto_tokens_diario(conteudo)
    if teto is None:
        return
    if gasto_medido >= teto:
        raise TetoDeTokensExcedido(
            f"Teto de tokens do dia atingido: gasto medido {gasto_medido} >= teto "
            f"{teto} (teto_tokens.tokens_por_dia da política de IA Responsável). A "
            "chamada ao modelo NÃO foi feita; o orçamento reinicia na virada do dia "
            "(UTC) — ou o DPO publica um teto maior.",
            gasto=gasto_medido,
            teto=teto,
        )
