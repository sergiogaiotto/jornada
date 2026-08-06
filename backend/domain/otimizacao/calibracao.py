"""Calibração de priors (§8-M11 CalibrateService) — CÓDIGO PURO, zero LLM (§10.6:
o agente calibrate §7.2 só NARRA; ajuste e backtest são determinísticos).

Compara previsto × realizado (conversões ENS) por OS e deriva a razão global
realizado/previsto (clampada), propondo priors novos ao escalar as taxas de conversão
(`canais[*].conversao` e `conversao_organica`) do prior vigente.

O `previsto` de cada caso NÃO é o P50 cru do snapshot: é o P50 congelado
RE-PREVISTO sob os priors VIGENTES (`fator_conversao`/`escala_entre` — conversões são
lineares na taxa §6). Sem isso o backtest compara sempre a mesma régua congelada e
"melhora" vira aritmética garantida: publicar N vezes compõe a razão e destrói os
priors do tenant (UAT5 achado 4 — email.conversao 0,032 → 0,000125 em três cliques).

Backtest OBRIGATÓRIO (§8-M11): re-prevê cada caso com a razão proposta e exige ganho
MÍNIMO de MAPE (`MELHORA_MINIMA`) e piso de `score` (`SCORE_MINIMO`) — assim a segunda
publicação idêntica REPROVA (razão ≈ 1,0 ⇒ ganho zero) em vez de compor.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

RAZAO_MIN, RAZAO_MAX = 0.25, 4.0  # calibração nunca extrapola 4x numa rodada
TAXA_MIN, TAXA_MAX = 1e-6, 0.95  # taxas de conversão permanecem probabilidades
MELHORA_MINIMA = 0.01  # ganho mínimo de MAPE (1 p.p.) — razão ≈ 1,0 não publica
SCORE_MINIMO = 0.05  # piso: MAPE novo > 95% não vira prior vigente (UAT5 achado 4)


def razao_calibracao(casos: list[dict[str, Any]]) -> float:
    """Razão global Σrealizado/Σprevisto dos casos, clampada em [0.25, 4.0].

    `previsto` já vem RE-PREVISTO sob os priors vigentes (ver docstring do módulo):
    com os priors calibrados, a razão converge para 1,0 — e 1,0 não publica.
    """
    previsto = sum(float(c["previsto"]) for c in casos)
    realizado = sum(float(c["realizado"]) for c in casos)
    if previsto <= 0:
        return 1.0
    return round(min(RAZAO_MAX, max(RAZAO_MIN, realizado / previsto)), 6)


def fator_conversao(priors: dict[str, Any]) -> float:
    """Escala agregada das taxas que `propor_priors` mexe (canais + orgânica).

    Média simples — `propor_priors` multiplica TODAS pelo mesmo fator, então a média
    é proporcional a qualquer uma delas e serve de régua entre versões de prior.
    """
    taxas = [float(d.get("conversao", 0.0)) for d in (priors.get("canais") or {}).values()]
    if "conversao_organica" in priors:
        taxas.append(float(priors["conversao_organica"]))
    return sum(taxas) / len(taxas) if taxas else 0.0


def escala_entre(novos: dict[str, Any], base: dict[str, Any]) -> float:
    """Quanto o prior `novos` escala as conversões em relação a `base`.

    Usada para RE-PREVER o P50 congelado (calculado sob `base`) sob os priors
    vigentes, sem rodar o motor (§6: conversões são lineares na taxa de conversão).
    Aproximação: se alguma taxa saturou em TAXA_MIN/TAXA_MAX o fator deixa de ser
    exatamente uniforme — a direção do ajuste continua correta.
    """
    denominador = fator_conversao(base)
    if denominador <= 0:
        return 1.0
    return round(fator_conversao(novos) / denominador, 9)


def propor_priors(atuais: dict[str, Any], razao: float, versao_nova: int) -> dict[str, Any]:
    """Priors novos = vigentes com taxas de conversão escaladas pela razão (clampadas).

    Deep-copy via json (priors são jsonb §4.1); demais chaves preservadas — o motor
    (§6) não muda: "o serviço passa a preferi-los sem tocar o motor" (priors.py).
    """
    novos: dict[str, Any] = json.loads(json.dumps(atuais))
    for dados in (novos.get("canais") or {}).values():
        dados["conversao"] = _clamp_taxa(float(dados.get("conversao", 0.0)) * razao)
    if "conversao_organica" in novos:
        novos["conversao_organica"] = _clamp_taxa(float(novos["conversao_organica"]) * razao)
    novos["versao"] = versao_nova
    novos["origem"] = "calibracao"
    novos["razao_aplicada"] = razao
    return novos


def priors_de_rollback(alvo: dict[str, Any], versao_nova: int) -> dict[str, Any]:
    """Priors de uma versão anterior republicados como versão NOVA (append-only §4.1).

    Rollback não apaga histórico: recria as taxas EXATAS da versão alvo numa versão
    nova, para o simulador (§6, que sempre prefere a última publicada) voltar à régua
    boa — inclusive a v1 `PRIORS_DEFAULT`, mesmo com N versões publicadas por cima.
    """
    novos: dict[str, Any] = json.loads(json.dumps(alvo))
    versao_alvo = int(alvo.get("versao", 1))
    novos["versao"] = versao_nova
    novos["origem"] = "rollback"
    novos["rollback_de"] = versao_alvo
    novos.pop("razao_aplicada", None)  # rollback não aplica razão nenhuma
    return novos


def assinatura_calibracao(razao: float, casos: list[dict[str, Any]]) -> str:
    """Impressão digital AUDITÁVEL da rodada: razão + conjunto de casos (OS, P50
    congelado, realizado). Vai no `backtest` gravado — permite provar depois QUE dados
    geraram aquela versão de prior."""
    corpo = json.dumps(
        {
            "razao": razao,
            "casos": sorted(
                [
                    [
                        str(c.get("os")),
                        round(float(c.get("previsto_congelado", c["previsto"])), 6),
                        round(float(c["realizado"]), 6),
                    ]
                    for c in casos
                ]
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(corpo.encode()).hexdigest()


def taxas_de_conversao(priors: dict[str, Any]) -> dict[str, float]:
    """Só o que a calibração mexe: `canais[*].conversao` + `conversao_organica`.

    É a identidade material de um prior — duas versões com estas taxas iguais são a
    MESMA régua para o simulador (§6), por mais que difiram em `versao`/`origem`.
    """
    taxas = {
        f"canal:{canal}": _clamp_taxa(float(dados.get("conversao", 0.0)))
        for canal, dados in (priors.get("canais") or {}).items()
    }
    if "conversao_organica" in priors:
        taxas["organica"] = _clamp_taxa(float(priors["conversao_organica"]))
    return taxas


def mesma_regua(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Priors materialmente idênticos (mesmas taxas de conversão) — publicar de novo
    não muda NADA para o simulador; a rodada é idempotente e vira 409 (UAT5 achado 4:
    o clique repetido publicava versão nova a cada vez, compondo a razão)."""
    return taxas_de_conversao(a) == taxas_de_conversao(b)


