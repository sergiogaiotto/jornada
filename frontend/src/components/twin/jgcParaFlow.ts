/**
 * JGC (§5.1) → React Flow: aparência por tipo de nó (§5.2, paleta JB) e layout
 * determinístico em camadas (profundidade topológica → coluna; ordem no array →
 * linha). A adjacência replica a do backend (edges + regras de decisionSplit —
 * domain/jornada/taximetro._saidas), para desenhar exatamente o que valida/compila.
 */
import { Position, type Edge } from "@xyflow/react";

import { fmtBRL, fmtCompacto } from "../../lib/format";
import type { ArestaJgc, GrafoJgc, ItemMemoriaTaximetro, NoJgc } from "../../lib/types";
import type { DadosNoJb, NoJbFlow } from "./NoJb";

export const ROTULO_CANAL: Record<string, string> = {
  email: "E-mail",
  sms: "SMS",
  push: "Push",
  whatsapp: "WhatsApp",
  rcs: "RCS",
};

const ICONE_CANAL: Record<string, string> = {
  email: "✉",
  sms: "💬",
  push: "🔔",
  whatsapp: "🟢",
  rcs: "✉",
};

function texto(v: unknown): string | undefined {
  return typeof v === "string" && v.length > 0 ? v : undefined;
}

/** Aparência JB do nó (mock T7): categoria de cor + ícone + rótulo + volumetria. */
export function aparencia(no: NoJgc): DadosNoJb {
  const d = no.data ?? {};
  const tipo = no.type;

  if (tipo === "entrySource")
    return {
      categoria: "entry",
      icone: "▶",
      rotulo: "Entrada",
      volumetria: texto(d["deRef"]),
    };
  if (tipo === "randomSplit") {
    const bracos = (d["braços"] ?? d["bracos"]) as { pct?: number }[] | undefined;
    return {
      categoria: "flow",
      icone: "%",
      rotulo: "Random Split",
      volumetria: bracos?.map((b) => b.pct ?? 0).join(" / "),
    };
  }
  if (tipo === "decisionSplit") {
    const regras = (d["regras"] as unknown[] | undefined) ?? [];
    return {
      categoria: "flow",
      icone: "?",
      rotulo: "Decision Split",
      volumetria: `${regras.length} regra${regras.length === 1 ? "" : "s"}`,
    };
  }
  if (tipo === "engagementSplit")
    return {
      categoria: "flow",
      icone: "E",
      rotulo: "Engagement Split",
      volumetria: texto(d["metrica"]),
    };
  if (tipo === "frequencySplit")
    return { categoria: "flow", icone: "f", rotulo: "Frequency Split", volumetria: "governor" };
  if (tipo === "sto") {
    const janela = d["janelaHoras"];
    return {
      categoria: "ein",
      icone: "✦",
      rotulo: "STO",
      volumetria: typeof janela === "number" ? `melhor hora ${janela}h` : "melhor hora",
    };
  }
  if (tipo === "wait")
    return {
      categoria: "wait",
      icone: "⏱",
      rotulo: "Wait",
      volumetria: texto(d["duracao"]) ?? (texto(d["ate"]) ? `até ${texto(d["ate"])}` : undefined),
    };
  if (tipo.startsWith("channel.")) {
    const canal = tipo.split(".", 2)[1];
    return {
      categoria: "msg",
      icone: ICONE_CANAL[canal] ?? "✉",
      rotulo: ROTULO_CANAL[canal] ?? canal,
      volumetria: texto(d["assetRef"]),
    };
  }
  if (tipo === "updateContact")
    return { categoria: "upd", icone: "↺", rotulo: "Update Contact", volumetria: texto(d["deRef"]) };
  if (tipo === "goal")
    return { categoria: "exit", icone: "🎯", rotulo: "Meta / Goal", volumetria: texto(d["metrica"]) };
  if (tipo === "exit")
    return { categoria: "exit", icone: "◼", rotulo: "Exit", volumetria: texto(d["motivo"]) };
  return { categoria: "exit", icone: "⚠", rotulo: tipo, volumetria: "nó de exceção" };
}

/** Mesma adjacência do backend: edges + regras de decisionSplit (to direto). */
export function arestasDoJgc(grafo: GrafoJgc): ArestaJgc[] {
  const vistas = new Set<string>();
  const resultado: ArestaJgc[] = [];
  const empilhar = (a: ArestaJgc) => {
    const chave = `${a.from}→${a.to}·${a.cond ?? ""}`;
    if (!vistas.has(chave)) {
      vistas.add(chave);
      resultado.push(a);
    }
  };
  for (const a of grafo.edges ?? []) empilhar(a);
  for (const no of grafo.nodes ?? []) {
    if (no.type !== "decisionSplit") continue;
    const regras = (no.data?.["regras"] as { expr?: string; to?: string }[] | undefined) ?? [];
    for (const [i, r] of regras.entries()) {
      if (r.to)
        empilhar({ id: `${no.id}-regra-${i}`, from: no.id, to: r.to, cond: r.expr ?? null });
    }
  }
  return resultado;
}

