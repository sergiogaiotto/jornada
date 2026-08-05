/**
 * T8 · Ensaio Geral — simulador Monte Carlo (mock T8 / SDD §6, §8-M8): portão
 * obrigatório. KPIs P10/P50/P90 (conversões, custo, receita, ROAS, lift), funil por
 * nó, gargalos, semáforo (vermelho bloqueia T9/T11), comparador de cenários lado a
 * lado e Congelar Previsto (a régua imutável do pós-disparo). ZERO LLM no caminho
 * crítico — o copiloto Simulate apenas NARRA os achados.
 */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ChipsPremissas } from "../components/ai/ChipsPremissas";
import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, Kpi, TituloTela } from "../components/ui/basics";
import { ApiError, post } from "../lib/api";
import { fmtBRL, fmtCompacto, fmtInt } from "../lib/format";
import { usePainelContextual } from "../lib/hooks";
import type {
  CompararOut,
  JornadaSimuladaOut,
  P105090,
  Semaforo,
  SimulacaoResultado,
} from "../lib/types";
import { useProducao } from "../stores/producao";

const SEMAFORO_CHIP: Record<Semaforo, string> = {
  verde: "mchip-g",
  amarelo: "mchip-w",
  vermelho: "mchip-r",
};

const METRICA_ROTULO: Record<string, string> = {
  conversoes: "Conversões",
  custo: "Custo",
  receita: "Receita",
  roas: "ROAS",
  lift_pp: "Lift (pp)",
};

function fmtFaixa(p: P105090 | null | undefined, fmt: (n: number) => string): string {
  if (!p) return "—";
  return `P10 ${fmt(p.p10)} · P90 ${fmt(p.p90)}`;
}

