/**
 * T13 · Monitoramento Vivo — previsto × realizado (mock T13 / SDD §8-M10 §1.1.2):
 * TODO KPI é um PAR contra o Previsto CONGELADO do snapshot (nunca a simulação
 * corrente). Gramática visual universal: barra fantasma (previsto) sob barra sólida
 * (realizado) — Recharts. Telemetria dupla reconciliada (ENS tempo real; extract é
 * conciliação, não soma). Zero LLM neste caminho — o Insight apenas NARRA no painel.
 */
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, Kpi, TituloTela } from "../components/ui/basics";
import { ApiError, get } from "../lib/api";
import { fmtBRL, fmtCompacto, fmtInt } from "../lib/format";
import { usePainelContextual } from "../lib/hooks";
import type { MonitorOut } from "../lib/types";

const CANAL_ROTULO: Record<string, string> = {
  email: "E-mail",
  push: "Push",
  sms: "SMS",
  whatsapp: "WhatsApp",
  rcs: "RCS",
};

/** Cores da paleta de gráficos validada (tailwind ch1..ch4 / mock). */
const COR_PREVISTO = "#C9D3DD"; // fantasma
const COR_REALIZADO = "#3A66D6"; // sólida (ch1)
const COR_CUSTO = "#7A5AD9"; // ch4

function deltaPct(previsto: number | null | undefined, realizado: number | null | undefined) {
  if (!previsto || realizado === null || realizado === undefined) return null;
  return ((realizado - previsto) / previsto) * 100;
}

