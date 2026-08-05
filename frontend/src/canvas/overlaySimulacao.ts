/**
 * Overlay do modo SIMULAÇÃO do canvas T7 (SDD §6 + §8-M7): pinta os volumes da
 * ÚLTIMA simulação (Ensaio Geral) sobre o grafo — cada nó ganha o P50 do funil como
 * volumetria e cada aresta ganha rótulo com a contagem + espessura proporcional.
 * Aresta herda o P50 do nó de DESTINO; destino com mais de uma entrada divide por
 * igual (aproximação honesta, marcada com "≈" — o motor não expõe volume por aresta).
 * Módulo puro (sem React) — recebe o fluxo já derivado por jgcParaFlow.
 */
import type { Edge } from "@xyflow/react";

import type { NoJbFlow } from "../components/twin/NoJb";
import { fmtCompacto } from "../lib/format";
import type { SimulacaoResultado } from "../lib/types";

const LARGURA_MIN = 1.2;
const LARGURA_MAX = 6;

export function aplicarOverlaySimulacao(
  fluxo: { nos: NoJbFlow[]; arestas: Edge[] },
  simulacao: SimulacaoResultado,
): { nos: NoJbFlow[]; arestas: Edge[] } {
  const funil = simulacao.funil ?? {};

  const nos: NoJbFlow[] = fluxo.nos.map((no) => {
    const passo = funil[no.id];
    if (!passo) return no;
    return { ...no, data: { ...no.data, volumetria: `${fmtCompacto(passo.p50)} · P50` } };
  });

  // grau de entrada por destino — para ratear o P50 entre arestas concorrentes
  const entradas = new Map<string, number>();
  for (const a of fluxo.arestas)
    entradas.set(a.target, (entradas.get(a.target) ?? 0) + 1);

  const volumes = new Map<string, { vol: number; aproximado: boolean }>();
  let maior = 0;
  for (const a of fluxo.arestas) {
    const p50 = funil[a.target]?.p50;
    if (p50 === undefined) continue;
    const grau = entradas.get(a.target) ?? 1;
    const vol = grau > 1 ? p50 / grau : p50;
    volumes.set(a.id, { vol, aproximado: grau > 1 });
    if (vol > maior) maior = vol;
  }

  const arestas: Edge[] = fluxo.arestas.map((a) => {
    const info = volumes.get(a.id);
    if (!info) return a;
    const rotuloVolume = `${info.aproximado ? "≈" : ""}${fmtCompacto(Math.round(info.vol))}`;
    const largura =
      maior > 0 ? LARGURA_MIN + (LARGURA_MAX - LARGURA_MIN) * (info.vol / maior) : LARGURA_MIN;
    return {
      ...a,
      label: a.label ? `${String(a.label)} · ${rotuloVolume}` : rotuloVolume,
      style: { ...a.style, stroke: "#0B827C", strokeWidth: largura },
      labelStyle: { fontSize: 9.5, fill: "#0B827C", fontWeight: 800 },
      labelBgStyle: { fill: "#FBFCFD" },
    };
  });

  return { nos, arestas };
}
