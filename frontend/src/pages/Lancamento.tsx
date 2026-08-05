/**
 * T12 · Torre de Lançamento (mock T12 / SDD §8-M10): disparo nunca é binário — rampa
 * 1% → 10% → 100% com QA automático entre ondas (breakers da política CONGELADOS
 * no armar). Breaker disparado ⇒ rampa congela sozinha (a única ação autônoma é a
 * conservadora); retomar é sempre humano (SEV1 exige 2 aprovadores). Kill switch em
 * 2 etapas. Caminho 100% determinístico — zero LLM.
 */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { ApiError, post } from "../lib/api";
import { usePainelContextual } from "../lib/hooks";
import type {
  DisparoBreaker,
  EstadoLaunch,
  KillOut,
  LaunchOut,
  RetomarOut,
} from "../lib/types";
import { useProducao } from "../stores/producao";

const ESTADO_CHIP: Record<EstadoLaunch, { chip: string; rotulo: string }> = {
  armado: { chip: "mchip-b", rotulo: "ARMADO" },
  em_rampa: { chip: "mchip-g", rotulo: "● NO AR" },
  pausado_breaker: { chip: "mchip-w", rotulo: "‖ PAUSADO (breaker)" },
  morto: { chip: "mchip-r", rotulo: "■ MORTO" },
  concluido: { chip: "mchip-g", rotulo: "✓ CONCLUÍDO" },
};

const BREAKER_ROTULO: Record<string, string> = {
  optout_pct_max: "Opt-out",
  bounce_pct_max: "Bounce e-mail",
  erro_entrega_pct_max: "Erro de entrega",
  burn_rate_max: "Burn-rate vs projetado",
};

const EVENTO_ROTULO: Record<string, string> = {
  armado: "⛽ torre armada",
  onda_avancada: "🌊 onda avançada",
  breaker_disparado: "🛑 breaker disparado",
  kill_solicitado: "⚠ kill solicitado (etapa 1)",
  kill_confirmado: "■ kill confirmado (etapa 2)",
  kill_automatico: "■ kill AUTOMÁTICO (SEV1)",
  retomada_aprovada: "✋ aprovação de retomada",
  retomada: "▶ retomada",
  concluido: "🏁 rampa concluída",
};

/** Disparos do 409 BreakerDisparado (extra `disparos` do RFC-7807). */
function disparosDoErro(erro: unknown): DisparoBreaker[] {
  if (erro instanceof ApiError && Array.isArray(erro.problem["disparos"])) {
    return erro.problem["disparos"] as DisparoBreaker[];
  }
  return [];
}

