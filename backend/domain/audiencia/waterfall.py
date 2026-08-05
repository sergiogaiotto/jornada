"""Regras puras da audiência (§8-M5): waterfall, volume de abordagem, holdout, frescor.

Tudo DETERMINÍSTICO (sem I/O, sem LLM). Contagens vêm do read model de ativação
(dry-run — fixtures §11 em dev/teste) ou do relatório do Data Cloud (T5a):
{bruto, elegivel?, supressoes: {lista: n}, sem_opt_in, canais: {canal: {opt_in,
cap_excedente, quiet_impactados, colisoes}}, frescor: {fonte: {atualizado_ha_horas}}}.

Invariantes do §8-M5-A2: volume por canal ≤ líquido; percentuais SOBRE o líquido;
colisões vêm do governor (read model), nunca são inventadas aqui.
"""

from datetime import datetime, timedelta
from typing import Any

from domain.audiencia.erros import HoldoutForaDaPolitica
from domain.audiencia.modelos import CANAIS, SETE_LISTAS


def montar_waterfall(contagens: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
    """Waterfall §4.1 `[{etapa, corte, restante, motivo}]` a partir das contagens.

    Ordem: bruto → (critérios → elegível, quando houver) → 7 listas (precedência da
    política) → opt-in → líquido. Devolve (waterfall, bruto, liquido).
    """
    bruto = int(contagens.get("bruto", 0))
    restante = bruto
    etapas: list[dict[str, Any]] = []

    elegivel = contagens.get("elegivel")
    if elegivel is not None:  # Data Cloud: bruto → elegível pelos critérios do segmento
        corte = restante - int(elegivel)
        restante = int(elegivel)
        etapas.append(
            {
                "etapa": "criterios",
                "corte": corte,
                "restante": restante,
                "motivo": "fora dos critérios do segmento",
            }
        )

    supressoes = dict(contagens.get("supressoes") or {})
    for lista in SETE_LISTAS:
        corte = int(supressoes.get(lista, 0))
        restante -= corte
        etapas.append(
            {
                "etapa": lista,
                "corte": corte,
                "restante": restante,
                "motivo": f"lista de supressão {lista!r} (§4.1 lista_supressao)",
            }
        )

    corte = int(contagens.get("sem_opt_in", 0))
    restante -= corte
    etapas.append(
        {
            "etapa": "sem_opt_in",
            "corte": corte,
            "restante": restante,
            "motivo": "sem opt-in em nenhum canal",
        }
    )
    return etapas, bruto, restante


def suprimidos_por_lista(contagens: dict[str, Any]) -> dict[str, int]:
    """`certificado_elegibilidade.suprimidos` (§4.1): {lista: contagem} das 7 listas."""
    supressoes = dict(contagens.get("supressoes") or {})
    return {lista: int(supressoes.get(lista, 0)) for lista in SETE_LISTAS}


def volume_de_abordagem(liquido: int, canais: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Volume de abordagem por canal PÓS caps/quiet hours/colisões (§8-M5-A2).

    `canais` = {canal: {opt_in, cap_excedente, quiet_impactados, colisoes}} do read
    model/governor. Invariantes: 0 ≤ n ≤ líquido; pct calculado SOBRE o líquido.
    """
    volume: dict[str, dict[str, Any]] = {}
    for canal in CANAIS:
        insumos = dict(canais.get(canal) or {})
        base = min(int(insumos.get("opt_in", 0)), liquido)
        n = (
            base
            - int(insumos.get("cap_excedente", 0))  # acima do frequency cap da política
            - int(insumos.get("quiet_impactados", 0))  # inalcançáveis fora das quiet hours
            - int(insumos.get("colisoes", 0))  # colisões cross-campanha (governor)
        )
        n = max(0, min(n, liquido))
        pct = round(100.0 * n / liquido, 1) if liquido > 0 else 0.0
        volume[canal] = {"n": n, "pct": pct}
    return volume


def colisoes_por_canal(canais: dict[str, Any]) -> dict[str, int]:
    """Colisões do governor por canal (§8-M5-A2: 'colisões vêm do governor')."""
    return {canal: int(dict(canais.get(canal) or {}).get("colisoes", 0)) for canal in CANAIS}


def frescor_por_fonte(frescor: dict[str, Any], agora: datetime) -> dict[str, str]:
    """`segmento.frescor` §4.1 — {fonte: ultima_atualizacao} (§8-M5-A4).

    Fixtures usam frescor RELATIVO (`atualizado_ha_horas` — Hybris D-1 = 24h) para
    checagem determinística; aqui vira timestamp absoluto ISO-8601.
    """
    resultado: dict[str, str] = {}
    for fonte, dados in dict(frescor or {}).items():
        horas = float(dict(dados).get("atualizado_ha_horas", 0.0))
        resultado[fonte] = (agora - timedelta(hours=horas)).isoformat()
    return resultado


def validar_holdout(pct: float, holdout_min: float) -> None:
    """PUT /segmentos/{id}/holdout — respeita `holdout_min` da política publicada."""
    if pct < holdout_min or pct >= 100.0:
        raise HoldoutForaDaPolitica(
            f"holdout_pct={pct:g} viola a política publicada "
            f"(mínimo {holdout_min:g}%, máximo <100% — §4.1 policy_versao.holdout_min)."
        )
