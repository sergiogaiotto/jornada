/**
 * T7 · Canvas do Digital Twin (mock T7 / SDD §8-M7): React Flow com a linguagem visual
 * do Journey Builder (nós custom na paleta JB — losangos laranja para splits), modos
 * Desenho/Simulação/Dinâmico, TAXÍMETRO fixo no rodapé (Σ volume × tarifa — cálculo é
 * código), premissas em chips, ajuste por texto livre como DIFF Aplicar/Rejeitar
 * (nunca aplica direto) e inspetor de nó no painel direito com a prévia JSON SFMC.
 * Modo Desenho = EDITOR nível Journey Builder (src/canvas/): paleta drag&drop, CRUD
 * de nós/arestas com undo/redo, inspetor por tipo §5.2, lint local §5.3 e salvar
 * via PUT (que invalida a simulação). Sem versão: gerar com Flow OU começar do zero
 * (POST /os/{id}/jornada — emenda §8-M7, determinístico).
 * Versionamento/exportação (emenda §8-M7): header com a linha do tempo de versões
 * (versão antiga abre SOMENTE LEITURA + "Restaurar como nova versão"), "Comparar
 * com…" pinta o diff do BE no próprio canvas (CanvasDiff), Exportar baixa JSON
 * (import nativo JB) ou XML (auditoria) com toast de hash/manifest; modo Simulação
 * sobrepõe os volumes P50 da última simulação por nó/aresta (overlaySimulacao).
 */
import "@xyflow/react/dist/style.css";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Background, Controls, ReactFlow } from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { CanvasDiff } from "../canvas/CanvasDiff";
import { EditorJornada } from "../canvas/EditorJornada";
import { HeaderVersoes } from "../canvas/HeaderVersoes";
import { type ProblemaLint } from "../canvas/lint";
import { aplicarOverlaySimulacao } from "../canvas/overlaySimulacao";
import { BadgeViaAi } from "../components/ai/BadgeViaAi";
import { ChipsPremissas } from "../components/ai/ChipsPremissas";
import { Copiloto } from "../components/ai/Copiloto";
import { PreviaDiff, type ItemDiff } from "../components/ai/PreviaDiff";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { jgcParaFlow, ROTULO_CANAL } from "../components/twin/jgcParaFlow";
import { NoJb } from "../components/twin/NoJb";
import { ApiError, baixar, get, post, put } from "../lib/api";
import { fmtBRL, fmtCompacto, fmtTarifa } from "../lib/format";
import { usePainelContextual } from "../lib/hooks";
import type {
  AjustarOut,
  DiffVersoesOut,
  GerarJornadaOut,
  GrafoJgc,
  GrafoOut,
  JornadaOut,
  JornadaResumoOut,
} from "../lib/types";
import { useProducao } from "../stores/producao";

const TIPOS_DE_NO = { jb: NoJb };

type Modo = "desenho" | "simulacao" | "dinamico";

