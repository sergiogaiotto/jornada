"""Política publicada v1 (seed §11.4 "políticas v1") — conteúdo no formato de
`policy_versao.conteudo` (§4.1): {frequency_cap, quiet_hours, blackout, holdout_min,
alcadas, retencao_dias, breakers, precedencia}.

Valores coerentes com o SDD: quiet hours 20:00–08:00 (§5.1), holdout default 10% (§4.1
`segmento.holdout_pct`), breaker de optout 0,6% (§8-M10-A1), 7 listas de supressão na
precedência (§4.1 `lista_supressao`). Vira linha de `policy_versao` quando o M12 chegar.
"""

from typing import Any


def faixa_alcada(custo: float, politica: dict[str, Any]) -> dict[str, Any] | None:
    """Faixa de alçada da política para o custo previsto (§8-M8: `enviar-alcada`).

    `alcadas` = [{ate, papel}] em faixas crescentes; retorna a PRIMEIRA faixa com
    custo ≤ `ate` (None quando o custo excede a maior — fora de alçada, 409).
    """
    faixas = sorted(politica.get("alcadas") or [], key=lambda f: float(f["ate"]))
    for faixa in faixas:
        if custo <= float(faixa["ate"]):
            return {"ate": faixa["ate"], "papel": faixa["papel"]}
    return None


POLITICA_PUBLICADA: dict[str, Any] = {
    "versao": 1,
    "estado": "publicada",
    "conteudo": {
        "frequency_cap": {"email": 4, "sms": 2, "push": 5, "whatsapp": 2, "janela_dias": 7},
        "quiet_hours": {"inicio": "20:00", "fim": "08:00"},
        "blackout": [],
        "holdout_min": 10.0,
        "alcadas": [{"ate": 100_000, "papel": "lider"}, {"ate": 1_000_000, "papel": "aprovador"}],
        "retencao_dias": 180,
        # Limites dos breakers da Torre de Lançamento (§8-M10; congelados em
        # `launch.breakers` no armar — §4.1). optout 0,6% = §8-M10-A1; erro de
        # entrega e burn-rate vs projetado completam o contrato do M10 (valores
        # v1 do seed — a política do tenant os governa via M12).
        "breakers": {
            "optout_pct_max": 0.6,
            "bounce_pct_max": 2.0,
            "erro_entrega_pct_max": 5.0,
            "burn_rate_max": 1.5,
        },
        "precedencia": [
            "blacklist",
            "fraude",
            "nao_perturbe",
            "optout",
            "procon",
            "inadimplente",
            "reprovado_credito",
        ],
    },
}