/** Profundidade topológica (Kahn, caminho mais longo); ciclo → resto na camada 0. */
function profundidades(nos: NoJgc[], arestas: ArestaJgc[]): Map<string, number> {
  const ids = new Set(nos.map((n) => n.id));
  const grau = new Map<string, number>(nos.map((n) => [n.id, 0]));
  const saidas = new Map<string, string[]>();
  for (const a of arestas) {
    if (!ids.has(a.from) || !ids.has(a.to)) continue;
    grau.set(a.to, (grau.get(a.to) ?? 0) + 1);
    saidas.set(a.from, [...(saidas.get(a.from) ?? []), a.to]);
  }
  const prof = new Map<string, number>(nos.map((n) => [n.id, 0]));
  const fila = nos.filter((n) => (grau.get(n.id) ?? 0) === 0).map((n) => n.id);
  while (fila.length > 0) {
    const atual = fila.shift() as string;
    for (const destino of saidas.get(atual) ?? []) {
      prof.set(destino, Math.max(prof.get(destino) ?? 0, (prof.get(atual) ?? 0) + 1));
      grau.set(destino, (grau.get(destino) ?? 1) - 1);
      if (grau.get(destino) === 0) fila.push(destino);
    }
  }
  return prof;
}

/** Volumetria dos nós de canal a partir da memória do taxímetro (§8-M7-A2). */
function volumetriaDoTaximetro(memoria: ItemMemoriaTaximetro[]): Map<string, string> {
  const mapa = new Map<string, string>();
  for (const item of memoria)
    mapa.set(item.no, `${fmtCompacto(item.volume)} · ${fmtBRL(item.custo)}`);
  return mapa;
}

export function jgcParaFlow(
  grafo: GrafoJgc,
  memoria: ItemMemoriaTaximetro[],
  liquidoEntrada?: number | null,
): { nos: NoJbFlow[]; arestas: Edge[] } {
  const arestasJgc = arestasDoJgc(grafo);
  const prof = profundidades(grafo.nodes ?? [], arestasJgc);
  const volumetrias = volumetriaDoTaximetro(memoria);

  // linhas por camada, na ordem do array de nós (determinístico)
  const porCamada = new Map<number, string[]>();
  for (const no of grafo.nodes ?? []) {
    const p = prof.get(no.id) ?? 0;
    porCamada.set(p, [...(porCamada.get(p) ?? []), no.id]);
  }
  const maiorCamada = Math.max(1, ...[...porCamada.values()].map((c) => c.length));

  const nos: NoJbFlow[] = (grafo.nodes ?? []).map((no) => {
    const dados = aparencia(no);
    const p = prof.get(no.id) ?? 0;
    const camada = porCamada.get(p) ?? [];
    const idx = camada.indexOf(no.id);
    const deslocamento = ((maiorCamada - camada.length) * 105) / 2;
    if (no.type === "entrySource" && liquidoEntrada != null)
      dados.volumetria = `${dados.volumetria ?? "DE"} · ${fmtCompacto(liquidoEntrada)}`;
    const volumetria = volumetrias.get(no.id);
    if (volumetria) dados.volumetria = volumetria;
    return {
      id: no.id,
      type: "jb",
      position: { x: 30 + p * 160, y: 24 + deslocamento + idx * 105 },
      // dimensões + handles explícitos: arestas calculáveis já no primeiro render,
      // sem esperar a medição via ResizeObserver (contrato SSR do @xyflow/react)
      width: 104,
      height: 72,
      handles: [
        { type: "target" as const, position: Position.Left, x: 0, y: 22, width: 6, height: 6 },
        { type: "source" as const, position: Position.Right, x: 104, y: 22, width: 6, height: 6 },
      ],
      data: dados,
    };
  });

  const arestas: Edge[] = arestasJgc.map((a) => ({
    id: a.id || `${a.from}-${a.to}`,
    source: a.from,
    target: a.to,
    label: a.cond ?? undefined,
    type: "smoothstep",
    style: { stroke: "#B9C6D3", strokeWidth: 1.5 },
    labelStyle: { fontSize: 9, fill: "#5F7186", fontWeight: 700 },
    labelBgStyle: { fill: "#FBFCFD" },
  }));

  return { nos, arestas };
}