const MODOS: { id: Modo; rotulo: string; ativo: string }[] = [
  { id: "desenho", rotulo: "● Desenho", ativo: "bg-blue text-white" },
  { id: "simulacao", rotulo: "Simulação", ativo: "bg-ch4 text-white" },
  { id: "dinamico", rotulo: "Dinâmico", ativo: "bg-good text-white" },
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
  const ensaio = useProducao((s) => s.ensaios[osId]);
  const queryClient = useQueryClient();

  const [modo, setModo] = useState<Modo>("desenho");
  const [instrucoes, setInstrucoes] = useState(
    "Holdout 10%, A/B no e-mail âncora, cadência D0→D2→D4, rota express WhatsApp para heavy users.",
  );
  const [ajuste, setAjuste] = useState("");
  const [proposta, setProposta] = useState<AjustarOut | null>(null);
  const [noSelecionado, setNoSelecionado] = useState<string | null>(null);
  /** versão da linha do tempo em exibição (null = última — a única editável) */
  const [versaoVistaId, setVersaoVistaId] = useState<string | null>(null);
  /** "Comparar com…": versão do diff visual pintado no canvas */
  const [compararComId, setCompararComId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const jornada = estado?.jornada;
  const taximetro = estado?.taximetro;

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 8000);
    return () => window.clearTimeout(t);
  }, [toast]);

  /**
   * A14 (UAT): ao montar, carrega a ÚLTIMA versão persistida do twin
   * (GET /os/{id}/jornada — emenda SDD §8-M7; 404 = OS sem versão → botão Gerar).
   * Só consulta quando o estado em memória está vazio (ex.: reload do navegador).
   */
  const ultimaVersao = useQuery({
    queryKey: ["os", osId, "jornada"],
    queryFn: ({ signal }) => get<JornadaOut>(`/os/${osId}/jornada`, signal),
    enabled: Boolean(osId) && !estado,
    retry: false,
  });
  const semVersao =
    ultimaVersao.error instanceof ApiError && ultimaVersao.error.status === 404;

  useEffect(() => {
    if (ultimaVersao.data && !estado) {
      // GET não expõe a memória do taxímetro — o rodapé usa o custo persistido;
      // a memória volta ao re-gerar/PUT (que recalculam e devolvem o taxímetro).
      setJornada(osId, {
        jornada: ultimaVersao.data,
        taximetro: {
          custo_projetado: ultimaVersao.data.custo_projetado ?? 0,
          memoria: [],
          avisos: [],
        },
      });
    }
  }, [ultimaVersao.data, estado, osId, setJornada]);

  /** Linha do tempo do twin (emenda §8-M7): dropdown de versões do header. */
  const versoes = useQuery({
    queryKey: ["os", osId, "jornadas"],
    queryFn: ({ signal }) => get<JornadaResumoOut[]>(`/os/${osId}/jornadas`, signal),
    enabled: Boolean(osId) && Boolean(jornada),
  });
  const invalidarVersoes = () =>
    void queryClient.invalidateQueries({ queryKey: ["os", osId, "jornadas"] });

  /** Versão antiga selecionada → abre SOMENTE LEITURA (GET /jornadas/{id}). */
  const vendoAntiga = Boolean(versaoVistaId && jornada && versaoVistaId !== jornada.id);
  const versaoAntiga = useQuery({
    queryKey: ["jornadas", versaoVistaId],
    queryFn: ({ signal }) => get<JornadaOut>(`/jornadas/${versaoVistaId}`, signal),
    enabled: vendoAntiga,
  });
  const jornadaExibida = vendoAntiga ? (versaoAntiga.data ?? null) : (jornada ?? null);

  /** "Comparar com…" — grafo da outra versão (fantasmas) + diff do BE (diff.py). */
  const comparada = useQuery({
    queryKey: ["jornadas", compararComId],
    queryFn: ({ signal }) => get<JornadaOut>(`/jornadas/${compararComId}`, signal),
    enabled: Boolean(compararComId),
  });
  const diffVersoes = useQuery({
    queryKey: ["jornadas", compararComId, "diff", jornadaExibida?.id],
    queryFn: ({ signal }) =>
      get<DiffVersoesOut>(`/jornadas/${compararComId}/diff/${jornadaExibida?.id}`, signal),
    enabled: Boolean(compararComId && jornadaExibida && compararComId !== jornadaExibida.id),
  });
  const comparacaoAtiva = Boolean(
    compararComId && jornadaExibida && comparada.data && diffVersoes.data,
  );

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
      setVersaoVistaId(null);
      setCompararComId(null);
      invalidarVersoes();
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
      invalidarVersoes();
    },
  });

  /** Salvar do EDITOR (modo desenho): PUT do grafo local — o servidor valida §5.3,
   * recalcula o taxímetro e INVALIDA a simulação (estado → rascunho). */
  const salvar = useMutation({
    mutationFn: (grafo: GrafoJgc) => put<GrafoOut>(`/jornadas/${jornada?.id}/grafo`, { grafo }),
    onSuccess: (saida) => {
      setJornada(osId, {
        jornada: saida.jornada,
        taximetro: saida.taximetro,
        resumo: estado?.resumo,
      });
      invalidarVersoes();
    },
  });

  /** "Começar do zero" (emenda §8-M7): nova versão rascunho SEM LLM com o esqueleto
   * mínimo entry→goal→exit — o editor abre pronto para desenhar. */
  const comecarDoZero = useMutation({
    mutationFn: () => post<GrafoOut>(`/os/${osId}/jornada`),
    onSuccess: (saida) => {
      setJornada(osId, { jornada: saida.jornada, taximetro: saida.taximetro });
      setProposta(null);
      setNoSelecionado(null);
      setVersaoVistaId(null);
      setCompararComId(null);
      invalidarVersoes();
    },
  });

  /** Restaurar versão antiga (emenda §8-M7): clona como NOVA versão rascunho —
   * versões NUNCA são sobrescritas; a linha do tempo ganha uma entrada. */
  const restaurar = useMutation({
    mutationFn: (id: string) => post<GrafoOut>(`/jornadas/${id}/restaurar`),
    onSuccess: (saida, origemId) => {
      const origem = versoes.data?.find((v) => v.id === origemId);
      setJornada(osId, { jornada: saida.jornada, taximetro: saida.taximetro });
      setVersaoVistaId(null);
      setCompararComId(null);
      setNoSelecionado(null);
      setToast(
        `Restaurada${origem ? ` a v${origem.versao}` : ""} como NOVA versão v${saida.jornada.versao} (rascunho) — restaurar nunca sobrescreve.`,
      );
      invalidarVersoes();
    },
  });

  /** Exportar (emenda §8-M7): download autenticado + toast com hash/manifest.
   * JSON = spec de import NATIVO do JB · XML = integração/auditoria (manifest+XSD). */
  const exportar = useMutation({
    mutationFn: (formato: "json" | "xml") =>
      baixar(`/jornadas/${jornadaExibida?.id}/export?formato=${formato}`),
    onSuccess: ({ filename, bytes }) => {
      setToast(
        `↓ ${filename} (${fmtCompacto(bytes)} bytes) · manifest: v${jornadaExibida?.versao} · hash ${jornadaExibida?.hash.slice(0, 12)}…`,
      );
    },
  });

  /** Erros 422 do PUT do editor → painel de problemas (origem "servidor"). */
  const problemasServidor = useMemo<ProblemaLint[]>(
    () =>
      errosDeValidacao(salvar.error).map((e) => ({
        no: e.no ?? null,
        regra: e.regra ?? "jgc_validate",
        mensagem: e.mensagem ?? "",
        origem: "servidor" as const,
      })),
    [salvar.error],
  );

  const preview = useQuery({
    queryKey: ["jornadas", jornadaExibida?.id, "sfmc-preview", noSelecionado],
    queryFn: ({ signal }) =>
      get<Record<string, unknown>>(
        `/jornadas/${jornadaExibida?.id}/no/${noSelecionado}/sfmc-preview`,
        signal,
      ),
    enabled: Boolean(jornadaExibida?.id && noSelecionado),
  });

  const fluxo = useMemo(
    () =>
      jornadaExibida
        ? jgcParaFlow(
            jornadaExibida.grafo,
            vendoAntiga ? [] : (taximetro?.memoria ?? []),
            segmento?.contagem_liquida,
          )
        : { nos: [], arestas: [] },
    [jornadaExibida, vendoAntiga, taximetro, segmento?.contagem_liquida],
  );

  /** Última simulação (Ensaio Geral §6) VÁLIDA para a versão exibida — o id da
   * jornada precisa bater (salvar/restaurar geram versão nova sem simulação). */
  const simulacaoAtual =
    jornadaExibida && ensaio && ensaio.id === jornadaExibida.id
      ? (ensaio.simulacao ?? null)
      : null;
  const fluxoComOverlay = useMemo(
    () =>
      modo === "simulacao" && simulacaoAtual
        ? aplicarOverlaySimulacao(fluxo, simulacaoAtual)
        : fluxo,
    [modo, simulacaoAtual, fluxo],
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

  const noJgc = jornadaExibida?.grafo.nodes.find((n) => n.id === noSelecionado) ?? null;
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

      {ultimaVersao.error != null && !semVersao && (
        <BannerErro erro={ultimaVersao.error} contexto="Última versão do twin" />
      )}
      {gerar.error != null && <BannerErro erro={gerar.error} contexto="Flow (gerar)" />}
      {ajustar.error != null && <BannerErro erro={ajustar.error} contexto="Flow (ajustar)" />}
      {comecarDoZero.error != null && (
        <BannerErro erro={comecarDoZero.error} contexto="Começar do zero" />
      )}
      {versaoAntiga.error != null && (
        <BannerErro erro={versaoAntiga.error} contexto="Abrir versão da linha do tempo" />
      )}
      {comparada.error != null && (
        <BannerErro erro={comparada.error} contexto="Comparar com versão" />
      )}
      {diffVersoes.error != null && (
        <BannerErro erro={diffVersoes.error} contexto="Diff entre versões (§8-M7)" />
      )}
      {restaurar.error != null && (
        <BannerErro erro={restaurar.error} contexto="Restaurar como nova versão" />
      )}
      {exportar.error != null && (
        <BannerErro erro={exportar.error} contexto="Exportar jornada (§5.4)" />
      )}
      {toast && (
        <div className="mb-2 flex items-center gap-2 rounded-md border border-good/50 bg-good-soft px-3 py-1.5 text-[12px] text-ink">
          <span className="min-w-0 flex-1">{toast}</span>
          <button
            type="button"
            aria-label="Fechar aviso"
            className="text-muted hover:text-ink"
            onClick={() => setToast(null)}
          >
            ✕
          </button>
        </div>
      )}
      {salvar.error != null && problemasServidor.length === 0 && (
        <BannerErro erro={salvar.error} contexto="Salvar grafo (jgc_validate §5.3)" />
      )}
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
      {!jornada && ultimaVersao.isLoading ? (
        <EstadoVazio>Consultando a última versão do twin…</EstadoVazio>
      ) : !jornada ? (
        <div className="mcard mb-3">
          <div className="mb-1 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
            Flow desenha o rascunho a partir do briefing (prévia via_ai) — ou comece do zero
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
            <button
              type="button"
              className="mbtn-gh flex-none"
              disabled={comecarDoZero.isPending}
              title="POST /os/{id}/jornada — cria v1 rascunho com entry+goal+exit mínimos, sem LLM (§10.6)"
              onClick={() => comecarDoZero.mutate()}
            >
              {comecarDoZero.isPending ? "Criando…" : "Começar do zero"}
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

      {!jornada && !ultimaVersao.isLoading && (
        <EstadoVazio>
          Sem versão do twin nesta OS — gere com o Flow (o `jgc_validate` §5.3 e o
          taxímetro são código, o agente não tem a palavra final) OU comece do zero:
          o servidor cria entry+goal+exit mínimos e o editor abre para desenhar.
        </EstadoVazio>
      )}

      {/* ------------------------------------------------------------- canvas */}
      {jornada && (
        <>
          {/* header de versionamento/exportação (emenda §8-M7) */}
          <HeaderVersoes
            versoes={versoes.data ?? []}
            exibidaId={jornadaExibida?.id ?? jornada.id}
            ultimaId={jornada.id}
            compararComId={compararComId}
            exportando={exportar.isPending}
            onVerVersao={(id) => {
              setVersaoVistaId(id === jornada.id ? null : id);
              setCompararComId(null);
              setNoSelecionado(null);
            }}
            onCompararCom={setCompararComId}
            onExportar={(formato) => exportar.mutate(formato)}
          />

          {vendoAntiga && jornadaExibida && (
            <div className="mb-2 flex flex-wrap items-center gap-2 rounded-md border border-warn-line bg-warn-bg px-3 py-1.5 text-[12px] text-warn">
              <b>
                versão v{jornadaExibida.versao} · {jornadaExibida.estado} — somente leitura
              </b>
              <span>custo projetado {fmtBRL(jornadaExibida.custo_projetado ?? 0)}</span>
              <button
                type="button"
                className="mbtn-gh ml-auto !px-2 !py-0.5 !text-[11px]"
                disabled={restaurar.isPending}
                title="POST /jornadas/{id}/restaurar — clona como NOVA versão rascunho; nunca sobrescreve (§1.2)"
                onClick={() => restaurar.mutate(jornadaExibida.id)}
              >
                {restaurar.isPending ? "Restaurando…" : "⎌ Restaurar como nova versão"}
              </button>
            </div>
          )}

          {comparacaoAtiva && jornadaExibida && comparada.data && diffVersoes.data ? (
            /* DIFF VISUAL (emenda §8-M7): pinta o diff do BE no próprio canvas */
            <CanvasDiff
              exibido={jornadaExibida.grafo}
              comparado={comparada.data.grafo}
              diff={diffVersoes.data}
              rotuloExibida={`v${jornadaExibida.versao}`}
              rotuloComparada={`v${comparada.data.versao}`}
              onFechar={() => setCompararComId(null)}
            />
          ) : compararComId && (comparada.isLoading || diffVersoes.isLoading) ? (
            <EstadoVazio>Calculando o diff entre as versões…</EstadoVazio>
          ) : vendoAntiga ? (
            jornadaExibida ? (
              /* versão antiga: canvas somente leitura (restaurar para editar) */
              <div className="mcard relative h-[440px] overflow-hidden p-0">
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
                  onNodeClick={(_, no) => setNoSelecionado(no.id)}
                  onPaneClick={() => setNoSelecionado(null)}
                >
                  <Background gap={12} size={1} color="#DDE4EA" />
                  <Controls showInteractive={false} />
                </ReactFlow>
              </div>
            ) : (
              <EstadoVazio>Abrindo a versão selecionada…</EstadoVazio>
            )
          ) : modo === "desenho" ? (
            /* EDITOR nível Journey Builder (src/canvas/): paleta, CRUD, undo/redo,
               inspetor §5.2, lint §5.3, MiniMap, auto-layout e salvar (PUT). */
            <EditorJornada
              jornada={jornada}
              problemasServidor={problemasServidor}
              salvando={salvar.isPending}
              onSalvar={(grafo) => salvar.mutate(grafo)}
              onSelecionar={setNoSelecionado}
            />
          ) : (
            <>
              {modo === "simulacao" && simulacaoAtual ? (
                <div className="mb-2 flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface2 px-3 py-1.5 text-[12px] text-slatex">
                  <span className="mchip-b">
                    ▶ simulação de{" "}
                    {new Date(simulacaoAtual.executada_em).toLocaleString("pt-BR")} · seed{" "}
                    {simulacaoAtual.parametros.seed} · {simulacaoAtual.runs} runs
                  </span>
                  <span>
                    volumes P50 por nó; arestas com contagem e espessura proporcional —
                    destino com várias entradas rateia por igual (≈)
                  </span>
                </div>
              ) : modo === "simulacao" ? (
                <div className="mb-2 flex flex-wrap items-center gap-2 rounded-md border border-line bg-surface2 px-3 py-1.5 text-[12px] text-slatex">
                  <span>
                    Sem simulação para esta versão do twin — rode o Ensaio Geral (T8) para
                    dar vida a este modo.
                  </span>
                  <Link
                    to={`/os/${osId}/simulacao`}
                    className="mbtn !px-2.5 !py-1 !text-[11px]"
                  >
                    Abrir o Ensaio Geral →
                  </Link>
                </div>
              ) : (
                <div className="mb-2 rounded-md border border-line bg-surface2 px-3 py-1.5 text-[12px] text-slatex">
                  Modo Dinâmico: telemetria ENS pinta o funil em tempo real após o
                  lançamento (T12/T13).
                </div>
              )}
              <div className="mcard relative h-[440px] overflow-hidden p-0">
                <ReactFlow
                  nodes={fluxoComOverlay.nos}
                  edges={fluxoComOverlay.arestas}
                  nodeTypes={TIPOS_DE_NO}
                  fitView
                  minZoom={0.4}
                  maxZoom={1.6}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  deleteKeyCode={null}
                  onNodeClick={(_, no) => setNoSelecionado(no.id)}
                  onPaneClick={() => setNoSelecionado(null)}
                >
                  <Background gap={12} size={1} color="#DDE4EA" />
                  <Controls showInteractive={false} />
                </ReactFlow>
              </div>
            </>
          )}

          {/* legenda da paleta JB */}
          <div className="mt-1.5 flex flex-wrap gap-3 text-[11px] text-slatex">
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-entry align-middle" />Entry source</span>
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-msg align-middle" />Mensagens</span>
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-flow align-middle" />Flow control (splits · waits)</span>
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-ein align-middle" />Otimização (STO)</span>
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-upd align-middle" />Customer updates</span>
            <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-jb-exit align-middle" />Meta / Exit</span>
          </div>

          {/* ------- ajuste por texto livre (só na última versão, fora do diff) */}
          {!vendoAntiga && !comparacaoAtiva && (
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
          )}
        </>
      )}

      {/* -------------------------------------------- TAXÍMETRO fixo no rodapé */}
      {taximetro && !vendoAntiga && (
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
