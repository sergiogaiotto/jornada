/**
 * T15 · Otimização & Retro — o loop que fecha (mock T15 / SDD §8-M11): o optimize
 * PROPÕE (única ação autônoma) mudanças ranqueadas lift × esforço × risco, cada uma
 * como diff JGC com impacto PRÉ-SIMULADO — aprovar dispara o mini-ciclo M8→M9
 * expresso (nova versão + aprovação EXPRESSA). Apuração do experimento respeita
 * anti-peeking (425 Too Early antes da janela — A1; significativo SÓ com IC
 * excluindo zero — A2). "Clonar com aprendizados" instancia a próxima campanha já
 * otimizada; Calibrate publica priors novos SÓ com backtest aprovado.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { BadgeViaAi } from "../components/ai/BadgeViaAi";
import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { ApiError, get, post } from "../lib/api";
import { fmtBRL } from "../lib/format";
import { usePainelContextual } from "../lib/hooks";
import type {
  ApuracaoOut,
  AprovarPropostaOut,
  CalibracaoOut,
  CloneOut,
  PortoesOut,
  PropostaOut,
  PropostasOut,
  RejeitarPropostaOut,
} from "../lib/types";

const METRICA_ROTULO: Record<string, string> = {
  conversoes: "conversões",
  custo: "custo",
  receita: "receita",
  roas: "ROAS",
  lift_pp: "lift (pp)",
};

function fmtDelta(metrica: string, delta: number | null): string | null {
  if (delta === null || delta === 0) return null;
  const sinal = delta > 0 ? "+" : "−";
  const abs = Math.abs(delta);
  if (metrica === "custo" || metrica === "receita") return `${sinal}${fmtBRL(abs, 0)}`;
  if (metrica === "roas") return `${sinal}${abs.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}x`;
  return `${sinal}${abs.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}`;
}

function ResumoDiff({ proposta }: { proposta: PropostaOut }) {
  const { nodes, edges } = proposta.diff;
  const partes = [
    nodes.alterados.length > 0 && `${nodes.alterados.length} nó(s) alterado(s)`,
    nodes.adicionados.length > 0 && `${nodes.adicionados.length} nó(s) novo(s)`,
    nodes.removidos.length > 0 && `${nodes.removidos.length} nó(s) removido(s)`,
    edges.alterados.length + edges.adicionados.length + edges.removidos.length > 0 &&
      `${edges.alterados.length + edges.adicionados.length + edges.removidos.length} aresta(s)`,
  ].filter(Boolean);
  return (
    <span className="mchip-v" title={`diff JGC: ${JSON.stringify(proposta.diff)}`}>
      diff: {partes.join(" · ") || "sem mudança estrutural"}
    </span>
  );
}

export function Retro() {
  const { id } = useParams<{ id: string }>();
  const osId = id ?? "";
  const queryClient = useQueryClient();

  const [rejeitandoId, setRejeitandoId] = useState<string | null>(null);
  const [motivo, setMotivo] = useState("");
  const [aprovada, setAprovada] = useState<AprovarPropostaOut | null>(null);

  const propostas = useQuery({
    queryKey: ["os", osId, "propostas"],
    queryFn: ({ signal }) => get<PropostasOut>(`/os/${osId}/propostas`, signal),
    enabled: Boolean(osId),
  });

  const portoes = useQuery({
    queryKey: ["os", osId, "portoes"],
    queryFn: ({ signal }) => get<PortoesOut>(`/os/${osId}/portoes`, signal),
    enabled: Boolean(osId),
  });
  const experimentoId = (portoes.data?.portoes.experimento["id"] as string | undefined) ?? null;

  const invalidar = () => queryClient.invalidateQueries({ queryKey: ["os", osId, "propostas"] });

  const aprovar = useMutation({
    mutationFn: (propostaId: string) =>
      post<AprovarPropostaOut>(`/propostas/${propostaId}/aprovar`),
    onSuccess: (r) => {
      setAprovada(r);
      invalidar();
    },
  });

  const rejeitar = useMutation({
    mutationFn: ({ propostaId, texto }: { propostaId: string; texto: string }) =>
      post<RejeitarPropostaOut>(`/propostas/${propostaId}/rejeitar`, { motivo: texto }),
    onSuccess: () => {
      setRejeitandoId(null);
      setMotivo("");
      invalidar();
    },
  });

  const apurar = useMutation({
    mutationFn: () => post<ApuracaoOut>(`/experimentos/${experimentoId}/apurar`),
  });

  const clonar = useMutation({
    mutationFn: () => post<CloneOut>(`/os/${osId}/clonar-com-aprendizados`, {}),
  });

  const calibrar = useMutation({
    mutationFn: () => post<CalibracaoOut>("/calibracao/publicar", {}),
  });

  const lista = propostas.data?.propostas ?? [];
  const pendentes = lista.filter((p) => p.estado === "proposta");
  const decididas = lista.filter((p) => p.estado !== "proposta");
  const apuracao = apurar.data;
  const antiPeeking =
    apurar.error instanceof ApiError && apurar.error.status === 425 ? apurar.error : null;
  const fimJanela = antiPeeking?.problem["fim_janela"] as string | null | undefined;

  usePainelContextual(
    <>
      <div className="ctx-title">Regras do loop</div>
      <Copiloto titulo="Optimize">
        Propor é minha <b>única ação autônoma</b> (§8-M11) — aplicar exige humano e uma
        nova aprovação expressa (link mágico) antes de qualquer apply. Rejeições viram{" "}
        <b>sinal</b>: não re-proponho o que você já recusou por esse motivo.
      </Copiloto>

      <div className="ctx-title">Anti-peeking</div>
      <div className="mfield">
        <span className="text-[12px]">
          Apuração antes do fim da janela pré-registrada ⇒ <b>425 Too Early</b> — nenhum
          lift é calculado (A1); <b>significativo</b> só com IC95 excluindo zero (A2)
        </span>
      </div>

      {calibrar.data && (
        <>
          <div className="ctx-title">Score de calibração</div>
          <div className="mfield">
            <span className="text-[12px]">
              priors <b>v{calibrar.data.versao}</b> publicados · score{" "}
              <b>{calibrar.data.score.toLocaleString("pt-BR")}</b> · backtest ✓
            </span>
            <span className="mchip-g">↑</span>
          </div>
        </>
      )}

      <div className="ctx-title">Memória institucional</div>
      <div className="mfield">
        <span className="text-[12px]">
          Aprendizados ACEITOS/PROMOVIDOS são herdados no clone (`herdado_de`);
          promovidos entram na base RAG <b>resultados</b> (A3)
        </span>
      </div>
    </>,
    [calibrar.data],
  );

  return (
    <div>
      <TituloTela
        titulo={
          <>
            Otimização &amp; Retro{" "}
            {apuracao && <span className="mchip-g align-middle">janela fechada ✓ apurado</span>}
            {propostas.data?.degradado && (
              <span className="mchip-w align-middle">optimize degradado (§10.6)</span>
            )}
          </>
        }
        subtitulo={`${pendentes.length} proposta(s) na fila · diff aprovável com impacto pré-simulado · apuração anti-peeking · clone com aprendizados`}
      />

      {propostas.error != null && <BannerErro erro={propostas.error} contexto="Propostas" />}
      {aprovar.error != null && <BannerErro erro={aprovar.error} contexto="Aprovar proposta" />}
      {rejeitar.error != null && <BannerErro erro={rejeitar.error} contexto="Rejeitar proposta" />}
      {clonar.error != null && <BannerErro erro={clonar.error} contexto="Clonar com aprendizados" />}
      {calibrar.error != null && <BannerErro erro={calibrar.error} contexto="Calibração" />}
      {apurar.error != null && !antiPeeking && (
        <BannerErro erro={apurar.error} contexto="Apuração" />
      )}

      <div className="flex flex-wrap items-start gap-3">
        {/* --------------------------------------- fila de next-best-change */}
        <div className="min-w-[340px] flex-[1.25]">
          <div className="mcard">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                Fila de next-best-change (Optimize) — ranqueada lift × esforço × risco
              </div>
              <BadgeViaAi
                rastro={{
                  agente: "optimize",
                  skill: "optimize@1.0",
                  evidencias: ["telemetria da OS", "sinais de rejeição"],
                  humano: "decidir é humano (§1.1.3)",
                }}
              />
            </div>

            {propostas.isLoading && (
              <div className="text-[12.5px] text-muted">Carregando propostas…</div>
            )}
            {!propostas.isLoading && lista.length === 0 && (
              <EstadoVazio>
                Sem propostas — o optimize propõe sobre a última versão SIMULADA do twin
                (rode o{" "}
                <Link to={`/os/${osId}/simulacao`} className="font-semibold text-blue underline">
                  Ensaio Geral (T8)
                </Link>
                ); com o hub LLM fora, a leitura degrada sem quebrar (§10.6).
              </EstadoVazio>
            )}

            {[...pendentes, ...decididas].map((p) => {
              const deltas = Object.entries(p.impacto.deltas).filter(
                ([, v]) => v !== null && v !== 0,
              );
              return (
                <div key={p.id} className="mfield block">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <b className="text-[13px]">{p.titulo}</b>
                    {p.estado === "proposta" ? (
                      <span className="mchip-b">na fila</span>
                    ) : p.estado === "aprovada" ? (
                      <span className="mchip-g">aprovada</span>
                    ) : (
                      <span className="mchip-r">rejeitada → sinal</span>
                    )}
                    <span className="flex-1" />
                    <span className="mchip-n" title="lift relativo / (esforço × risco)">
                      score {p.score.toLocaleString("pt-BR", { maximumFractionDigits: 4 })}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[12px] text-slatex">{p.motivacao}</div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11.5px]">
                    {deltas.map(([metrica, delta]) => {
                      const texto = fmtDelta(metrica, delta);
                      if (!texto) return null;
                      const bom = metrica === "custo" ? (delta ?? 0) < 0 : (delta ?? 0) > 0;
                      return (
                        <span key={metrica} className={bom ? "mchip-g" : "mchip-w"}>
                          {METRICA_ROTULO[metrica] ?? metrica} {texto}
                        </span>
                      );
                    })}
                    <ResumoDiff proposta={p} />
                    <span className="mchip-n">esforço {p.esforco}</span>
                    <span className="mchip-n">risco {p.risco.toLocaleString("pt-BR")}</span>
                    {p.impacto.semaforo_proposto && (
                      <span
                        className={
                          p.impacto.semaforo_proposto === "verde" ? "mchip-g" : "mchip-w"
                        }
                      >
                        pré-simulado: {p.impacto.semaforo_proposto}
                      </span>
                    )}
                  </div>

                  {p.estado === "proposta" && (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        className="mbtn-gd !px-2.5 !py-1 !text-[11.5px]"
                        disabled={aprovar.isPending}
                        title="Gera nova versão do twin + mini-ciclo M8→M9 expresso (nova aprovação)"
                        onClick={() => aprovar.mutate(p.id)}
                      >
                        {aprovar.isPending ? "Aprovando…" : "Aprovar"}
                      </button>
                      {rejeitandoId === p.id ? (
                        <>
                          <input
                            autoFocus
                            value={motivo}
                            onChange={(e) => setMotivo(e.target.value)}
                            placeholder="motivo (obrigatório — vira sinal)"
                            className="w-64 rounded-md border border-line2 px-2 py-1 text-[12px] outline-none focus:border-blue"
                          />
                          <button
                            type="button"
                            className="mbtn-rd !px-2.5 !py-1 !text-[11.5px]"
                            disabled={rejeitar.isPending || !motivo.trim()}
                            onClick={() => rejeitar.mutate({ propostaId: p.id, texto: motivo })}
                          >
                            Confirmar rejeição
                          </button>
                          <button
                            type="button"
                            className="mbtn-gh !px-2.5 !py-1 !text-[11.5px]"
                            onClick={() => setRejeitandoId(null)}
                          >
                            Cancelar
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          className="mbtn-gh !px-2.5 !py-1 !text-[11.5px]"
                          onClick={() => {
                            setRejeitandoId(p.id);
                            setMotivo("");
                          }}
                        >
                          Rejeitar
                        </button>
                      )}
                    </div>
                  )}
                  {p.estado === "rejeitada" && p.motivo_rejeicao && (
                    <div className="mt-1 text-[11.5px] text-muted">
                      motivo: “{p.motivo_rejeicao}” — alimenta o optimize na próxima rodada
                    </div>
                  )}
                </div>
              );
            })}

            <div className="mt-1 text-[11px] text-faint">
              Propor é a única ação autônoma do agente — aplicar exige humano +
              mini-aprovação expressa (§1.1.3 / §8-M11).
            </div>
          </div>

          {aprovada && (
            <div className="mcard mt-3 border-good/40 bg-good-soft/40">
              <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                Mini-ciclo M8→M9 expresso — v{aprovada.jornada.versao} criada (rascunho)
              </div>
              <div className="mt-1 text-[12px]">
                Nova versão <b>v{aprovada.jornada.versao}</b> (hash{" "}
                <span className="font-mono">{aprovada.jornada.hash.slice(0, 12)}…</span>) — nada
                publicado: o hash novo exige snapshot novo e aprovação EXPRESSA.
              </div>
              <ol className="mt-1.5 grid list-decimal gap-0.5 pl-5 text-[12px] text-slatex">
                {aprovada.mini_ciclo.passos.map((passo, i) => (
                  <li key={i} className="font-mono text-[11px]">
                    {passo}
                  </li>
                ))}
              </ol>
              <Link
                to={`/os/${osId}/simulacao`}
                className="mt-2 inline-block text-[12px] font-semibold text-blue underline"
              >
                Começar pelo Ensaio Geral (T8) →
              </Link>
            </div>
          )}
        </div>

        {/* ------------------------------------- apuração + retro + clone */}
        <div className="grid min-w-[320px] flex-1 gap-3">
          <div className="mcard">
            <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
              Apuração do experimento (anti-peeking §8-M11-A1/A2)
            </div>
            {!apuracao && (
              <button
                type="button"
                className="mbtn"
                disabled={apurar.isPending || !experimentoId}
                title={
                  experimentoId
                    ? "425 Too Early antes do fim da janela pré-registrada"
                    : "Sem experimento pré-registrado (T9)"
                }
                onClick={() => apurar.mutate()}
              >
                {apurar.isPending ? "Apurando…" : "Apurar experimento"}
              </button>
            )}
            {antiPeeking && (
              <div className="mt-2 rounded-md border border-warn-line bg-warn-bg px-3 py-2 text-[12px]">
                <b className="text-warn">⏳ 425 Too Early — anti-peeking respeitado.</b>{" "}
                {String(antiPeeking.problem.detail ?? "")}
                {fimJanela && (
                  <div className="mt-1 tabular-nums text-slatex">
                    Janela fecha em <b>{new Date(fimJanela).toLocaleString("pt-BR")}</b> — nenhum
                    lift é calculado antes disso.
                  </div>
                )}
              </div>
            )}
            {apuracao && (
              <div className="text-[12.5px]">
                <div className="text-[20px] font-extrabold tracking-[-.02em] text-good">
                  Lift{" "}
                  {apuracao.resultado.lift !== null
                    ? `${apuracao.resultado.lift >= 0 ? "+" : ""}${apuracao.resultado.lift.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}pp`
                    : "—"}{" "}
                  {apuracao.resultado.significativo ? (
                    <span className="mchip-g align-middle">significativo</span>
                  ) : (
                    <span className="mchip-w align-middle">não significativo</span>
                  )}
                </div>
                <div className="mt-0.5 text-slatex">
                  IC95:{" "}
                  {apuracao.resultado.ic95
                    ? `${apuracao.resultado.ic95[0].toLocaleString("pt-BR", { maximumFractionDigits: 1 })} a ${apuracao.resultado.ic95[1].toLocaleString("pt-BR", { maximumFractionDigits: 1 })}`
                    : "—"}{" "}
                  · ROAS realizado{" "}
                  <b>
                    {apuracao.resultado.roas?.toLocaleString("pt-BR", {
                      maximumFractionDigits: 1,
                    }) ?? "—"}
                    x
                  </b>{" "}
                  · resultado imutável (anti-p-hacking)
                </div>
                <div className="mt-1.5 text-[12px]">
                  Aprendizado <span className="font-mono">{apuracao.aprendizado.id.slice(0, 8)}…</span>{" "}
                  {apuracao.aprendizado.status === "promovido" ? (
                    <span className="mchip-g">promovido → base RAG resultados (A3)</span>
                  ) : (
                    <span className="mchip-b">{apuracao.aprendizado.status}</span>
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="mcard">
            <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
              Calibração do simulador (backtest obrigatório)
            </div>
            <div className="mb-2 text-[12px] text-slatex">
              O Calibrate compara previsto congelado × realizado e só publica priors novos
              se o erro (MAPE) melhora no backtest — versionado em `calibracao_prior`.
            </div>
            {calibrar.data ? (
              <div className="text-[12.5px]">
                <span className="mchip-g">priors v{calibrar.data.versao} publicados</span>{" "}
                <span className="mchip-n">
                  score {calibrar.data.score.toLocaleString("pt-BR")}
                </span>
                <div className="mt-1 text-[11.5px] text-muted">
                  backtest:{" "}
                  {JSON.stringify(calibrar.data.backtest).slice(0, 120)}
                  …
                </div>
              </div>
            ) : (
              <button
                type="button"
                className="mbtn-gh"
                disabled={calibrar.isPending}
                onClick={() => calibrar.mutate()}
              >
                {calibrar.isPending ? "Calibrando…" : "Publicar calibração (backtest)"}
              </button>
            )}
          </div>

          <div className="mcard">
            <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
              Clonar com aprendizados (§8-M11-A3)
            </div>
            {clonar.data ? (
              <div className="text-[12.5px]">
                <b>{clonar.data.os.codigo}</b> criada a partir da {clonar.data.origem.codigo} —{" "}
                <span className="mchip-g">
                  {clonar.data.herdados.aprendizados.length} aprendizado(s) herdado(s)
                </span>{" "}
                <span className="mchip-n">
                  priors v{String(clonar.data.herdados.priors["versao"] ?? "1")}
                </span>
                <div className="mt-1 grid gap-0.5 text-[11.5px] text-slatex">
                  {clonar.data.herdados.aprendizados.map((a) => (
                    <span key={a.id}>• “{a.texto}”</span>
                  ))}
                </div>
                <Link
                  to={`/os/${clonar.data.os.id}/briefing`}
                  className="mt-2 inline-block text-[12px] font-semibold text-blue underline"
                >
                  Abrir a nova OS ({clonar.data.os.codigo}) →
                </Link>
              </div>
            ) : (
              <>
                <div className="mb-2 text-[12px] text-slatex">
                  Nova OS herdando aprendizados ACEITOS/PROMOVIDOS (`herdado_de`) + priors
                  vigentes — a próxima campanha nasce mais inteligente.
                </div>
                <button
                  type="button"
                  className="mbtn-gd"
                  disabled={clonar.isPending}
                  onClick={() => clonar.mutate()}
                >
                  {clonar.isPending ? "Clonando…" : "⧉ Clonar com aprendizados"}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