function ChipDelta({ delta }: { delta: number | null }) {
  if (delta === null) return null;
  const positivo = delta >= 0;
  return (
    <b className={positivo ? "text-good" : "text-crit"}>
      {positivo ? "+" : ""}
      {delta.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%
    </b>
  );
}

function fmtX(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${n.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}x`;
}

export function Monitor() {
  const { id } = useParams<{ id: string }>();
  const osId = id ?? "";

  const monitor = useQuery({
    queryKey: ["os", osId, "monitor"],
    queryFn: ({ signal }) => get<MonitorOut>(`/os/${osId}/monitor`, signal),
    enabled: Boolean(osId),
    refetchInterval: 30_000, // telemetria viva — ENS near-real-time (§8-M10)
    retry: (falhas, erro) => !(erro instanceof ApiError && erro.status === 409) && falhas < 2,
  });

  const m = monitor.data;
  const kpis = m?.kpis;
  const lift = kpis?.lift_pp.realizado;
  const roasDelta = deltaPct(kpis?.roas.previsto?.p50, kpis?.roas.realizado);
  const convDelta = deltaPct(kpis?.conversoes.previsto?.p50, kpis?.conversoes.realizado);

  const canais = Object.entries(m?.canais ?? {});
  const dadosDisparos = canais.map(([canal, c]) => ({
    canal: CANAL_ROTULO[canal] ?? canal,
    previsto: c.disparos.previsto ?? 0,
    realizado: c.disparos.realizado,
  }));
  const dadosCusto = canais.map(([canal, c]) => ({
    canal: CANAL_ROTULO[canal] ?? canal,
    previsto: c.custo.previsto ?? 0,
    realizado: c.custo.realizado,
  }));

  // KPIs normalizados: previsto (P50) = 100 (fantasma) × realizado em % da régua
  const dadosKpis = kpis
    ? (
        [
          ["Conversões", kpis.conversoes.previsto?.p50, kpis.conversoes.realizado],
          ["Lift (pp)", kpis.lift_pp.previsto?.p50, lift?.valor_pp],
          ["ROAS", kpis.roas.previsto?.p50, kpis.roas.realizado],
          ["Custo", kpis.custo.previsto?.p50, kpis.custo.realizado],
          ["Receita", kpis.receita.previsto?.p50, kpis.receita.realizado],
        ] as const
      )
        .filter(([, prev, real]) => Boolean(prev) && real !== null && real !== undefined)
        .map(([nome, prev, real]) => ({
          kpi: nome,
          previsto: 100,
          realizado: Math.round((Number(real) / Number(prev)) * 1000) / 10,
        }))
    : [];

  const feedDesvios = canais
    .map(([canal, c]) => ({
      canal: CANAL_ROTULO[canal] ?? canal,
      delta: deltaPct(c.disparos.previsto, c.disparos.realizado),
    }))
    .filter((d): d is { canal: string; delta: number } => d.delta !== null)
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    .slice(0, 3);

  usePainelContextual(
    <>
      <div className="ctx-title">Insight de plantão</div>
      <Copiloto titulo="Insight">
        {m ? (
          <>
            {roasDelta !== null && (
              <>
                ROAS <b>{fmtX(kpis?.roas.realizado)}</b> veio{" "}
                <b>
                  {Math.abs(roasDelta).toLocaleString("pt-BR", { maximumFractionDigits: 0 })}%{" "}
                  {roasDelta >= 0 ? "acima" : "abaixo"}
                </b>{" "}
                do previsto congelado ({fmtX(kpis?.roas.previsto?.p50)}).{" "}
              </>
            )}
            {lift?.valor_pp != null && (
              <>
                Lift vs holdout <b>+{lift.valor_pp.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}pp</b>
                {lift.significativo
                  ? " — significativo (IC exclui zero)."
                  : " — ainda sem significância."}{" "}
              </>
            )}
            O erro previsto×realizado alimenta o Calibrate (T15).
          </>
        ) : (
          <>O monitor compara TODO KPI contra a régua congelada no Ensaio Geral (§1.1.2).</>
        )}
      </Copiloto>

      <div className="ctx-title">Feed de desvios (disparos)</div>
      {feedDesvios.length > 0 ? (
        feedDesvios.map((d) => (
          <div key={d.canal} className="mfield">
            <span className="text-[12px]">
              <b>{d.canal}</b> — {d.delta >= 0 ? "+" : ""}
              {d.delta.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% vs previsto
            </span>
            <span className={Math.abs(d.delta) > 15 ? "mchip-w" : "mchip-g"}>
              {d.delta >= 0 ? "↑" : "↓"}
            </span>
          </div>
        ))
      ) : (
        <div className="text-[12px] text-muted">— sem telemetria —</div>
      )}

      <div className="ctx-title">Reconciliação ENS × extract</div>
      <div className="mfield">
        <span className="text-[12px]">
          {m
            ? `${fmtCompacto(m.fontes.ens)} eventos ENS · ${fmtCompacto(m.fontes.extract)} extract`
            : "—"}
        </span>
        {m &&
          (m.reconciliacao.divergente ? (
            <span className="mchip-w">&gt;{m.reconciliacao.limite_pct}%</span>
          ) : (
            <span className="mchip-g">ok</span>
          ))}
      </div>

      <div className="ctx-title">Pergunte aos dados</div>
      <div className="mfield">
        <span className="text-[12px]">
          Explore estes números em linguagem natural —{" "}
          <Link to={`/os/${osId}/perguntas`} className="font-semibold text-blue underline">
            camada semântica (T14)
          </Link>
        </span>
      </div>
    </>,
    [m, osId],
  );

  if (monitor.error instanceof ApiError && monitor.error.status === 409) {
    return (
      <div>
        <TituloTela
          titulo="Monitoramento Vivo"
          subtitulo="Todo KPI como par previsto × realizado — contra o Previsto congelado (§1.1.2)"
        />
        <EstadoVazio>
          OS sem snapshot com <b>Previsto congelado</b> — rode o{" "}
          <Link to={`/os/${osId}/simulacao`} className="font-semibold text-blue underline">
            Ensaio Geral (T8)
          </Link>
          , congele o Previsto e monte o snapshot nos{" "}
          <Link to={`/os/${osId}/portoes`} className="font-semibold text-blue underline">
            Portões (T9)
          </Link>{" "}
          — o monitor só existe contra a régua congelada (§8-M10).
        </EstadoVazio>
      </div>
    );
  }

  return (
    <div>
      <TituloTela
        titulo={
          <>
            Monitoramento Vivo{" "}
            {m?.launch?.estado === "em_rampa" && (
              <span className="mchip-g align-middle">
                ● Ao Vivo · onda {m.launch.onda_atual}/{m.launch.ondas.length}
              </span>
            )}
            {m?.launch?.estado === "pausado_breaker" && (
              <span className="mchip-w align-middle">‖ pausado (breaker)</span>
            )}
            {m && !m.launch && <span className="mchip-n align-middle">sem launch armado</span>}
          </>
        }
        subtitulo={
          m ? (
            <>
              {m.os.codigo} · previsto congelado em{" "}
              {m.snapshot.previsto_congelado_em
                ? new Date(m.snapshot.previsto_congelado_em).toLocaleDateString("pt-BR")
                : "—"}{" "}
              · snapshot <span className="font-mono">{m.snapshot.hash.slice(0, 12)}…</span> ·
              barra fantasma = previsto, sólida = realizado
            </>
          ) : (
            "Todo KPI como par previsto × realizado (barra fantasma + sólida)"
          )
        }
      />

      {monitor.error != null && <BannerErro erro={monitor.error} contexto="Monitor" />}
      {monitor.isLoading && <EstadoVazio>Carregando telemetria…</EstadoVazio>}

      {m && kpis && (
        <>
          {/* ------------------------------------------------------- KPIs */}
          <div className="mb-3 flex flex-wrap gap-3">
            <Kpi
              rotulo="Conversões"
              valor={fmtInt(kpis.conversoes.realizado)}
              detalhe={
                <>
                  prev. {fmtInt(Math.round(kpis.conversoes.previsto?.p50 ?? 0))} ·{" "}
                  <ChipDelta delta={convDelta} />
                </>
              }
            />
            <Kpi
              rotulo="Lift vs holdout"
              valor={
                lift?.valor_pp != null
                  ? `+${lift.valor_pp.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}pp`
                  : "—"
              }
              detalhe={
                lift?.ic95_pp ? (
                  <>
                    prev. +{kpis.lift_pp.previsto?.p50?.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}pp
                    · IC95: {lift.ic95_pp[0].toLocaleString("pt-BR", { maximumFractionDigits: 1 })} a{" "}
                    {lift.ic95_pp[1].toLocaleString("pt-BR", { maximumFractionDigits: 1 })}{" "}
                    {lift.significativo ? (
                      <span className="mchip-g">significativo</span>
                    ) : (
                      <span className="mchip-n">sem significância</span>
                    )}
                  </>
                ) : (
                  (lift?.detalhe ?? "—")
                )
              }
              tom="good"
            />
            <Kpi
              rotulo="ROAS"
              valor={fmtX(kpis.roas.realizado)}
              detalhe={
                <>
                  prev. {fmtX(kpis.roas.previsto?.p50)} · <ChipDelta delta={roasDelta} />
                </>
              }
              tom="good"
            />
            <Kpi
              rotulo="Custo real"
              valor={fmtBRL(kpis.custo.realizado, 0)}
              detalhe={<>prev. {fmtBRL(kpis.custo.previsto?.p50, 0)} (P50 congelado)</>}
            />
            <Kpi
              rotulo="Receita"
              valor={fmtBRL(kpis.receita.realizado, 0)}
              detalhe={<>prev. {fmtBRL(kpis.receita.previsto?.p50, 0)}</>}
              tom="good"
            />
          </div>

          {m.reconciliacao.alertas.length > 0 && (
            <div className="mcard mb-3 border-warn-line bg-warn-bg">
              <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                Alertas abertos
              </div>
              <div className="mt-1 text-[12.5px]">
                {m.reconciliacao.alertas.map((a) => (
                  <span key={a.id} className="block">
                    <span className="mchip-w mr-1.5 uppercase">{a.sev}</span>
                    {a.titulo}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="mb-3 flex flex-wrap items-start gap-3">
            {/* --------------------------- KPIs vs régua (fantasma × sólida) */}
            <div className="mcard min-w-[320px] flex-1">
              <div className="mb-1 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                KPIs em % do previsto congelado (fantasma = 100)
              </div>
              <ResponsiveContainer width="100%" height={210}>
                <BarChart data={dadosKpis} barGap={2}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EDF1F5" vertical={false} />
                  <XAxis dataKey="kpi" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 10 }} unit="%" width={40} />
                  <Tooltip
                    formatter={(v: number, nome: string) => [
                      `${v.toLocaleString("pt-BR")}%`,
                      nome === "previsto" ? "previsto (P50)" : "realizado",
                    ]}
                  />
                  <ReferenceLine y={100} stroke="#182230" strokeDasharray="4 2" />
                  <Bar dataKey="previsto" name="previsto" fill={COR_PREVISTO} radius={[3, 3, 0, 0]} />
                  <Bar dataKey="realizado" name="realizado" fill={COR_REALIZADO} radius={[3, 3, 0, 0]} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* ------------------------------------------ disparos por canal */}
            <div className="mcard min-w-[320px] flex-1">
              <div className="mb-1 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                Disparos por canal — previsto × realizado
              </div>
              <ResponsiveContainer width="100%" height={210}>
                <BarChart data={dadosDisparos} barGap={2}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EDF1F5" vertical={false} />
                  <XAxis dataKey="canal" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 10 }} width={44} tickFormatter={(v) => fmtCompacto(v)} />
                  <Tooltip formatter={(v: number) => fmtInt(v)} />
                  <Bar dataKey="previsto" name="previsto" fill={COR_PREVISTO} radius={[3, 3, 0, 0]} />
                  <Bar dataKey="realizado" name="realizado" fill={COR_REALIZADO} radius={[3, 3, 0, 0]} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="flex flex-wrap items-start gap-3">
            {/* ------------------------------------------------ custo por canal */}
            <div className="mcard min-w-[320px] flex-1">
              <div className="mb-1 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                Custo por canal (R$) — previsto × realizado
              </div>
              <ResponsiveContainer width="100%" height={190}>
                <BarChart data={dadosCusto} layout="vertical" barGap={2}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#EDF1F5" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => fmtCompacto(v)} />
                  <YAxis type="category" dataKey="canal" tick={{ fontSize: 11 }} width={72} />
                  <Tooltip formatter={(v: number) => fmtBRL(v)} />
                  <Bar dataKey="previsto" name="previsto" fill={COR_PREVISTO} radius={[0, 3, 3, 0]} />
                  <Bar dataKey="realizado" name="realizado" fill={COR_CUSTO} radius={[0, 3, 3, 0]} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                </BarChart>
              </ResponsiveContainer>
              <table className="w-full text-left text-[11.5px]">
                <thead>
                  <tr className="border-b border-linesoft text-[10px] uppercase tracking-[.06em] text-faint">
                    <th className="py-1 pr-2">Canal</th>
                    <th className="py-1 pr-2 text-right">Disparos</th>
                    <th className="py-1 pr-2 text-right">Custo real</th>
                    <th className="py-1 pr-2 text-right">vs previsto</th>
                  </tr>
                </thead>
                <tbody>
                  {canais.map(([canal, c]) => {
                    const delta = deltaPct(c.custo.previsto, c.custo.realizado);
                    return (
                      <tr key={canal} className="border-b border-linesoft">
                        <td className="py-1 pr-2 font-semibold">{CANAL_ROTULO[canal] ?? canal}</td>
                        <td className="py-1 pr-2 text-right tabular-nums">
                          {fmtInt(c.disparos.realizado)}
                        </td>
                        <td className="py-1 pr-2 text-right tabular-nums">
                          {fmtBRL(c.custo.realizado)}
                        </td>
                        <td className="py-1 pr-2 text-right tabular-nums">
                          <ChipDelta delta={delta} />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* ---------------------------------- metas × realizado + reconciliação */}
            <div className="mcard min-w-[320px] flex-1">
              <div className="mb-2 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                Metas do briefing × realizado
              </div>
              {Object.entries(m.metas).length === 0 && (
                <div className="text-[12px] text-muted">Briefing sem metas numéricas.</div>
              )}
              {Object.entries(m.metas).map(([nome, par]) => {
                const alvo = Number(par.previsto ?? 0);
                const real = par.realizado;
                const pct = alvo > 0 && real != null ? (Number(real) / alvo) * 100 : null;
                return (
                  <div key={nome} className="mb-1.5 text-[12px]">
                    <div className="flex items-baseline justify-between">
                      <span className="font-semibold capitalize">{nome.split("_").join(" ")}</span>
                      <span className="tabular-nums">
                        {real != null ? Number(real).toLocaleString("pt-BR") : "—"} · meta{" "}
                        {alvo.toLocaleString("pt-BR")}{" "}
                        {pct !== null && (
                          <b className={pct >= 100 ? "text-good" : "text-warn"}>
                            {Math.round(pct)}%
                          </b>
                        )}
                      </span>
                    </div>
                    <div className="mbar relative">
                      <i
                        className={pct !== null && pct >= 100 ? "bg-good" : "bg-blue"}
                        style={{ width: `${Math.min(100, (pct ?? 0) * 0.66)}%` }}
                      />
                      {/* marcador da meta (fantasma) — gramática do mock */}
                      <span className="absolute top-[-2px] h-[11px] w-[2px] bg-ink" style={{ left: "66%" }} />
                    </div>
                  </div>
                );
              })}

              <div className="mb-1 mt-3 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                Reconciliação ENS × extract (limite {m.reconciliacao.limite_pct}%)
              </div>
              <div className="grid gap-1 text-[12px]">
                {Object.entries(m.reconciliacao.por_tipo).map(([tipo, r]) => (
                  <div key={tipo} className="flex items-baseline justify-between gap-2">
                    <span>
                      <span className={`font-bold ${r.acima_limite ? "text-crit" : "text-good"}`}>
                        {r.acima_limite ? "✗" : "✓"}
                      </span>{" "}
                      {tipo}
                    </span>
                    <span className="tabular-nums text-faint">
                      ENS {fmtCompacto(r.ens)} · extract {fmtCompacto(r.extract)} ·{" "}
                      {r.divergencia_pct.toLocaleString("pt-BR")}%
                    </span>
                  </div>
                ))}
              </div>

              <div className="mt-2 border-t border-linesoft pt-1.5 text-[11px] text-faint">
                {m.premissas.map((p, i) => (
                  <span key={i} className="block">
                    • {p}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
