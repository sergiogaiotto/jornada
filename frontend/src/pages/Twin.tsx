/**
 * T7 · Canvas do Digital Twin (mock T7 / SDD §8-M7): React Flow com a linguagem visual
 * do Journey Builder (nós custom na paleta JB — losangos laranja para splits), modos
 * Desenho/Simulação/Ao Vivo, TAXÍMETRO fixo no rodapé (Σ volume × tarifa — cálculo é
 * código), premissas em chips, ajuste por texto livre como DIFF Aplicar/Rejeitar
 * (nunca aplica direto) e inspetor de nó no painel direito com a prévia JSON SFMC.
 */
import "@xyflow/react/dist/style.css";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Background, Controls, ReactFlow } from "@xyflow/react";
import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { BadgeViaAi } from "../components/ai/BadgeViaAi";
import { ChipsPremissas } from "../components/ai/ChipsPremissas";
import { Copiloto } from "../components/ai/Copiloto";
import { PreviaDiff, type ItemDiff } from "../components/ai/PreviaDiff";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { jgcParaFlow, ROTULO_CANAL } from "../components/twin/jgcParaFlow";
import { NoJb } from "../components/twin/NoJb";
import { ApiError, get, post, put } from "../lib/api";
import { fmtBRL, fmtCompacto, fmtTarifa } from "../lib/format";
import { usePainelContextual } from "../lib/hooks";
import type { AjustarOut, GerarJornadaOut, GrafoOut } from "../lib/types";
import { useProducao } from "../stores/producao";

const TIPOS_DE_NO = { jb: NoJb };

type Modo = "desenho" | "simulacao" | "aovivo";

const MODOS: { id: Modo; rotulo: string; ativo: string }[] = [
  { id: "desenho", rotulo: "● Desenho", ativo: "bg-blue text-white" },
  { id: "simulacao", rotulo: "Simulação", ativo: "bg-ch4 text-white" },
  { id: "aovivo", rotulo: "Ao Vivo", ativo: "bg-good text-white" },
];

/** Erros §5.3 vindos do 422 (GrafoInvalido): `erros[{no, regra, mensagem}]`. */
function errosDeValidacao(erro: unknown): { no?: string; regra?: string; mensagem?: string }[] {
  if (erro instanceof ApiError && Array.isArray(erro.problem["erros"]))
    return erro.problem["erros"] as { no?: string; regra?: string; mensagem?: string }[];
  return [];
}

