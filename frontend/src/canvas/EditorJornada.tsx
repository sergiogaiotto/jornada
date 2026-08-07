/**
 * Editor visual nível Journey Builder do canvas T7 (SDD §5, §8-M7):
 * - Paleta lateral (drag & drop cria nó com data default §5.2);
 * - CRUD completo: conectar por handles, mover livre, Delete remove nó/aresta,
 *   Ctrl+D duplica, Ctrl+Z/Y desfaz/refaz (histórico local ≥ 20 passos);
 * - Inspetor por tipo (painel direito) aplicado ao grafo LOCAL;
 * - Lint em tempo real (lint.ts — espelho leve do jgc_validate §5.3) + painel de
 *   problemas clicável que centraliza o nó (anel vermelho);
 * - MiniMap + Controls + auto-layout por camadas BFS (botão "Organizar");
 * - Salvar = PUT /jornadas/{id}/grafo (o servidor valida §5.3 e recalcula o
 *   taxímetro; 422 volta mapeado ao painel). Salvar INVALIDA a simulação (§6).
 */
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { atividadeDoTipo, COR_CATEGORIA, proximoId, proximoIdAresta } from "./catalogo";
import { Inspetor } from "./Inspetor";
import { organizarLayout } from "./layout";
import { lintarGrafo, type ProblemaLint } from "./lint";
import { PainelProblemas } from "./PainelProblemas";
import { Paleta } from "./Paleta";
import { aparencia } from "../components/twin/jgcParaFlow";
import { NoJb, type DadosNoJb, type NoJbFlow } from "../components/twin/NoJb";
import { useFecharForaEsc } from "../lib/hooks";
import type { ArestaJgc, GrafoJgc, JornadaOut } from "../lib/types";

const TIPOS_DE_NO = { jb: NoJb };
const LIMITE_HISTORICO = 50; // ≥ 20 passos exigidos pelo aceite do editor

interface Snap {
  grafo: GrafoJgc;
  posicoes: Record<string, { x: number; y: number }>;
}

interface Props {
  jornada: JornadaOut;
  /** erros 422 do PUT (jgc_validate do servidor) já normalizados */
  problemasServidor: ProblemaLint[];
  salvando: boolean;
  onSalvar: (grafo: GrafoJgc) => void;
  /** sincroniza o nó selecionado com o painel contextual (custo + prévia SFMC) */
  onSelecionar: (noId: string | null) => void;
}

const clonar = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

function snapInicial(jornada: JornadaOut): Snap {
  const grafo = clonar(jornada.grafo);
  return { grafo, posicoes: organizarLayout(grafo) };
}

/** Arestas derivadas das regras de decisionSplit — visíveis mas não editáveis
 * (edite as regras no inspetor); a adjacência espelha o backend. */
function arestasDeRegras(grafo: GrafoJgc): Edge[] {
  const arestas: Edge[] = [];
  for (const no of grafo.nodes ?? []) {
    if (no.type !== "decisionSplit") continue;
    const regras = (no.data?.["regras"] ?? []) as { expr?: string; to?: string }[];
    for (const [i, r] of regras.entries()) {
      if (!r.to) continue;
      arestas.push({
        id: `regra:${no.id}:${i}`,
        source: no.id,
        target: r.to,
        label: r.expr ?? undefined,
        type: "smoothstep",
        deletable: false,
        selectable: false,
        style: { stroke: "#DD7A01", strokeWidth: 1.2, strokeDasharray: "4 3" },
        labelStyle: { fontSize: 9, fill: "#5F7186", fontWeight: 700 },
        labelBgStyle: { fill: "#FBFCFD" },
      });
    }
  }
  return arestas;
}

/** cond automática ao conectar a partir de um split: primeiro braço/classe órfão. */
function condParaConexao(grafo: GrafoJgc, origem: string): string | null {
  const no = grafo.nodes.find((n) => n.id === origem);
  if (!no) return null;
  const usadas = new Set(
    grafo.edges.filter((a) => a.from === origem).map((a) => String(a.cond)),
  );
  if (no.type === "randomSplit") {
    const bracos = (no.data?.["braços"] ?? no.data?.["bracos"] ?? []) as { id?: string }[];
    return bracos.map((b) => String(b.id ?? "")).find((id) => id && !usadas.has(id)) ?? null;
  }
  if (no.type === "frequencySplit") {
    // D05/I01: classe pode ser objeto {id, min/max} — o cond da aresta é o id,
    // nunca o objeto (cond-objeto levava 422 tipo_invalido anônimo no save).
    const classes = (no.data?.["classes"] ?? []) as (string | { id?: string })[];
    const rotulos = classes.map((c) =>
      typeof c === "object" && c !== null ? String(c.id ?? "") : String(c));
    return rotulos.find((r) => r && !usadas.has(r)) ?? null;
  }
  return null;
}