function fmtX(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${n.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}x`;
}

/** Erros §5.3 do 422 GrafoInvalido: [{no, regra, mensagem}]. */
function errosDoGrafo(erro: unknown): { no?: string; regra?: string; mensagem?: string }[] {
  if (erro instanceof ApiError && Array.isArray(erro.problem["erros"])) {
    return erro.problem["erros"] as { no?: string; regra?: string; mensagem?: string }[];
  }
  return [];
}

export function Ensaio() {
  const { id } = useParams<{ id: string }>();
  const osId = id ?? "";

  const jornadaTwin = useProducao((s) => s.jornadas[osId]);
  const ensaio = useProducao((s) => s.ensaios[osId]);
  const cenarios = useProducao((s) => s.cenarios[osId] ?? []);
  const setEnsaio = useProducao((s) => s.setEnsaio);
  const registrarCenario = useProducao((s) => s.registrarCenario);

  const [seed, setSeed] = useState(42);
  const [runs, setRuns] = useState(500);
  const [nPersonas, setNPersonas] = useState(10_000);
  const [comparacao, setComparacao] = useState<CompararOut | null>(null);

  const jornadaId = ensaio?.id ?? jornadaTwin?.jornada.id ?? null;
  const sim: SimulacaoResultado | null = ensaio?.simulacao ?? null;
  const congelado = Boolean(ensaio?.previsto);

  const simular = useMutation({
    mutationFn: () =>
      post<JornadaSimuladaOut>(`/jornadas/${jornadaId}/simular`, {
        seed,
        runs,
        n_personas: nPersonas,
      }),
    onSuccess: (r) => {
      setEnsaio(osId, r);
      registrarCenario(osId, {
        jornada_id: r.id,
        versao: r.versao,
        hash: r.hash,
        rotulo: `v${r.versao} · ${r.hash.slice(0, 8)}`,
      });
      setComparacao(null);
    },
  });

  const congelar = useMutation({
    mutationFn: () => post<JornadaSimuladaOut>(`/jornadas/${jornadaId}/congelar-previsto`),
    onSuccess: (r) => setEnsaio(osId, r),
  });

  const comparar = useMutation({
    mutationFn: (ids: string[]) => post<CompararOut>("/simulacoes/comparar", { jornada_ids: ids }),
    onSuccess: setComparacao,
  });

  const errosGrafo = errosDoGrafo(simular.error);
  const funil = Object.entries(sim?.funil ?? {});
  const maxFunil = Math.max(1, ...funil.map(([, v]) => v.p50));
  const pressao = Object.entries(sim?.pressao_contato ?? {});

  usePainelContextual(
    <>
      <div className="ctx-title">Explicador causal</div>
      <Copiloto titulo="Simulate">
        {sim ? (
          <>
            Rodei <b>{fmtCompacto(sim.parametros.n_personas)} personas × {sim.parametros.runs} runs</b>{" "}
            (seed {sim.parametros.seed} — reprodutível, §8-M8-A1) sobre{" "}
            {fmtCompacto(sim.volume_entrada)} contatos líquidos.{" "}
            {sim.gargalos.length > 0 ? (
              <>
                Maior gargalo: <b>{sim.gargalos[0].no}</b> (espera P50 de{" "}
                {sim.gargalos[0].espera_horas_p50.toLocaleString("pt-BR")}h).{" "}
              </>
            ) : (
              "Sem gargalos relevantes de espera. "
            )}
            {sim.semaforo === "verde"
              ? "Semáforo VERDE — recomendo congelar o Previsto e seguir aos portões."
              : sim.semaforo === "amarelo"
                ? "Semáforo AMARELO — há avisos; revise antes de congelar."
                : "Semáforo VERMELHO — T9/T11 ficam bloqueados até resolver os motivos."}
          </>
        ) : (
          <>
            O Ensaio Geral percorre o grafo com personas sintéticas (só agregados —
            anti-reidentificação) e produz o Previsto em P10/P50/P90. Nada dispara sem
            ensaio (§1.1.2).
          </>
        )}
      </Copiloto>

      <div className="ctx-title">Premissas (editáveis)</div>
      {sim ? (
        <ChipsPremissas premissas={sim.premissas} />
      ) : (
        <div className="text-[12px] text-muted">Rode o ensaio para ver as premissas.</div>
      )}

      <div className="ctx-title">Pressão de contato</div>
      {pressao.length > 0 ? (
        <div className="mfield block">
          {pressao.map(([canal, p]) => (
            <span key={canal} className="flex items-baseline justify-between text-[12px]">
              <span>
                {canal}
                {p.colisao_critica && <span className="mchip-r ml-1">colisão</span>}
              </span>
              <b className="tabular-nums">
                {p.msgs_por_contato.p50.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}{" "}
                msg/contato
                {p.cap_janela != null && (
                  <span className="font-normal text-faint"> · cap {p.cap_janela}</span>
                )}
              </b>
            </span>
          ))}
        </div>
      ) : (
        <div className="text-[12px] text-muted">— sem simulação —</div>
      )}

      <div className="ctx-title">Portão</div>
      <div className="mfield">
        <span className="text-[12px]">
          {sim?.semaforo === "verde" ? (
            <>
              Simulação <b className="text-good">VERDE</b> — libera os{" "}
              <Link to={`/os/${osId}/portoes`} className="font-semibold text-blue underline">
                portões de governança (T9)
              </Link>
            </>
          ) : sim?.semaforo === "vermelho" ? (
            <>
              Simulação <b className="text-crit">VERMELHA</b> — bloqueia T9/T11 (§6)
            </>
          ) : sim?.semaforo === "amarelo" ? (
            <>
              Simulação <b className="text-warn">AMARELA</b> — siga com atenção aos avisos
            </>
          ) : (
            <>portão obrigatório — rode o ensaio (§6)</>
          )}
        </span>
        {sim && <span className={SEMAFORO_CHIP[sim.semaforo]}>{sim.semaforo}</span>}
      </div>
    </>,
    [sim, osId, pressao.length],
  );

  return (
    <div>
      <TituloTela
        titulo={
          <>
            Ensaio Geral{" "}
            <span className="mchip-v align-middle">
              {fmtCompacto(nPersonas)} personas · {runs} runs
            </span>{" "}
            {sim && (
              <span className={`${SEMAFORO_CHIP[sim.semaforo]} align-middle`}>
                semáforo {sim.semaforo}
              </span>
            )}
          </>
        }
        subtitulo="Monte Carlo com relógio virtual (waits, quiet hours, throttle, STO) · o previsto congela como régua do pós-disparo"
      />

      {simular.error != null && (
        <div>
          <BannerErro erro={simular.error} contexto="Ensaio Geral" />
          {errosGrafo.length > 0 && (
            <div className="-mt-1 mb-3 text-[12px] text-crit">
              {errosGrafo.map((e, i) => (
                <span key={i} className="block">
                  <b>{e.no ?? "grafo"}</b> · {e.regra ?? "regra"} — {e.mensagem}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
      {congelar.error != null && <BannerErro erro={congelar.error} contexto="Congelar Previsto" />}
      {comparar.error != null && <BannerErro erro={comparar.error} contexto="Comparador" />}

      {/* ------------------------------------------------ parâmetros do run */}
      <div className="mcard mb-3">
        <div className="mb-1 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
          Parâmetros do run (seed fixa ⇒ mesmos P50s — §8-M8-A1)
        </div>
        <div className="flex flex-wrap items-end gap-3">
          {(
            [
              ["Seed", seed, setSeed, 1],
              ["Runs (K)", runs, setRuns, 10],
              ["Personas (N)", nPersonas, setNPersonas, 100],
            ] as const
          ).map(([rotulo, valor, setter, min]) => (
            <label key={rotulo} className="text-[11.5px] font-semibold text-slatex">
              {rotulo}
              <input
                type="number"
                min={min}
                value={valor}
                onChange={(e) => setter(Number(e.target.value))}
                className="mt-0.5 block w-28 rounded-md border border-line2 px-2 py-1.5 text-[12.5px] tabular-nums outline-none focus:border-blue"
              />
            </label>
          ))}
          <button
            type="button"
            className="mbtn"
            disabled={simular.isPending || jornadaId === null}
            onClick={() => simular.mutate()}
          >
            {simular.isPending ? "Simulando…" : sim ? "Re-simular" : "Rodar Ensaio Geral"}
          </button>
          <button
            type="button"
            className="mbtn-gd"
            disabled={congelar.isPending || !sim || congelado}
            title="Sela a régua imutável do pós-disparo (§1.1.2) — o snapshot (T9) herda este bloco"
            onClick={() => congelar.mutate()}
          >
            {congelar.isPending
              ? "Congelando…"
              : congelado
                ? "Previsto congelado ✓"
                : "Congelar Previsto"}
          </button>
        </div>
        {congelado && ensaio?.previsto?.congelado_em && (
          <div className="mt-1.5 text-[11.5px] text-good">
            Previsto congelado em{" "}
            {new Date(ensaio.previsto.congelado_em).toLocaleString("pt-BR")} por{" "}
            {ensaio.previsto.congelado_por} — todo KPI do pós-disparo será um par
            previsto × realizado.
          </div>
        )}
      </div>

      {jornadaId === null && (
        <EstadoVazio>
          Nenhuma versão de jornada nesta OS —{" "}
          <Link to={`/os/${osId}/twin`} className="font-semibold text-blue underline">
            gere o grafo no Twin Canvas (T7)
          </Link>{" "}
          antes do Ensaio Geral.
        </EstadoVazio>
      )}

      {jornadaId !== null && !sim && !simular.isPending && (
        <EstadoVazio>
          Portão obrigatório (§6): 10.000 personas sintéticas percorrem o grafo em Monte
          Carlo — <b>Rodar Ensaio Geral</b> produz o funil, custo, ROAS e lift em
          P10/P50/P90.
        </EstadoVazio>
      )}

      {sim && (
        <>
          {/* ------------------------------------------------------- KPIs */}
          <div className="mb-3 flex flex-wrap gap-3">
            <Kpi
              rotulo="Conversões (P50)"
              valor={fmtInt(Math.round(sim.conversoes.p50))}
              detalhe={fmtFaixa(sim.conversoes, (n) => fmtInt(Math.round(n)))}
            />
            <Kpi
              rotulo="Custo total (P50)"
              valor={fmtBRL(sim.custo.p50, 0)}
              detalhe={fmtFaixa(sim.custo, (n) => fmtBRL(n, 0))}
            />
            <Kpi
              rotulo="Receita projetada (P50)"
              valor={fmtBRL(sim.receita.p50, 0)}
              detalhe={fmtFaixa(sim.receita, (n) => fmtBRL(n, 0))}
              tom="good"
            />
            <Kpi
              rotulo="ROAS (P50)"
              valor={fmtX(sim.roas?.p50)}
              detalhe={fmtFaixa(sim.roas, fmtX)}
              tom="good"
            />
            <Kpi
              rotulo="Lift esperado (P50)"
              valor={`${sim.lift_pp.p50 >= 0 ? "+" : ""}${sim.lift_pp.p50.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}pp`}
              detalhe={
                sim.poder.aplicavel
                  ? `MDE ${sim.poder.mde_pp?.toLocaleString("pt-BR")}pp · poder ${((sim.poder.poder ?? 0) * 100).toFixed(0)}% ${sim.poder.suficiente ? "✓" : "✗"}`
                  : "sem experimento pré-registrado (T9)"
              }
              tom="blue"
            />
          </div>

          {(sim.motivos_semaforo.length > 0 || sim.avisos.length > 0) && (
            <div
              className={`mcard mb-3 ${sim.semaforo === "vermelho" ? "border-crit/50 bg-crit-soft/40" : "border-warn-line bg-warn-bg"}`}
            >
              <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                Semáforo {sim.semaforo} — motivos (§6)
              </div>
              <div className="mt-1 text-[12.5px]">
                {[...sim.motivos_semaforo, ...sim.avisos].map((m, i) => (
                  <span key={i} className="block">
                    • {m}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="flex flex-wrap items-start gap-3">
            {/* ------------------------------------------------ funil por nó */}
            <div className="mcard min-w-[320px] flex-[1.2]">
              <div className="mb-2 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                Funil projetado por nó (P50 · {sim.runs} runs)
              </div>
              <div className="grid gap-1.5">
                {funil.map(([noId, v]) => (
                  <div key={noId} className="text-[12px]">
                    <div className="flex items-baseline justify-between gap-2">
                      <span>
                        <span className="font-mono font-semibold">{noId}</span>{" "}
                        <span className="text-faint">{v.tipo}</span>
                      </span>
                      <b className="tabular-nums">{fmtCompacto(Math.round(v.p50))}</b>
                    </div>
                    <div className="mbar">
                      <i
                        className="bg-ch2"
                        style={{ width: `${Math.max(1, (100 * v.p50) / maxFunil)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              {sim.gargalos.length > 0 && (
                <div className="mt-2 border-t border-linesoft pt-2 text-[11.5px] text-slatex">
                  <b>Gargalos:</b>{" "}
                  {sim.gargalos.map((g) => (
                    <span key={g.no} className="mchip-w mr-1">
                      {g.no} · {g.espera_horas_p50.toLocaleString("pt-BR")}h
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* --------------------------------------------- comparador */}
            <div className="mcard min-w-[320px] flex-1">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                  Cenários simulados (lado a lado)
                </div>
                <button
                  type="button"
                  className="mbtn-gh !px-2.5 !py-1 !text-[11px]"
                  disabled={comparar.isPending || cenarios.length < 2}
                  title={
                    cenarios.length < 2
                      ? "Edite o grafo no Twin (nova versão) e simule de novo para comparar cenários"
                      : "POST /simulacoes/comparar — P50s + deltas vs baseline"
                  }
                  onClick={() => comparar.mutate(cenarios.map((c) => c.jornada_id))}
                >
                  {comparar.isPending ? "Comparando…" : "Comparar cenários"}
                </button>
              </div>

              <div className="grid gap-1">
                {cenarios.map((c) => (
                  <div
                    key={c.jornada_id}
                    className="flex items-center justify-between rounded-md bg-surface2 px-2.5 py-1.5 text-[12px]"
                  >
                    <span>
                      <b>{c.rotulo}</b>
                      {c.jornada_id === jornadaId && (
                        <span className="mchip-b ml-1.5">corrente</span>
                      )}
                    </span>
                    <span className="font-mono text-[10.5px] text-faint">
                      {c.jornada_id.slice(0, 8)}…
                    </span>
                  </div>
                ))}
                {cenarios.length < 2 && (
                  <div className="text-[11.5px] text-muted">
                    Cada versão do twin simulada vira um cenário — edite o grafo no{" "}
                    <Link to={`/os/${osId}/twin`} className="font-semibold text-blue underline">
                      Twin (T7)
                    </Link>{" "}
                    e re-simule para comparar (cada arrasto re-simula).
                  </div>
                )}
              </div>

              {comparacao && (
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-left text-[11.5px]">
                    <thead>
                      <tr className="border-b border-linesoft text-[10px] uppercase tracking-[.06em] text-faint">
                        <th className="py-1 pr-2">Cenário</th>
                        {Object.keys(METRICA_ROTULO).map((m) => (
                          <th key={m} className="py-1 pr-2 text-right">
                            {METRICA_ROTULO[m]}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {comparacao.cenarios.map((c) => {
                        const baseline = c.jornada_id === comparacao.baseline;
                        return (
                          <tr
                            key={c.jornada_id}
                            className={`border-b border-linesoft ${baseline ? "bg-good-soft/40" : ""}`}
                          >
                            <td className="py-1 pr-2">
                              <b>v{c.versao}</b>{" "}
                              <span className={SEMAFORO_CHIP[c.semaforo]}>{c.semaforo}</span>
                              {baseline && <span className="mchip-n ml-1">baseline</span>}
                            </td>
                            {Object.keys(METRICA_ROTULO).map((m) => {
                              const valor = c.p50[m];
                              const delta = c.delta_vs_baseline[m];
                              return (
                                <td key={m} className="py-1 pr-2 text-right tabular-nums">
                                  {m === "custo" || m === "receita"
                                    ? fmtBRL(valor, 0)
                                    : m === "roas"
                                      ? fmtX(valor)
                                      : (valor?.toLocaleString("pt-BR", {
                                          maximumFractionDigits: 1,
                                        }) ?? "—")}
                                  {!baseline && delta != null && delta !== 0 && (
                                    <span
                                      className={`block text-[10px] ${delta > 0 ? "text-good" : "text-crit"}`}
                                    >
                                      {delta > 0 ? "+" : ""}
                                      {delta.toLocaleString("pt-BR", {
                                        maximumFractionDigits: 1,
                                      })}
                                    </span>
                                  )}
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
