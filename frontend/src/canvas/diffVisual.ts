/**
 * Diff VISUAL entre versões do twin (emenda §8-M7): combina o diff estrutural do
 * backend (GET /jornadas/{a}/diff/{b} — domain/jornada/diff.py, o MESMO diff do
 * ajustar e do M11) com os DOIS grafos para pintar no próprio canvas:
 * - adicionado (só na versão exibida)  → anel VERDE;
 * - removido  (só na versão comparada) → FANTASMA vermelho translúcido — o nó/aresta
 *   entra num "grafo de união" apenas para ser desenhado;
 * - alterado  (mesmo id, conteúdo ≠)   → anel ÂMBAR.
 * Convenção de direção: o diff deve ser pedido como de=COMPARADA → para=EXIBIDA,
 * assim "adicionados" lê-se "o que a versão exibida ganhou". Módulo puro (sem React).
 */
import type { MarcaDiff } from "../components/twin/NoJb";
import type { ArestaJgc, DiffVersoesOut, GrafoJgc, NoJgc } from "../lib/types";

export interface ItemDiffVisual {
  alvo: "nó" | "aresta";
  id: string;
  marca: MarcaDiff;
  /** legível: tipo do nó · "from → to (cond)" da aresta */
  detalhe: string;
}

export interface DiffVisual {
  /** grafo da versão exibida + fantasmas (nós/arestas que só existem na comparada) */
  grafoUniao: GrafoJgc;
  marcasNos: Map<string, MarcaDiff>;
  marcasArestas: Map<string, MarcaDiff>;
  /** mudanças na ordem: nós (＋/Δ/−) e depois arestas — painel lateral clicável */
  itens: ItemDiffVisual[];
}

function marcas(ids: { adicionados: string[]; removidos: string[]; alterados: string[] }) {
  const mapa = new Map<string, MarcaDiff>();
  for (const id of ids.adicionados) mapa.set(id, "adicionado");
  for (const id of ids.removidos) mapa.set(id, "removido");
  for (const id of ids.alterados) mapa.set(id, "alterado");
  return mapa;
}

const ORDEM_MARCA: MarcaDiff[] = ["adicionado", "alterado", "removido"];

export function montarDiffVisual(
  exibido: GrafoJgc,
  comparado: GrafoJgc,
  diff: DiffVersoesOut,
): DiffVisual {
  const marcasNos = marcas(diff.nodes);
  const marcasArestas = marcas(diff.edges);

  // fantasmas: itens que SÓ existem na versão comparada (removidos na exibida)
  const nosFantasma: NoJgc[] = comparado.nodes.filter(
    (n) => marcasNos.get(n.id) === "removido",
  );
  const arestasFantasma: ArestaJgc[] = comparado.edges.filter(
    (a) => marcasArestas.get(a.id) === "removido",
  );
  const grafoUniao: GrafoJgc = {
    ...exibido,
    nodes: [...exibido.nodes, ...nosFantasma],
    edges: [...exibido.edges, ...arestasFantasma],
  };

  const porId = new Map<string, NoJgc>(grafoUniao.nodes.map((n) => [n.id, n]));
  const arestaPorId = new Map<string, ArestaJgc>(grafoUniao.edges.map((a) => [a.id, a]));

  const itens: ItemDiffVisual[] = [];
  for (const marca of ORDEM_MARCA)
    for (const [id, m] of marcasNos)
      if (m === marca)
        itens.push({ alvo: "nó", id, marca, detalhe: porId.get(id)?.type ?? id });
  for (const marca of ORDEM_MARCA)
    for (const [id, m] of marcasArestas)
      if (m === marca) {
        const a = arestaPorId.get(id);
        itens.push({
          alvo: "aresta",
          id,
          marca,
          detalhe: a ? `${a.from} → ${a.to}${a.cond ? ` (${a.cond})` : ""}` : id,
        });
      }

  return { grafoUniao, marcasNos, marcasArestas, itens };
}