const ATALHOS: [string, string][] = [
  ["Arrastar da paleta", "criar nó com data default (§5.2)"],
  ["Arrastar entre handles", "conectar (splits ganham cond do braço órfão)"],
  ["Delete / Backspace", "excluir nó ou aresta selecionada"],
  ["Ctrl+D", "duplicar o nó selecionado"],
  ["Ctrl+Z · Ctrl+Y", "desfazer · refazer (histórico local)"],
  ["Clique no problema", "centralizar o nó com erro (anel vermelho)"],
];

export function EditorJornada(props: Props) {
  return (
    <ReactFlowProvider>
      <EditorInterno {...props} />
    </ReactFlowProvider>
  );
}

function EditorInterno({ jornada, problemasServidor, salvando, onSalvar, onSelecionar }: Props) {
  const rf = useReactFlow();
  const [estado, setEstado] = useState<Snap>(() => snapInicial(jornada));
  const [historico, setHistorico] = useState<{ passado: Snap[]; futuro: Snap[] }>({
    passado: [],
    futuro: [],
  });
  const [noSelecionado, setNoSelecionado] = useState<string | null>(null);
  const [ajudaAberta, setAjudaAberta] = useState(false);
  const fecharAjuda = useCallback(() => setAjudaAberta(false), []);
  // clique fora / Esc fecham o popover de atalhos (padrão do DropdownGuia)
  const raizAjuda = useFecharForaEsc(ajudaAberta, fecharAjuda);
  const baseRef = useRef(`${jornada.id}:${jornada.hash}`);
  const ultimoNoEditadoRef = useRef<string | null>(null);

  // adota o grafo do servidor quando a versão muda (gerar/restaurar/PUT ok):
  // mesma jornada ⇒ preserva posições e histórico; jornada nova ⇒ reset completo.
  useEffect(() => {
    const chave = `${jornada.id}:${jornada.hash}`;
    if (chave === baseRef.current) return;
    const mesmaJornada = baseRef.current.startsWith(`${jornada.id}:`);
    baseRef.current = chave;
    const grafo = clonar(jornada.grafo);
    setEstado((prev) => {
      const posicoes = organizarLayout(grafo);
      if (mesmaJornada)
        for (const id of Object.keys(posicoes))
          if (prev.posicoes[id]) posicoes[id] = prev.posicoes[id];
      return { grafo, posicoes };
    });
    if (!mesmaJornada) {
      setHistorico({ passado: [], futuro: [] });
      setNoSelecionado(null);
      onSelecionar(null);
    }
    ultimoNoEditadoRef.current = null;
  }, [jornada.id, jornada.hash, jornada.grafo, onSelecionar]);

  const empurrarHistorico = useCallback((snapshot: Snap) => {
    setHistorico((h) => ({
      passado: [...h.passado.slice(-(LIMITE_HISTORICO - 1)), snapshot],
      futuro: [],
    }));
  }, []);

  /** mutação estrutural: snapshot no histórico + novo estado. */
  const mutar = useCallback(
    (fn: (s: Snap) => Snap) => {
      ultimoNoEditadoRef.current = null;
      empurrarHistorico(estado);
      setEstado(fn(clonar(estado)));
    },
    [estado, empurrarHistorico],
  );

  const desfazer = useCallback(() => {
    if (historico.passado.length === 0) return;
    const anterior = historico.passado[historico.passado.length - 1];
    setHistorico({
      passado: historico.passado.slice(0, -1),
      futuro: [...historico.futuro.slice(-(LIMITE_HISTORICO - 1)), estado],
    });
    setEstado(anterior);
    ultimoNoEditadoRef.current = null;
  }, [historico, estado]);

  const refazer = useCallback(() => {
    if (historico.futuro.length === 0) return;
    const proximo = historico.futuro[historico.futuro.length - 1];
    setHistorico({
      passado: [...historico.passado.slice(-(LIMITE_HISTORICO - 1)), estado],
      futuro: historico.futuro.slice(0, -1),
    });
    setEstado(proximo);
    ultimoNoEditadoRef.current = null;
  }, [historico, estado]);

  const selecionar = useCallback(
    (id: string | null) => {
      setNoSelecionado(id);
      onSelecionar(id);
    },
    [onSelecionar],
  );

  const excluirNo = useCallback(
    (id: string) => {
      mutar((s) => ({
        ...s,
        grafo: {
          ...s.grafo,
          nodes: s.grafo.nodes.filter((n) => n.id !== id),
          edges: s.grafo.edges.filter((a) => a.from !== id && a.to !== id),
        },
      }));
      if (noSelecionado === id) selecionar(null);
    },
    [mutar, noSelecionado, selecionar],
  );

  const duplicarNo = useCallback(
    (id: string) => {
      const original = estado.grafo.nodes.find((n) => n.id === id);
      if (!original) return;
      const novoId = proximoId(estado.grafo.nodes);
      mutar((s) => {
        const pos = s.posicoes[id] ?? { x: 60, y: 60 };
        return {
          grafo: {
            ...s.grafo,
            nodes: [...s.grafo.nodes, { id: novoId, type: original.type, data: clonar(original.data) }],
          },
          posicoes: { ...s.posicoes, [novoId]: { x: pos.x + 32, y: pos.y + 32 } },
        };
      });
      selecionar(novoId);
    },
    [estado, mutar, selecionar],
  );

  const editarData = useCallback(
    (id: string, data: Record<string, unknown>) => {
      // 1 passo de histórico por "rajada" de edição no mesmo nó (undo reverte o bloco)
      if (ultimoNoEditadoRef.current !== id) {
        empurrarHistorico(estado);
        ultimoNoEditadoRef.current = id;
      }
      setEstado((s) => ({
        ...s,
        grafo: {
          ...s.grafo,
          nodes: s.grafo.nodes.map((n) => (n.id === id ? { ...n, data } : n)),
        },
      }));
    },
    [estado, empurrarHistorico],
  );

  // ------------------------------------------------------------------ React Flow
  const problemasLocais = useMemo(() => lintarGrafo(estado.grafo), [estado.grafo]);
  const problemas = useMemo(
    () => [...problemasServidor, ...problemasLocais],
    [problemasServidor, problemasLocais],
  );
  const nosComProblema = useMemo(
    () => new Set(problemas.map((p) => p.no).filter((n): n is string => Boolean(n))),
    [problemas],
  );

  const nosFlow: NoJbFlow[] = useMemo(
    () =>
      estado.grafo.nodes.map((no) => {
        const dados: DadosNoJb = { ...aparencia(no), erro: nosComProblema.has(no.id) };
        return {
          id: no.id,
          type: "jb" as const,
          position: estado.posicoes[no.id] ?? { x: 40, y: 40 },
          width: 104,
          height: 72,
          selected: no.id === noSelecionado,
          data: dados,
        };
      }),
    [estado, nosComProblema, noSelecionado],
  );

  const arestasFlow: Edge[] = useMemo(
    () => [
      ...estado.grafo.edges.map((a) => ({
        id: a.id,
        source: a.from,
        target: a.to,
        label: a.cond ?? undefined,
        type: "smoothstep" as const,
        deletable: true,
        style: { stroke: "#B9C6D3", strokeWidth: 1.5 },
        labelStyle: { fontSize: 9, fill: "#5F7186", fontWeight: 700 },
        labelBgStyle: { fill: "#FBFCFD" },
      })),
      ...arestasDeRegras(estado.grafo),
    ],
    [estado.grafo],
  );

  const aoMudarNos = useCallback(
    (mudancas: NodeChange<NoJbFlow>[]) => {
      const removidos = mudancas.filter((m) => m.type === "remove").map((m) => m.id);
      if (removidos.length > 0) {
        mutar((s) => ({
          ...s,
          grafo: {
            ...s.grafo,
            nodes: s.grafo.nodes.filter((n) => !removidos.includes(n.id)),
            edges: s.grafo.edges.filter(
              (a) => !removidos.includes(a.from) && !removidos.includes(a.to),
            ),
          },
        }));
        if (noSelecionado && removidos.includes(noSelecionado)) selecionar(null);
      }
      for (const m of mudancas) {
        if (m.type === "position" && m.position)
          setEstado((s) => ({
            ...s,
            posicoes: { ...s.posicoes, [m.id]: m.position as { x: number; y: number } },
          }));
        if (m.type === "select") selecionar(m.selected ? m.id : null);
      }
    },
    [mutar, noSelecionado, selecionar],
  );

  const aoMudarArestas = useCallback(
    (mudancas: EdgeChange<Edge>[]) => {
      const removidas = mudancas
        .filter((m) => m.type === "remove")
        .map((m) => m.id)
        .filter((id) => estado.grafo.edges.some((a) => a.id === id));
      if (removidas.length > 0)
        mutar((s) => ({
          ...s,
          grafo: { ...s.grafo, edges: s.grafo.edges.filter((a) => !removidas.includes(a.id)) },
        }));
    },
    [estado, mutar],
  );

  const aoConectar = useCallback(
    (conexao: Connection) => {
      if (!conexao.source || !conexao.target) return;
      // I02 (roteamento_ambiguo §5.3): um decisionSplit roteado por `regras[].to`
      // não pode ganhar aresta real — era exatamente assim que o híbrido nascia na
      // UI (as arestas tracejadas das regras não são editáveis; a manual duplicaria
      // a saída na adjacência). O destino se edita nas regras, pelo Inspetor.
      const origem = estado.grafo.nodes.find((n) => n.id === conexao.source);
      if (origem?.type === "decisionSplit") {
        const regras = (origem.data?.["regras"] ?? []) as { to?: string }[];
        if (regras.some((r) => r.to)) return;
      }
      const cond = condParaConexao(estado.grafo, conexao.source);
      const nova: ArestaJgc = {
        id: proximoIdAresta(estado.grafo.edges.map((a) => a.id)),
        from: conexao.source,
        to: conexao.target,
        cond,
      };
      mutar((s) => ({ ...s, grafo: { ...s.grafo, edges: [...s.grafo.edges, nova] } }));
    },
    [estado, mutar],
  );

  const aoSoltar = useCallback(
    (evento: React.DragEvent) => {
      const tipo = evento.dataTransfer.getData("application/jornada-tipo");
      const atividade = atividadeDoTipo(tipo);
      if (!atividade) return;
      evento.preventDefault();
      const posicao = rf.screenToFlowPosition({ x: evento.clientX, y: evento.clientY });
      const id = proximoId(estado.grafo.nodes);
      mutar((s) => ({
        grafo: {
          ...s.grafo,
          nodes: [...s.grafo.nodes, { id, type: tipo, data: atividade.dataDefault() }],
        },
        posicoes: { ...s.posicoes, [id]: { x: posicao.x - 52, y: posicao.y - 18 } },
      }));
      selecionar(id);
    },
    [estado, mutar, rf, selecionar],
  );

  const focarNo = useCallback(
    (noId: string) => {
      const pos = estado.posicoes[noId];
      if (!pos) return;
      rf.setCenter(pos.x + 52, pos.y + 36, { zoom: 1.2, duration: 400 });
      selecionar(noId);
    },
    [estado, rf, selecionar],
  );

  const organizar = useCallback(() => {
    mutar((s) => ({ ...s, posicoes: organizarLayout(s.grafo) }));
    window.setTimeout(() => rf.fitView({ duration: 300, padding: 0.15 }), 50);
  }, [mutar, rf]);

  const aoTeclar = useCallback(
    (evento: React.KeyboardEvent) => {
      const alvo = evento.target as HTMLElement;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(alvo.tagName)) return; // formulários
      if (!(evento.ctrlKey || evento.metaKey)) return;
      const tecla = evento.key.toLowerCase();
      if (tecla === "z" && !evento.shiftKey) {
        evento.preventDefault();
        desfazer();
      } else if (tecla === "y" || (tecla === "z" && evento.shiftKey)) {
        evento.preventDefault();
        refazer();
      } else if (tecla === "d") {
        evento.preventDefault();
        if (noSelecionado) duplicarNo(noSelecionado);
      }
    },
    [desfazer, refazer, duplicarNo, noSelecionado],
  );

  const noJgcSelecionado = estado.grafo.nodes.find((n) => n.id === noSelecionado) ?? null;
  const editavel = jornada.estado === "rascunho" || jornada.estado === "simulado";

  return (
    <div onKeyDown={aoTeclar}>
      <div className="mcard overflow-hidden p-0">
        {/* ------------------------------------------------------------ toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-white px-3 py-1.5">
          <button type="button" className="mbtn-gh !px-2 !py-1 !text-[11px]" onClick={organizar}>
            ⇥ Organizar
          </button>
          <button
            type="button"
            className="mbtn-gh !px-2 !py-1 !text-[11px]"
            disabled={historico.passado.length === 0}
            onClick={desfazer}
            title="Ctrl+Z"
          >
            ↶ Desfazer
          </button>
          <button
            type="button"
            className="mbtn-gh !px-2 !py-1 !text-[11px]"
            disabled={historico.futuro.length === 0}
            onClick={refazer}
            title="Ctrl+Y"
          >
            ↷ Refazer
          </button>
          <div ref={raizAjuda} className="relative">
            <button
              type="button"
              className="mbtn-gh !px-2 !py-1 !text-[11px]"
              aria-label="Atalhos do editor"
              aria-haspopup="dialog"
              aria-expanded={ajudaAberta}
              onClick={() => setAjudaAberta((v) => !v)}
            >
              ?
            </button>
            {ajudaAberta && (
              <div className="absolute left-0 top-8 z-20 w-72 rounded-lg border border-line bg-white p-3 shadow-card">
                <div className="mb-1 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                  Atalhos do editor
                </div>
                {ATALHOS.map(([tecla, acao]) => (
                  <div key={tecla} className="flex justify-between gap-2 py-0.5 text-[11.5px]">
                    <b className="whitespace-nowrap text-steel">{tecla}</b>
                    <span className="text-right text-slatex">{acao}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
          <span className={problemas.length > 0 ? "mchip-r" : "mchip-g"}>
            {problemas.length > 0 ? `${problemas.length} problema(s)` : "lint ✓"}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-[10.5px] text-warn">
              ⚠ Salvar invalida a simulação (estado → rascunho §6)
            </span>
            <button
              type="button"
              className="mbtn !px-3 !py-1 !text-[11.5px]"
              disabled={salvando || !editavel}
              title={
                editavel
                  ? "PUT /jornadas/{id}/grafo — o servidor valida §5.3 e recalcula o taxímetro"
                  : `Versão ${jornada.estado} não é editável — restaure como nova versão`
              }
              onClick={() => onSalvar(estado.grafo)}
            >
              {salvando ? "Salvando…" : "Salvar grafo"}
            </button>
          </div>
        </div>

        {!editavel && (
          <div className="border-b border-warn-line bg-warn-bg px-3 py-1.5 text-[11.5px] text-warn">
            Versão em estado <b>{jornada.estado}</b> não é editável (§1.2) — use
            "Restaurar" na linha do tempo para clonar como novo rascunho.
          </div>
        )}

        {/* ---------------------------------------------- paleta · canvas · inspetor */}
        <div className="flex h-[520px]">
          <Paleta />
          <div
            className="relative min-h-0 min-w-0 flex-1"
            onDrop={aoSoltar}
            onDragOver={(e) => {
              if (e.dataTransfer.types.includes("application/jornada-tipo")) {
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
              }
            }}
          >
            <ReactFlow
              nodes={nosFlow}
              edges={arestasFlow}
              nodeTypes={TIPOS_DE_NO}
              onNodesChange={aoMudarNos}
              onEdgesChange={aoMudarArestas}
              onConnect={aoConectar}
              onNodeDragStart={() => empurrarHistorico(estado)}
              onPaneClick={() => selecionar(null)}
              fitView
              minZoom={0.4}
              maxZoom={1.6}
              connectionRadius={28}
              deleteKeyCode={["Delete", "Backspace"]}
              nodesDraggable
              nodesConnectable
            >
              <Background gap={12} size={1} color="#DDE4EA" />
              <Controls showInteractive={false} />
              <MiniMap
                pannable
                zoomable
                nodeColor={(no) => COR_CATEGORIA[(no.data as DadosNoJb).categoria] ?? "#747E8B"}
                className="!h-24 !w-36"
              />
            </ReactFlow>
          </div>
          <Inspetor
            no={noJgcSelecionado}
            idsDeNos={estado.grafo.nodes.map((n) => n.id)}
            onEditarData={editarData}
            onExcluir={excluirNo}
            onDuplicar={duplicarNo}
          />
        </div>
      </div>

      <PainelProblemas problemas={problemas} onFocar={focarNo} />
    </div>
  );
}