def backtest(casos: list[dict[str, Any]], razao: float) -> dict[str, Any]:
    """Backtest obrigatório (§8-M11): erro relativo por caso, antes × depois da razão.

    MAPE sobre max(realizado, 1) — determinístico e defensivo contra divisão por zero.
    `score` numeric(4,2) = max(0, 1 − mape_novo) saturado em [0, 1] (1.0 = previsão
    calibrada perfeita). `melhora` exige DUAS coisas (UAT5 achado 4): ganho de MAPE
    ≥ MELHORA_MINIMA (razão ≈ 1,0 não publica) e `score` ≥ SCORE_MINIMO (previsão
    ainda absurda não vira prior vigente). `motivo` explica a reprovação.
    """
    detalhes: list[dict[str, Any]] = []
    erros_antigos: list[float] = []
    erros_novos: list[float] = []
    for caso in casos:
        previsto = float(caso["previsto"])
        realizado = float(caso["realizado"])
        base = max(realizado, 1.0)
        erro_antigo = abs(previsto - realizado) / base
        erro_novo = abs(previsto * razao - realizado) / base
        erros_antigos.append(erro_antigo)
        erros_novos.append(erro_novo)
        detalhes.append(
            {
                "os": caso.get("os"),
                "previsto": round(previsto, 2),  # P50 RE-PREVISTO sob os priors vigentes
                "previsto_congelado": round(
                    float(caso.get("previsto_congelado", previsto)), 2
                ),  # P50 cru do snapshot do launch (régua do monitor §8-M10)
                "previsto_calibrado": round(previsto * razao, 2),
                "realizado": realizado,
                "erro_antigo": round(erro_antigo, 4),
                "erro_novo": round(erro_novo, 4),
            }
        )
    mape_antigo = round(sum(erros_antigos) / len(erros_antigos), 4)
    mape_novo = round(sum(erros_novos) / len(erros_novos), 4)
    ganho = round(mape_antigo - mape_novo, 4)
    score = round(min(1.0, max(0.0, 1.0 - mape_novo)), 2)
    motivo = _motivo_reprovacao(ganho, score)
    return {
        "casos": detalhes,
        "razao": razao,
        "mape_antigo": mape_antigo,
        "mape_novo": mape_novo,
        "ganho": ganho,
        "melhora": motivo is None,
        "score": score,
        "motivo": motivo,
        "assinatura": assinatura_calibracao(razao, casos),
    }


def _motivo_reprovacao(ganho: float, score: float) -> str | None:
    if ganho < MELHORA_MINIMA:
        return (
            f"ganho de MAPE {ganho} < mínimo {MELHORA_MINIMA} — a razão proposta não "
            "melhora o erro sob os priors VIGENTES (nada a calibrar)"
        )
    if score < SCORE_MINIMO:
        return (
            f"score {score} < piso {SCORE_MINIMO} — mesmo calibrado o erro continua "
            "absurdo; corrija a régua (previsto congelado) antes de publicar priors"
        )
    return None


def _clamp_taxa(valor: float) -> float:
    return round(min(TAXA_MAX, max(TAXA_MIN, valor)), 6)
