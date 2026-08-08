"""Janela estruturada da oferta (J04 — liga o `wait_alem_da_janela` do §5.3).

O D04 registrou a limitação: a regra existia, testada, e NENHUM chamador de produção
passava `janela_oferta_dias` — a janela vivia como TEXTO LIVRE no campo obrigatório
`janela` do briefing ("01/07 a 15/08 (rampa canário…)"), e derivá-la por parser seria
inventar semântica (§1.3.5). A saída é estrutural: dois campos OPCIONAIS do briefing,
`janela_inicio` e `janela_fim` (ISO `YYYY-MM-DD`), entradas normais `{valor, inferido}`.

Doutrina de leitura (o precedente é o `_numero` do simulador para verba/ticket):
COERÇÃO TOLERANTE — campo ausente, não-parseável ou invertido (fim < início) devolve
None e a regra segue INERTE para aquela OS, exatamente como antes do J04. O campo
textual `janela` continua obrigatório para completude (M3) e vira display; quando os
dois convivem, a ESTRUTURADA governa a regra — nunca se deriva uma da outra.

Convenção de dias, fixada: `(fim - início).days` — "2026-07-01 a 2026-08-15" = 45.0
(a mesma régua float do `duracao_em_dias` do validador).
"""

from datetime import date
from typing import Any

from domain.intake.completude import valor_do_campo
from domain.intake.erros import CampoBriefingInvalido
from domain.intake.modelos import CAMPO_JANELA_FIM, CAMPO_JANELA_INICIO

CAMPOS_JANELA: tuple[str, ...] = (CAMPO_JANELA_INICIO, CAMPO_JANELA_FIM)


def parse_data_iso(valor: Any) -> date | None:
    """Data ISO `YYYY-MM-DD` a partir de valor cru — None quando não parseável.

    Fonte ÚNICA do que conta como janela válida: o consultor usa isto para DESCARTAR
    na fronteira o valor que não é ISO (auditoria da onda 6 — data BR '01/07/2026'
    seria gravada como presente-mas-inválida e a regra ficaria inerte em silêncio)."""
    if not isinstance(valor, str):
        return None
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        return None


def exigir_janela_iso(campo: str, valor: Any) -> None:
    """422 (J04) se `campo` é uma data estruturada da janela e `valor` NÃO é ISO
    `YYYY-MM-DD`. Fecha o caminho do editor humano (PATCH de campos/briefing) do mesmo
    jeito que `interpretar_saida` fecha o do consultor — o valor presente-mas-inválido
    (data BR, texto livre) deixa de ser gravado como limite inerte. Campo fora da
    janela: no-op."""
    if campo in CAMPOS_JANELA and parse_data_iso(valor) is None:
        raise CampoBriefingInvalido(
            f"{campo} deve ser data ISO YYYY-MM-DD (recebido {valor!r}); é o que liga a "
            "regra de wait × janela da oferta (§5.3). Ex.: 2026-07-01."
        )


def _data(briefing: dict[str, Any], campo: str) -> date | None:
    return parse_data_iso(valor_do_campo(briefing, campo))


def janela_oferta_dias(briefing: dict[str, Any] | None) -> float | None:
    """Dias da janela estruturada — None quando os campos não existem/não parseiam.

    None mantém o comportamento pré-J04 (regra inerte): briefing velho continua
    válido; o portão só passa a existir quando alguém DECLARA a janela."""
    if not isinstance(briefing, dict):
        return None
    inicio = _data(briefing, CAMPO_JANELA_INICIO)
    fim = _data(briefing, CAMPO_JANELA_FIM)
    if inicio is None or fim is None or fim < inicio:
        return None
    return float((fim - inicio).days)