export function Twin() {
  const { id } = useParams<{ id: string }>();
  const osId = id ?? "";

  const estado = useProducao((s) => s.jornadas[osId]);
  const setJornada = useProducao((s) => s.setJornada);
  const segmento = useProducao((s) => s.segmentos[osId]);

  const [modo, setModo] = useState<Modo>("desenho");
  const [instrucoes, setInstrucoes] = useState(
    "Holdout 10%, A/B no e-mail âncora, cadência D0→D2→D4, rota express WhatsApp para heavy users.",
  );
  const [ajuste, setAjuste] = useState("");
  const [proposta, setProposta] = useState<AjustarOut | null>(null);
  const [noSelecionado, setNoSelecionado] = useState<string | null>(null);

  const jornada = estado?.jornada;
  const taximetro = estado?.taximetro;

  const gerar = useMutation({
    mutationFn: () => post<GerarJornadaOut>(`/os/${osId}/jornada/gerar`, { instrucoes }),
    onSuccess: (saida) => {
      setJornada(osId, {
        jornada: saida.jornada,
        taximetro: saida.taximetro,
        resumo: saida.resumo,
      });
      setProposta(null);
      setNoSelecionado(null);
    },
  });

  const ajustar = useMutation({
    mutationFn: (texto: string) =>
      post<AjustarOut>(`/jornadas/${jornada?.id}/ajustar`, { instrucoes: texto }),
    onSuccess: (saida) => setProposta(saida),
  });

  const aplicar = useMutation({
    mutationFn: () =>
      put<GrafoOut>(`/jornadas/${jornada?.id}/grafo`, { grafo: proposta?.grafo_proposto }),
    onSuccess: (saida) => {
      setJornada(osId, {
        jornada: saida.jornada,
        taximetro: saida.taximetro,
        resumo: estado?.resumo,
      });
      setProposta(null);
    },
  });

  const preview = useQuery({
    queryKey: ["jornadas", jornada?.id, "sfmc-preview", noSelecionado],
    queryFn: ({ signal }) =>
      get<Record<string, unknown>>(
        `/jornadas/${jornada?.id}/no/${noSelecionado}/sfmc-preview`,
        signal,
      ),
    enabled: Boolean(jornada?.id && noSelecionado),
  });

  const fluxo = useMemo(
    () =>
      jornada
        ? jgcParaFlow(jornada.grafo, taximetro?.memoria ?? [], segmento?.contagem_liquida)
        : { nos: [], arestas: [] },
    [jornada, taximetro, segmento?.contagem_liquida],
  );

  /** Taxímetro agregado por canal (rodapé): Σ volume × tarifa vigente (A2). */
  const porCanal = useMemo(() => {
    const mapa = new Map<string, { volume: number; custo: number; tarifa: string }>();
    for (const item of taximetro?.memoria ?? []) {
      const atual = mapa.get(item.canal) ?? { volume: 0, custo: 0, tarifa: item.tarifa };
      atual.volume += item.volume;
      atual.custo += Number(item.custo);
      mapa.set(item.canal, atual);
    }
    return [...mapa.entries()];
  }, [taximetro]);

  const noJgc = jornada?.grafo.nodes.find((n) => n.id === noSelecionado) ?? null;
  const itemMemoria =
    taximetro?.memoria.find((m) => m.no === noSelecionado) ?? null;
  const errosPut = errosDeValidacao(aplicar.error);

  usePainelContextual(
    <>
      <div className="ctx-title">
        {noJgc ? `Nó selecionado · ${noJgc.id}` : "Inspetor de nó"}
      </div>
      {noJgc ? (
        <>
          <div className="mfield">
            <span className="min-w-0">
              <span className="block text-[12px] font-bold">
                {noJgc.type} <span className="font-mono text-[10.5px] text-faint">{noJgc.id}</span>
              </span>
              <span className="block break-words font-mono text-[10.5px] leading-relaxed text-slatex">
                {JSON.stringify(noJgc.data)}
              </span>
            </span>
          </div>
          {itemMemoria && (
            <div className="mfield">
              <span className="min-w-0">
                <span className="block text-[12px] font-bold">Custo do passo</span>
                <span className="block text-[11.5px] text-slatex">
                  {fmtCompacto(itemMemoria.volume)} × {fmtTarifa(itemMemoria.tarifa)} ={" "}
                  <b>{fmtBRL(itemMemoria.custo)}</b>
                  {taximetro && taximetro.custo_projetado > 0 && (
                    <>
                      {" "}
                      ({Math.round((100 * Number(itemMemoria.custo)) / taximetro.custo_projetado)}%
                      do total{Number(itemMemoria.custo) / taximetro.custo_projetado > 0.5 ? " ⚠" : ""})
                    </>
                  )}
                </span>
              </span>
            </div>
          )}
          <div className="ctx-title">JSON SFMC (Sync · prévia)</div>
          {preview.isLoading && (
            <div className="text-[11.5px] text-muted">Compilando prévia…</div>
          )}
          {preview.error != null && (
            <div className="text-[11.5px] text-crit">Prévia indisponível para este nó.</div>
          )}
          {preview.data !== undefined && (
            <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-claro p-2.5 font-mono text-[10px] leading-relaxed text-claro-paper">
              {JSON.stringify(preview.data, null, 1)}
            </pre>
          )}
        </>
      ) : (
        <div className="text-[12px] text-muted">
          Clique num nó do canvas para inspecionar dados, custo do passo e o JSON que o
          compilador (M9) vai gerar — externalKey idempotente.
        </div>
      )}
      <div className="ctx-title">Copiloto</div>
      <Copiloto
        titulo="Flow"
        acao="Ajustar jornada por texto livre"
        onAcao={() => setAjuste("mover o WhatsApp express de D6 para D4")}
      >
        Antipadrão detectado: nenhum. Sugestão: mover WhatsApp de D6→D4 projeta +180
        conversões (simule no Ensaio Geral).
      </Copiloto>
    </>,
    [noJgc, itemMemoria, preview.data, preview.isLoading, preview.error],
  );

  return (
    <div className="flex min-h-full flex-col">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <TituloTela
          titulo={
            <>
              Canvas da Jornada{" "}
              {jornada && (
                <span className="mchip-b">
                  v{jornada.versao} · {jornada.estado}
                </span>
              )}
            </>
          }
          subtitulo={
            estado?.resumo ? (
              <>
                “{estado.resumo}” <BadgeViaAi rastro={{ agente: "flow", skill: "v1" }} />
              </>
            ) : (
              "Grafo canônico (JGC §5) — tudo que se desenha é materializável 1:1 no SFMC"
            )
          }
        />
        <div className="flex items-center gap-1.5">
          {MODOS.map((m) => (
            <button
              key={m.id}
              type="button"
              onClick={() => setModo(m.id)}
              className={`rounded-full px-3 py-1 text-[12px] font-bold transition-colors ${
                modo === m.id ? m.ativo : "bg-linesoft text-slatex hover:bg-line"
              }`}
            >
              {m.rotulo}
            </button>
          ))}
        </div>
      </div>

      {gerar.error != null && <BannerErro erro={gerar.error} contexto="Flow (gerar)" />}
      {ajustar.error != null && <BannerErro erro={ajustar.error} contexto="Flow (ajustar)" />}
      {aplicar.error != null && (
        <div>
          <BannerErro erro={aplicar.error} contexto="Validação do grafo (§5.3)" />
          {errosPut.length > 0 && (
            <div className="-mt-1 mb-3 grid gap-1 text-[12px]">
              {errosPut.map((e, i) => (
                <div key={i} className="text-crit">
                  ✗ <b>{e.no ?? "grafo"}</b> · {e.regra ?? "regra"} — {e.mensagem}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* --------------------------------------------------- gerar / premissas */}
      {!jornada ? (
        <div className="mcard mb-3">
          <div className="mb-1 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
            Flow desenha o rascunho a partir do briefing (prévia via_ai)
          </div>
          <div className="flex items-start gap-2">
            <textarea
              value={instrucoes}
              onChange={(e) => setInstrucoes(e.target.value)}
              rows={2}
              className="min-w-0 flex-1 resize-y rounded-md border border-line2 px-3 py-2 text-[13px] outline-none focus:border-blue"
              placeholder="Instruções em texto livre para o Flow (opcional)"
            />
            <button
              type="button"
              className="mbtn flex-none"
              disabled={gerar.isPending}
              onClick={() => gerar.mutate()}
            >
              {gerar.isPending ? "Desenhando…" : "Gerar jornada (Flow)"}
            </button>
          </div>
        </div>
      ) : (
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <ChipsPremissas premissas={jornada.premissas} />
          <button
            type="button"
            className="mbtn-gh !px-2.5 !py-1 !text-[11px]"
            disabled={gerar.isPending}
            onClick={() => gerar.mutate()}
          >
            {gerar.isPending ? "Gerando…" : "Nova versão (Flow)"}
          </button>
        </div>
      )}

      {!jornada && (
        <EstadoVazio>
          Sem versão do twin nesta OS — o Flow gera o JGC; `jgc_validate` (§5.3) e o
          taxímetro são código, o agente não tem a palavra final.
        </EstadoVazio>
      )}

      {/* ------------------------------------------------------------- canvas */}
      {jornada && (
        <>
          {modo !== "desenho" && (
            <div className="mb-2 rounded-md border border-line bg-surface2 px-3 py-1.5 text-[12px] text-slatex">
              {modo === "simulacao"
                ? "Modo Simulação: o funil P10/P50/P90 do Ensaio Geral (T8) pinta as arestas — rode a simulação para dar vida a este modo."
                : "Modo Ao Vivo: telemetria ENS pinta o funil em tempo real após o lançamento (T12/T13)."}
            </div>
          )}
          <div className="mcard relative h-[440px] overflow-hidden p-0">
            <ReactFlow
              nodes={fluxo.nos}
              edges={fluxo.arestas}
              nodeTypes={TIPOS_DE_NO}
              fitView
              minZoom={0.4}
              maxZoom={1.6}
              nodesDraggable={modo === "desenho"}
              nodesConnectable={false}
              deleteKeyCode={null}
              onNodeClick={(_, no) => setNoSelecionado(no.id)}
              onPaneClick={() => setNoSelecionado(null)}
            >
              <Background gap={12} size={1} color="#DDE4EA" />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>

          {/* legenda da paleta JB */}
          <div className="mt-1.5 flex flex-wrap gap-3 text-[11px] text-slatex">
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-entry align-middle" />Entry source</span>
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-msg align-middle" />Mensagens</span>
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-flow align-middle" />Flow control (splits · waits)</span>
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-ein align-middle" />Otimização (STO)</span>
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-upd align-middle" />Customer updates</span>
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-exit align-middle" />Meta / Exit</span>
          </div>

          {/* --------------------------------------- ajuste por texto livre */}
          <div className="mcard mt-3">
            <div className="mb-1 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
              Ajustar por texto livre — o Flow propõe um DIFF; aplicar é humano (§1.1.3)
            </div>
            <div className="flex items-center gap-2">
              <input
                value={ajuste}
                onChange={(e) => setAjuste(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && ajuste.trim() && !ajustar.isPending)
                    ajustar.mutate(ajuste.trim());
                }}
                className="min-w-0 flex-1 rounded-md border border-line2 px-3 py-2 text-[13px] outline-none focus:border-blue"
                placeholder='ex.: "adicione um push antes do SMS de D4"'
              />
              <button
                type="button"
                className="mbtn flex-none"
                disabled={ajustar.isPending || ajuste.trim().length === 0}
                onClick={() => ajustar.mutate(ajuste.trim())}
              >
                {ajustar.isPending ? "Propondo…" : "Propor ajuste"}
              </button>
            </div>

            {proposta && (
              <div className="mt-2">
                {!proposta.valido && (
                  <div className="mb-1.5 rounded-md border border-warn-line bg-warn-bg px-2.5 py-1.5 text-[11.5px] text-warn">
                    ⚠ A proposta NÃO passa no `jgc_validate` (§5.3) —{" "}
                    {proposta.erros.map((e) => e.mensagem).join(" · ")}
                  </div>
                )}
                <PreviaDiff
                  titulo={proposta.resumo || "ajuste do Flow"}
                  itens={itensDoDiff(proposta)}
                  premissas={proposta.premissas}
                  rastro={{ agente: "flow", evidencias: proposta.avisos }}
                  rotuloAplicar="Aplicar (PUT do grafo)"
                  onAplicar={() => aplicar.mutateAsync().then(() => undefined)}
                  onRejeitar={() => setProposta(null)}
                />
              </div>
            )}
          </div>
        </>
      )}

      {/* -------------------------------------------- TAXÍMETRO fixo no rodapé */}
      {taximetro && (
        <div className="sticky bottom-0 z-10 mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-claro px-4 py-2 text-[12px] text-claro-pale shadow-card">
          <b className="tracking-wide text-claro-pale">TAXÍMETRO</b>
          {porCanal.map(([canal, v]) => (
            <span key={canal} className="whitespace-nowrap">
              {ROTULO_CANAL[canal] ?? canal} {fmtCompacto(v.volume)} ×{" "}
              {fmtTarifa(v.tarifa)} = <b className="text-white">{fmtBRL(v.custo)}</b>
            </span>
          ))}
          {porCanal.length === 0 && <span>nenhum nó de canal no grafo</span>}
          <span className="ml-auto whitespace-nowrap font-extrabold text-white">
            Total projetado: {fmtBRL(taximetro.custo_projetado)}
          </span>
          {taximetro.avisos.length > 0 && (
            <span className="w-full text-[11px] text-claro-rose">
              ⚠ {taximetro.avisos.join(" · ")}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** Diff §8-M7 → itens da PreviaDiff (nós/arestas adicionados·removidos·alterados + custo). */
function itensDoDiff(p: AjustarOut): ItemDiff[] {
  const itens: ItemDiff[] = [];
  const blocos: { rotulo: string; ids: { adicionados: string[]; removidos: string[]; alterados: string[] } }[] = [
    { rotulo: "Nós", ids: p.diff.nodes },
    { rotulo: "Arestas", ids: p.diff.edges },
  ];
  for (const { rotulo, ids } of blocos) {
    if (ids.adicionados.length > 0)
      itens.push({ rotulo: `${rotulo} adicionados`, depois: ids.adicionados.join(", ") });
    if (ids.removidos.length > 0)
      itens.push({ rotulo: `${rotulo} removidos`, antes: ids.removidos.join(", "), depois: "—" });
    if (ids.alterados.length > 0)
      itens.push({ rotulo: `${rotulo} alterados`, depois: ids.alterados.join(", ") });
  }
  if (p.diff.meta_alterada) itens.push({ rotulo: "Meta do JGC", depois: "alterada" });
  itens.push({
    rotulo: "Custo projetado (taxímetro)",
    antes: p.custo_projetado_atual !== null ? fmtBRL(p.custo_projetado_atual) : undefined,
    depois: fmtBRL(p.custo_projetado_proposto),
  });
  if (itens.length === 1 && p.diff.nodes.adicionados.length === 0)
    itens.unshift({ rotulo: "Estrutura", depois: "sem mudanças estruturais no grafo" });
  return itens;
}
