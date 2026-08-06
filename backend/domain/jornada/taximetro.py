"""Taxímetro (§8-M7-A2) — custo projetado = Σ(volume esperado × tarifa vigente).

CÓDIGO determinístico (roster §7.2 `cost`: "cálculo é código; LLM narra"): dinheiro em
Decimal, nunca float. Volume esperado por nó via propagação no grafo (premissa
documentada — o refinamento probabilístico é do simulador M8):

- entrySource recebe o volume líquido do segmento (contagem_liquida §4.1);
- randomSplit: braço recebe volume × pct/100 (aresta casada por `cond` = id do braço);
- decisionSplit/engagementSplit/frequencySplit: divisão IGUAL entre os braços
  (esperança neutra sem priors — priors chegam com o simulador §6);
- demais nós repassam o volume integral a cada saída;
- cada `channel.*` soma floor(volume) × tarifa_vigente(canal) — tarifa de
  `tarifa_canal` (§4.1; seed §11.4). Canal sem tarifa vigente → custo 0 + AVISO
  (nunca inventa tarifa — §1.3.5).

Processamento em ordem topológica (Kahn); ciclo (JGC deve ser DAG) → aviso e os nós
do ciclo ficam fora da conta.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from domain.jornada.adjacencia import saidas_do_grafo as _saidas

TIPOS_DIVISAO_IGUAL: tuple[str, ...] = ("decisionSplit", "engagementSplit", "frequencySplit")

_CEM = Decimal("100")
_CENTAVO = Decimal("0.01")


def _volumes_por_no(grafo: dict[str, Any], volume_entrada: int) -> tuple[dict[str, Decimal], bool]:
    """Propaga o volume esperado (Decimal) da entrada a cada nó; (volumes, houve_ciclo)."""
    nos: dict[str, dict[str, Any]] = {
        str(n["id"]): n for n in grafo.get("nodes") or [] if isinstance(n, dict) and n.get("id")
    }
    saidas = _saidas(grafo)
    grau_entrada: dict[str, int] = dict.fromkeys(nos, 0)
    for arestas in saidas.values():
        for aresta in arestas:
            destino = str(aresta["to"])
            if destino in grau_entrada:
                grau_entrada[destino] += 1

    volumes: dict[str, Decimal] = dict.fromkeys(nos, Decimal(0))
    for no_id, no in nos.items():
        if no.get("type") == "entrySource":
            volumes[no_id] = Decimal(volume_entrada)

    fila = [i for i, grau in grau_entrada.items() if grau == 0]
    processados = 0
    while fila:
        no_id = fila.pop()
        processados += 1
        no, volume = nos[no_id], volumes[no_id]
        arestas = [a for a in saidas.get(no_id, []) if str(a["to"]) in nos]
        for aresta in arestas:
            destino = str(aresta["to"])
            if no.get("type") == "randomSplit":
                braco = next(
                    (
                        b
                        for b in no.get("data", {}).get("braços") or []
                        if str(b.get("id")) == str(aresta.get("cond"))
                    ),
                    None,
                )
                pct = Decimal(str(braco.get("pct", 0))) if braco else Decimal(0)
                volumes[destino] += volume * pct / _CEM
            elif no.get("type") in TIPOS_DIVISAO_IGUAL:
                volumes[destino] += volume / Decimal(len(arestas))
            else:
                volumes[destino] += volume  # repasse integral (wait, sto, channel...)
            grau_entrada[destino] -= 1
            if grau_entrada[destino] == 0:
                fila.append(destino)
    return volumes, processados < len(nos)


def calcular(
    grafo: dict[str, Any], *, volume_entrada: int, tarifas: dict[str, Decimal]
) -> tuple[Decimal, list[dict[str, Any]], list[str]]:
    """Taxímetro (A2): (custo_total quantizado a centavo, memória por nó, avisos)."""
    volumes, houve_ciclo = _volumes_por_no(grafo, volume_entrada)
    avisos: list[str] = []
    if houve_ciclo:
        avisos.append("Grafo com ciclo: nós do ciclo ficaram fora do taxímetro (JGC deve ser DAG).")
    memoria: list[dict[str, Any]] = []
    total = Decimal(0)
    for no in grafo.get("nodes") or []:
        if not isinstance(no, dict) or not no.get("id"):
            continue  # nó malformado: o jgc_validate aponta; aqui nunca KeyError (A13)
        tipo = str(no.get("type", ""))
        if not tipo.startswith("channel."):
            continue
        no_id, canal = str(no["id"]), tipo.split(".", 1)[1]
        volume = int(volumes.get(no_id, Decimal(0)))  # floor: não se cobra fração de envio
        tarifa = tarifas.get(canal)
        if tarifa is None:
            avisos.append(
                f"Canal {canal!r} (nó {no_id}) sem tarifa vigente — custo 0 no taxímetro."
            )
            tarifa = Decimal(0)
        custo = (Decimal(volume) * tarifa).quantize(_CENTAVO, rounding=ROUND_HALF_UP)
        total += custo
        memoria.append(
            {
                "no": no_id,
                "canal": canal,
                "volume": volume,
                "tarifa": str(tarifa),
                "custo": str(custo),
            }
        )
    return total.quantize(_CENTAVO, rounding=ROUND_HALF_UP), memoria, avisos
