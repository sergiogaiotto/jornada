/**
 * Auto-layout horizontal do editor T7 (botão "Organizar"): camadas por BFS a partir
 * dos entrySources (profundidade = caminho mais longo, Kahn — o mesmo critério do
 * jgcParaFlow), colunas no eixo X e linhas centradas no eixo Y. Determinístico:
 * a ordem dentro da camada segue a ordem do array de nós do JGC.
 */
import { arestasDoJgc } from "../components/twin/jgcParaFlow";
import type { GrafoJgc } from "../lib/types";

const PASSO_X = 170;
const PASSO_Y = 105;

export function organizarLayout(grafo: GrafoJgc): Record<string, { x: number; y: number }> {
  const nos = grafo.nodes ?? [];
  const arestas = arestasDoJgc(grafo);
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

  const porCamada = new Map<number, string[]>();
  for (const no of nos) {
    const p = prof.get(no.id) ?? 0;
    porCamada.set(p, [...(porCamada.get(p) ?? []), no.id]);
  }
  const maiorCamada = Math.max(1, ...[...porCamada.values()].map((c) => c.length));

  const posicoes: Record<string, { x: number; y: number }> = {};
  for (const no of nos) {
    const p = prof.get(no.id) ?? 0;
    const camada = porCamada.get(p) ?? [];
    const idx = camada.indexOf(no.id);
    const deslocamento = ((maiorCamada - camada.length) * PASSO_Y) / 2;
    posicoes[no.id] = { x: 30 + p * PASSO_X, y: 24 + deslocamento + idx * PASSO_Y };
  }
  return posicoes;
}
