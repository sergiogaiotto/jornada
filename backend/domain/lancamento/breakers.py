"""Breakers determinísticos da Torre de Lançamento (§8-M10) — CÓDIGO PURO, ZERO LLM.

Caminho crítico (§10.6): breakers e kill NUNCA dependem de LLM — este módulo não
importa portas nem adapters; recebe telemetria, limites e lookups já resolvidos.

Breakers avaliados sobre a telemetria da janela (desde armar/última retomada):
- `optout`       — opt-outs / sents × 100 > `optout_pct_max` (A1: 0,6% na política);
- `bounce`       — bounces / sents × 100 > `bounce_pct_max`;
- `erro_entrega` — (sents − delivered) / sents × 100 > `erro_entrega_pct_max`,
  avaliado SÓ quando há telemetria de entrega (delivered > 0 — evita falso positivo
  por atraso do ENS);
- `burn_rate`    — custo realizado (Σ sents × tarifa do canal) / custo projetado
  pro-rata das ondas iniciadas > `burn_rate_max`;
- `disparo_lista_supressao` — sent para contato presente em QUALQUER das 7 listas
  (§4.1) ⇒ **SEV1 + kill automático** (A2).

Limite ausente nos `breakers` do launch ⇒ breaker não avaliado (política congelada
manda — §4.1 `launch.breakers`).

Telemetria dupla (M10 parte 2): taxas e burn-rate medem SÓ o fluxo ENS (tempo real);
eventos `fonte='extract'` são o batch de conciliação D-1 e NUNCA somam nas taxas
(dobrariam a contagem dos mesmos disparos). Exceção: o breaker de lista de supressão
varre os `sent` de TODAS as fontes — extract que revela disparo a contato suprimido
também mata (A2).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from domain.lancamento.modelos import TelemetryEvent

SEV_KILL = "sev1"  # disparo p/ lista de supressão (A2)
SEV_PAUSA = "sev2"  # demais breakers → pausado_breaker (A1)


def _pct(parte: int, total: int) -> float:
    return round(100.0 * parte / total, 4) if total else 0.0


def avaliar_breakers(
    *,
    eventos: list[TelemetryEvent],
    limites: dict[str, Any],
    listas_por_contato: dict[str, list[str]],
    custo_projetado_total: float | None,
    pct_acumulado: float,
    tarifas: dict[str, Decimal],
) -> list[dict[str, Any]]:
    """Veredito por código: lista de disparos [{breaker, valor, limite, sev, kill,
    detalhe}] — vazia quando nenhum limite foi violado.

    `listas_por_contato` = {contato_hash: [listas]} SÓ dos hashes suprimidos (o
    serviço resolve via porta); `pct_acumulado` = Σ pct das ondas já iniciadas
    (pro-rata do burn-rate); `custo_projetado_total` = custo congelado no snapshot
    (None/0 ⇒ burn-rate não avaliado).
    """
    disparos: list[dict[str, Any]] = []
    sents = [e for e in eventos if e.tipo == "sent"]  # TODAS as fontes — só p/ A2
    ens = [e for e in eventos if e.fonte != "extract"]  # taxas/burn: fluxo ENS
    sents_ens = [e for e in ens if e.tipo == "sent"]
    n_sent = len(sents_ens)
    n_delivered = sum(1 for e in ens if e.tipo == "delivered")
    n_bounce = sum(1 for e in ens if e.tipo == "bounce")
    n_optout = sum(1 for e in ens if e.tipo == "optout")

    # --- disparo p/ lista de supressão = SEV1 + kill automático (A2) ---
    suprimidos = sorted(
        {e.contato_hash for e in sents if e.contato_hash and listas_por_contato.get(e.contato_hash)}
    )
    if suprimidos:
        listas = sorted({lista for h in suprimidos for lista in listas_por_contato[h]})
        disparos.append(
            {
                "breaker": "disparo_lista_supressao",
                "valor": len(suprimidos),
                "limite": 0,
                "sev": SEV_KILL,
                "kill": True,
                "detalhe": (
                    f"{len(suprimidos)} contato(s) suprimido(s) receberam disparo "
                    f"(listas: {', '.join(listas)}) — SEV1 + kill automático (§8-M10-A2)."
                ),
                "contatos_hash": suprimidos,  # hash sha256 — NUNCA PII (§10.2)
                "listas": listas,
            }
        )

    # --- taxas sobre a onda corrente (sem sent ⇒ nada a medir) ---
    if n_sent:
        taxas = (
            ("optout", _pct(n_optout, n_sent), limites.get("optout_pct_max")),
            ("bounce", _pct(n_bounce, n_sent), limites.get("bounce_pct_max")),
            (
                "erro_entrega",
                _pct(n_sent - n_delivered, n_sent) if n_delivered else None,
                limites.get("erro_entrega_pct_max"),
            ),
        )
        for breaker, valor, limite in taxas:
            if valor is None or limite is None:
                continue
            if valor > float(limite):
                disparos.append(
                    {
                        "breaker": breaker,
                        "valor": valor,
                        "limite": float(limite),
                        "sev": SEV_PAUSA,
                        "kill": False,
                        "detalhe": (
                            f"Taxa de {breaker} {valor:.2f}% acima do limite "
                            f"{float(limite):.2f}% da política congelada (§8-M10)."
                        ),
                    }
                )

    # --- burn-rate vs projetado (pro-rata das ondas iniciadas) ---
    limite_burn = limites.get("burn_rate_max")
    projetado = (
        float(custo_projetado_total or 0.0) * pct_acumulado / 100.0
        if custo_projetado_total
        else 0.0
    )
    if limite_burn is not None and projetado > 0:
        realizado = float(
            sum((tarifas.get(e.canal or "", Decimal(0)) for e in sents_ens), Decimal(0))
        )
        burn = round(realizado / projetado, 4)
        if burn > float(limite_burn):
            disparos.append(
                {
                    "breaker": "burn_rate",
                    "valor": burn,
                    "limite": float(limite_burn),
                    "sev": SEV_PAUSA,
                    "kill": False,
                    "detalhe": (
                        f"Burn-rate {burn:.2f}× o custo projetado pro-rata "
                        f"(R$ {realizado:.2f} / R$ {projetado:.2f}) acima de "
                        f"{float(limite_burn):.2f}× (§8-M10)."
                    ),
                }
            )
    return disparos
