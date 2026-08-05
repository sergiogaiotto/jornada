/**
 * Canvas de COMPARAÇÃO entre versões do twin (emenda §8-M7): somente leitura, pinta
 * o diff estrutural no PRÓPRIO canvas (anel verde = adicionado · fantasma vermelho
 * translúcido = removido, o nó vem da versão comparada só para ser visto · âmbar =
 * alterado) e lista as mudanças num painel lateral clicável que centraliza o item.
 * O diff vem do backend (diff.py — o MESMO do ajustar/M11); aqui é só pintura.
 */
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
} from "@xyflow/react";
import { useMemo } from "react";

import { montarDiffVisual, type ItemDiffVisual } from "./diffVisual";
import { jgcParaFlow } from "../components/twin/jgcParaFlow";
import { NoJb, type MarcaDiff, type NoJbFlow } from "../components/twin/NoJb";
import type { DiffVersoesOut, GrafoJgc } from "../lib/types";

const TIPOS_DE_NO = { jb: NoJb };

/** cores do traço por marca (paleta good/crit/âmbar dos mocks) */
const TRACO: Record<MarcaDiff, { stroke: string; strokeWidth: number; dash?: string; opacity?: number }> = {
  adicionado: { stroke: "#177A4C", strokeWidth: 2.2 },
  removido: { stroke: "#C0392B", strokeWidth: 1.6, dash: "5 4", opacity: 0.45 },
  alterado: { stroke: "#D98E22", strokeWidth: 2 },
};

const SIMBOLO: Record<MarcaDiff, string> = { adicionado: "＋", removido: "−", alterado: "Δ" };
const COR_TEXTO: Record<MarcaDiff, string> = {
  adicionado: "text-good",
  removido: "text-crit",
  alterado: "text-warn",
};

interface Props {
  /** grafo da versão em exibição (o "para" do diff) */
  exibido: GrafoJgc;
  /** grafo da versão escolhida em "Comparar com…" (o "de" do diff) */
  comparado: GrafoJgc;
  diff: DiffVersoesOut;
  rotuloExibida: string;
  rotuloComparada: string;
  onFechar: () => void;
}

export function CanvasDiff(props: Props) {
  return (
    <ReactFlowProvider>
      <CanvasDiffInterno {...props} />
    </ReactFlowProvider>
  );
}

function CanvasDiffInterno({
  exibido,
  comparado,
  diff,
  rotuloExibida,
  rotuloComparada,
  onFechar,
}: Props) {
  const rf = useReactFlow();

  const visual = useMemo(
    () => montarDiffVisual(exibido, comparado, diff),
    [exibido, comparado, diff],
  );

  const fluxo = useMemo(() => {
    const base = jgcParaFlow(visual.grafoUniao, []);
    const nos: NoJbFlow[] = base.nos.map((no) => {
      const marca = visual.marcasNos.get(no.id);
      return marca ? { ...no, data: { ...no.data, diff: marca } } : no;
    });
    const arestas: Edge[] = base.arestas.map((a) => {
      const marca = visual.marcasArestas.get(a.id);
      if (!marca) return a;
      const traco = TRACO[marca];
      return {
        ...a,
        style: {
          stroke: traco.stroke,
          strokeWidth: traco.strokeWidth,
          strokeDasharray: traco.dash,
          opacity: traco.opacity,
        },
      };
    });
    return { nos, arestas };
  }, [visual]);

  const focar = (item: ItemDiffVisual) => {
    if (item.alvo === "nó") {
      const no = fluxo.nos.find((n) => n.id === item.id);
      if (no) rf.setCenter(no.position.x + 52, no.position.y + 36, { zoom: 1.2, duration: 400 });
      return;
    }
    const aresta = visual.grafoUniao.edges.find((a) => a.id === item.id);
    if (!aresta) return;
    const de = fluxo.nos.find((n) => n.id === aresta.from);
    const para = fluxo.nos.find((n) => n.id === aresta.to);
    if (de && para)
      rf.setCenter(
        (de.position.x + para.position.x) / 2 + 52,
        (de.position.y + para.position.y) / 2 + 36,
        { zoom: 1.1, duration: 400 },
      );
  };

  return (
    <div className="mcard overflow-hidden p-0">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-white px-3 py-1.5 text-[11.5px]">
        <b className="text-steel">
          Comparando {rotuloExibida} (exibida) com {rotuloComparada}
        </b>
        <span className="text-slatex">
          <i className="mr-1 inline-block h-2 w-2 rounded-full bg-good align-middle" />
          anel verde = adicionado em {rotuloExibida}
        </span>
        <span className="text-slatex">
          <i className="mr-1 inline-block h-2 w-2 rounded-full bg-crit align-middle" />
          fantasma vermelho = existia só em {rotuloComparada}
        </span>
        <span className="text-slatex">
          <i className="mr-1 inline-block h-2 w-2 rounded-full bg-warn align-middle" />
          âmbar = alterado
        </span>
        <button
          type="button"
          className="mbtn-gh ml-auto !px-2 !py-0.5 !text-[11px]"
          onClick={onFechar}
        >
          ✕ Fechar comparação
        </button>
      </div>
      <div className="flex h-[440px]">
        <div className="relative min-h-0 min-w-0 flex-1">
          <ReactFlow
            nodes={fluxo.nos}
            edges={fluxo.arestas}
            nodeTypes={TIPOS_DE_NO}
            fitView
            minZoom={0.4}
            maxZoom={1.6}
            nodesDraggable={false}
            nodesConnectable={false}
            deleteKeyCode={null}
          >
            <Background gap={12} size={1} color="#DDE4EA" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
        <div className="w-60 flex-none overflow-y-auto border-l border-line bg-surface2 p-2.5">
          <div className="mb-1 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
            Mudanças ({visual.itens.length})
          </div>
          {visual.itens.length === 0 && (
            <div className="text-[11.5px] text-muted">
              Nenhuma diferença estrutural — os grafos são idênticos
              {diff.meta_alterada ? " (apenas a meta do JGC mudou)" : ""}.
            </div>
          )}
          {visual.itens.map((item) => (
            <button
              key={`${item.alvo}:${item.id}`}
              type="button"
              onClick={() => focar(item)}
              className="mb-1 block w-full rounded-md border border-line bg-white px-2 py-1 text-left text-[11.5px] hover:border-blue"
              title="Centralizar no canvas"
            >
              <b className={COR_TEXTO[item.marca]}>{SIMBOLO[item.marca]}</b>{" "}
              <b className="font-mono">{item.id}</b>{" "}
              <span className="text-slatex">
                · {item.alvo} {item.marca} — {item.detalhe}
              </span>
            </button>
          ))}
          {diff.meta_alterada && visual.itens.length > 0 && (
            <div className="mt-1 text-[11px] text-warn">Δ meta do JGC alterada</div>
          )}
        </div>
      </div>
    </div>
  );
}