export function Lancamento() {
  const { id } = useParams<{ id: string }>();
  const osId = id ?? "";

  const launch = useProducao((s) => s.launches[osId]);
  const setLaunch = useProducao((s) => s.setLaunch);

  const [tokenKill, setTokenKill] = useState<string | null>(null);

  const avancar = useMutation({
    mutationFn: () => post<LaunchOut>(`/launch/${launch.id}/avancar-onda`),
    onSuccess: (l) => setLaunch(osId, l),
  });

  const kill = useMutation({
    mutationFn: (confirmacao: string | null) =>
      post<KillOut>(`/launch/${launch.id}/kill`, { confirmacao }),
    onSuccess: (r) => {
      setLaunch(osId, r.launch);
      setTokenKill(r.etapa === 1 ? r.confirmacao : null);
    },
  });

  const retomar = useMutation({
    mutationFn: () => post<RetomarOut>(`/launch/${launch.id}/retomar`),
    onSuccess: (r) => setLaunch(osId, r.launch),
  });

  const disparos = [
    ...disparosDoErro(avancar.error),
    ...(launch?.eventos ?? [])
      .filter((e) => e.tipo === "breaker_disparado")
      .flatMap((e) => (Array.isArray(e["disparos"]) ? (e["disparos"] as DisparoBreaker[]) : [])),
  ];
  const eventos = [...(launch?.eventos ?? [])].reverse();
  const retomarInfo = retomar.data;

  usePainelContextual(
    <>
      <div className="ctx-title">Copiloto de plantão</div>
      <Copiloto titulo="Vigia">
        {launch == null ? (
          <>A Torre arma após o apply verde do snapshot (T11).</>
        ) : launch.estado === "em_rampa" ? (
          <>
            Onda <b>{launch.onda_atual}</b> de {launch.ondas.length} no ar. Breakers
            avaliados a cada evento de telemetria e a cada avanço de onda — tudo nominal
            até aqui. O QA da próxima onda é automático (§8-M10).
          </>
        ) : launch.estado === "pausado_breaker" ? (
          <>
            Rampa <b>congelada pelo breaker</b> — a única ação autônoma é a conservadora.
            Retomar é sempre humano (líder/aprovador; SEV1 exige 2 distintos).
          </>
        ) : launch.estado === "morto" ? (
          <>
            Kill executado — jornada pausada no SFMC. Retomada exige alçada (2 aprovadores
            se houver SEV1 aberto).
          </>
        ) : launch.estado === "concluido" ? (
          <>Rampa 100% concluída sem breaker — acompanhe o previsto × realizado (T13).</>
        ) : (
          <>Torre armada — avance a onda 1 (1%) para iniciar o disparo canário.</>
        )}
      </Copiloto>

      <div className="ctx-title">QA da próxima onda</div>
      <div className="mfield">
        <span className="text-[12px]">
          Avança só se os breakers seguirem verdes · retomada pós-breaker exige humano ·
          SEV1 exige <b>2 aprovadores distintos</b> (§10.5)
        </span>
      </div>

      <div className="ctx-title">Registro</div>
      <div className="mfield">
        <span className="text-[12px]">
          Toda intervenção automática gera incidente tipado + evento no dossiê
          (actor <b>sistema</b>, via_ai=false — §10.6: zero LLM no caminho crítico)
        </span>
      </div>
    </>,
    [launch?.estado, launch?.onda_atual],
  );

  if (!launch) {
    return (
      <div>
        <TituloTela
          titulo="Torre de Lançamento"
          subtitulo="Rampa canário 1% → 10% → 100% · breakers automáticos · kill switch em 2 etapas"
        />
        <EstadoVazio>
          Nenhum launch armado nesta sessão —{" "}
          <Link to={`/os/${osId}/prevoo`} className="font-semibold text-blue underline">
            conclua o apply no Pré-voo (T11)
          </Link>{" "}
          e clique em <b>Armar lançamento</b> (exige APPLY OK — §8-M10).
        </EstadoVazio>
      </div>
    );
  }

  const estado = ESTADO_CHIP[launch.estado];

  return (
    <div>
      <TituloTela
        titulo={
          <>
            Torre de Lançamento{" "}
            <span className={`${estado.chip} align-middle`}>
              {estado.rotulo}
              {launch.estado === "em_rampa" && ` · onda ${launch.onda_atual}/${launch.ondas.length}`}
            </span>
          </>
        }
        subtitulo="Breakers congelados da política no armar · rampa congela sozinha; retomar/abortar é sempre humano"
      />

      {avancar.error != null && <BannerErro erro={avancar.error} contexto="QA da onda" />}
      {kill.error != null && <BannerErro erro={kill.error} contexto="Kill switch" />}
      {retomar.error != null && <BannerErro erro={retomar.error} contexto="Retomada" />}

      {/* --------------------------------------------------------- rampa */}
      <div className="mcard mb-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {launch.ondas.map((onda, i) => {
            const n = i + 1;
            const concluida =
              n < launch.onda_atual ||
              (n === launch.onda_atual && launch.estado === "concluido");
            const corrente = n === launch.onda_atual && launch.estado !== "concluido";
            const cor = concluida
              ? "bg-good text-white"
              : corrente
                ? launch.estado === "em_rampa"
                  ? "bg-blue text-white"
                  : "bg-warn text-white"
                : "bg-[#E9EEF3] text-slatex";
            return (
              <div key={n} className="flex min-w-0 items-center gap-1.5" style={{ flexGrow: onda.pct }}>
                <div className={`min-w-0 flex-1 rounded-md px-2.5 py-1.5 text-[11.5px] ${cor}`}>
                  <b>
                    Onda {n} · {onda.pct}%
                  </b>{" "}
                  {concluida
                    ? "· concluída ✓ QA ok"
                    : corrente
                      ? launch.estado === "em_rampa"
                        ? "· em andamento · breakers ok"
                        : `· ${launch.estado}`
                      : "· aguarda QA automático"}
                </div>
                {i < launch.ondas.length - 1 && <span className="text-ghost">→</span>}
              </div>
            );
          })}
        </div>
        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="mbtn"
            disabled={
              avancar.isPending ||
              launch.estado === "morto" ||
              launch.estado === "concluido" ||
              launch.estado === "pausado_breaker"
            }
            onClick={() => avancar.mutate()}
          >
            {avancar.isPending
              ? "Checando breakers…"
              : launch.onda_atual >= launch.ondas.length
                ? "Concluir rampa"
                : `Avançar → onda ${launch.onda_atual + 1} (${launch.ondas[launch.onda_atual]?.pct}%)`}
          </button>

          {(launch.estado === "pausado_breaker" || launch.estado === "morto") && (
            <button
              type="button"
              className="mbtn-gh"
              disabled={retomar.isPending}
              title="Sempre humano (§8-M10-A1) — exige papel líder/aprovador; SEV1 exige 2 distintos"
              onClick={() => retomar.mutate()}
            >
              {retomar.isPending ? "Retomando…" : "Retomar (humano)"}
            </button>
          )}
          {retomarInfo && !retomarInfo.retomado && (
            <span className="mchip-w">
              {retomarInfo.aprovacoes}/{retomarInfo.exigidas} aprovações — aguarda 2º
              aprovador distinto (SEV1)
            </span>
          )}

          <span className="flex-1" />

          {tokenKill === null ? (
            <button
              type="button"
              className="mbtn-rd"
              disabled={
                kill.isPending || launch.estado === "morto" || launch.estado === "concluido"
              }
              onClick={() => kill.mutate(null)}
            >
              ■ KILL SWITCH
            </button>
          ) : (
            <span className="flex items-center gap-2 rounded-md border border-crit/40 bg-crit-soft px-2.5 py-1.5">
              <span className="text-[11.5px] font-bold text-crit">
                Etapa 2 — confirmar kill? Pausa a jornada no SFMC.
              </span>
              <button
                type="button"
                className="mbtn-rd !px-2.5 !py-1 !text-[11px]"
                disabled={kill.isPending}
                onClick={() => kill.mutate(tokenKill)}
              >
                Confirmar KILL
              </button>
              <button
                type="button"
                className="mbtn-gh !px-2.5 !py-1 !text-[11px]"
                onClick={() => setTokenKill(null)}
              >
                Cancelar
              </button>
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-start gap-3">
        {/* ---------------------------------------------------- breakers */}
        <div className="mcard min-w-[300px] flex-1">
          <div className="mb-2 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
            Circuit breakers (política congelada no armar)
          </div>
          <div className="grid gap-1.5 text-[12px]">
            {Object.entries(launch.breakers).map(([nome, limite]) => {
              const disparado = disparos.find((d) => nome.startsWith(d.breaker));
              return (
                <div key={nome} className="flex items-baseline justify-between gap-2">
                  <span>
                    <span className={`font-bold ${disparado ? "text-crit" : "text-good"}`}>
                      {disparado ? "✗" : "✓"}
                    </span>{" "}
                    {BREAKER_ROTULO[nome] ?? rotulo(nome)}
                    {disparado && (
                      <span className="ml-1 text-[11px] text-crit">
                        {disparado.valor.toLocaleString("pt-BR")} acima do limite
                      </span>
                    )}
                  </span>
                  <span className="tabular-nums text-faint">
                    limite {Number(limite).toLocaleString("pt-BR")}
                    {nome.includes("pct") ? "%" : nome.includes("burn") ? "×" : ""}
                  </span>
                </div>
              );
            })}
            <div className="flex items-baseline justify-between gap-2">
              <span>
                <span className="font-bold text-good">✓</span> Disparo p/ lista de exclusão
              </span>
              <span className="tabular-nums text-faint">SEV1 + kill automático se &gt; 0</span>
            </div>
          </div>
          {disparos.length > 0 && (
            <div className="mt-2 rounded-md border border-crit/40 bg-crit-soft px-2.5 py-1.5 text-[11.5px] text-crit">
              {disparos.slice(0, 3).map((d, i) => (
                <span key={i} className="block">
                  <b>{d.breaker}</b> ({d.sev}
                  {d.kill ? " · kill automático" : ""}): {d.detalhe}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* -------------------------------------------- registro da rampa */}
        <div className="mcard min-w-[300px] flex-1">
          <div className="mb-2 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
            Registro da rampa (auditável · launch.eventos)
          </div>
          {eventos.length === 0 ? (
            <div className="text-[12.5px] text-muted">— sem eventos —</div>
          ) : (
            <div className="grid max-h-64 gap-1 overflow-y-auto text-[12px]">
              {eventos.map((e, i) => (
                <div
                  key={i}
                  className="flex items-baseline justify-between gap-2 rounded-md bg-surface2 px-2.5 py-1"
                >
                  <span>
                    {EVENTO_ROTULO[e.tipo] ?? e.tipo}
                    {e["onda"] != null && (
                      <b>
                        {" "}
                        {String(e["onda"])} ({String(e["pct"])}%)
                      </b>
                    )}
                  </span>
                  <span className="whitespace-nowrap text-[10.5px] text-faint">
                    {e.por} ·{" "}
                    {e.em ? new Date(e.em).toLocaleTimeString("pt-BR") : "—"}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className="mt-2 border-t border-linesoft pt-1.5 text-[11px] text-faint">
            Telemetria real chega pelo webhook ENS (assinatura HMAC) e avalia os breakers
            a cada lote — acompanhe os KPIs em{" "}
            <Link to={`/os/${osId}/monitor`} className="font-semibold text-blue underline">
              previsto × realizado (T13)
            </Link>
            .
          </div>
        </div>
      </div>
    </div>
  );
}

function rotulo(nome: string): string {
  return nome.split("_").join(" ");
}
