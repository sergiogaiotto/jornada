"""Personas sintéticas de AGREGADOS (§6) — CÓDIGO PURO, zero I/O.

Contrato LGPD do §6: personas são amostradas de agregados do read model — JAMAIS
registros individuais em prompt/log. Aqui só entram contagens/percentuais (mix de
classes de frequência do governor, distribuição de horários) + jitter amostrado do
`GeradorAleatorio` com a seed do run — mesma seed ⇒ mesmas coortes (M8-A1).
"""

from typing import Any

from domain.simulacao.tipos import GeradorAleatorio

CLASSES_FREQUENCIA: tuple[str, ...] = ("saturado", "ok", "sub")  # frequencySplit §5.2

_JITTER_PESO = 0.02  # desvio do mix de classes entre runs (agregado, não indivíduo)


def gerar_personas(
    *,
    n: int,
    priors: dict[str, Any],
    ger: GeradorAleatorio,
    volume_abordagem: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Coortes agregadas de N personas: mix de classes (governor) + horários (STO).

    `volume_abordagem` (§4.1 segmento) documenta a origem agregada; as classes vêm dos
    priors com jitter por run — nunca de registros individuais (§6).
    """
    base = priors["classes_frequencia"]
    mult = priors["mult_classe"]
    pesos: dict[str, float] = {}
    for classe in CLASSES_FREQUENCIA:
        pesos[classe] = max(0.01, ger.normal(float(base[classe]), _JITTER_PESO))
    total = sum(pesos.values())
    coortes = [
        {
            "classe": classe,
            "peso": round(pesos[classe] / total, 6),
            "mult_conversao": float(mult[classe]),
        }
        for classe in CLASSES_FREQUENCIA
    ]
    mult_medio = sum(c["peso"] * c["mult_conversao"] for c in coortes)
    return {
        "n": n,
        "coortes": coortes,
        "mult_conversao_medio": round(mult_medio, 6),
        "horarios": {
            "pico": float(priors["hora_pico"]),
            "desvio": float(priors["desvio_horas"]),
        },
        "fonte": (
            "agregados do read model (volume_abordagem/priors) — sem registros individuais (§6)"
        ),
        "canais_abordagem": sorted((volume_abordagem or {}).keys()),
    }
