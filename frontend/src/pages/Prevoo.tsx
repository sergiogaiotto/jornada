/**
 * T11 · Plano de Compilação & Pré-voo (mock T11 / SDD §5.4, §8-M9): primeiro o plano
 * declarativo (criar/alterar/manter/destruir com avisos destrutivos), depois o apply
 * idempotente (externalKeys do hash, rollback compensatório) e a bateria de pré-voo
 * (pass/warn/fail — FAIL bloqueia o apply) + drift. Compilador é 100% determinístico
 * — LLM fora do caminho crítico; o Sync só traduz o diff para impacto de negócio.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { get, post } from "../lib/api";
import { rotuloFonte } from "../lib/format";
import { usePainelContextual } from "../lib/hooks";
import type {
  AcaoPlano,
  AmbienteSync,
  DriftCheckOut,
  LaunchOut,
  PreflightOut,
  SyncRunOut,
} from "../lib/types";
import { useProducao } from "../stores/producao";

const ACAO_CHIP: Record<AcaoPlano, string> = {
  criar: "mchip-g",
  alterar: "mchip-w",
  manter: "mchip-n",
  destruir: "mchip-r",
};

const STATUS_DOT: Record<string, string> = {
  pass: "text-good",
  warn: "text-warn",
  fail: "text-crit",
};

const SEMAFORO_CHIP: Record<string, string> = {
  verde: "mchip-g",
  amarelo: "mchip-w",
  vermelho: "mchip-r",
};

const ESTADO_RUN_CHIP: Record<SyncRunOut["estado"], string> = {
  pendente: "mchip-n",
  ok: "mchip-g",
  parcial: "mchip-w",
  revertido: "mchip-w",
  falhou: "mchip-r",
};

export function Prevoo() {
  const { id } = useParams<{ id: string }>();
  const osId = id ?? "";
  const navigate = useNavigate();

  const snapshot = useProducao((s) => s.snapshots[osId]);
  const setLaunch = useProducao((s) => s.setLaunch);

  const [ambiente, setAmbiente] = useState<AmbienteSync>("homolog");
  const [planRun, setPlanRun] = useState<SyncRunOut | null>(null);
  const [applyRun, setApplyRun] = useState<SyncRunOut | null>(null);
  const [preflight, setPreflight] = useState<PreflightOut | null>(null);

  const plan = useMutation({
    mutationFn: () => post<SyncRunOut>(`/snapshots/${snapshot.id}/plan?ambiente=${ambiente}`),
    onSuccess: (r) => {
      setPlanRun(r);
      setApplyRun(null);
    },
  });

  const apply = useMutation({
    mutationFn: () => post<SyncRunOut>(`/snapshots/${snapshot.id}/apply?ambiente=${ambiente}`),
    onSuccess: setApplyRun,
  });

  const rodarPreflight = useMutation({
    mutationFn: () => post<PreflightOut>(`/preflight/${snapshot.id}?ambiente=${ambiente}`),
    onSuccess: setPreflight,
  });

  const drift = useQuery({
    queryKey: ["drift", osId, ambiente],
    queryFn: ({ signal }) =>
      get<DriftCheckOut[]>(`/drift?ambiente=${ambiente}&os_id=${osId}`, signal),
    enabled: false, // on-demand (§5.4.5) — o GET grava drift_check
  });

  const armar = useMutation({
    mutationFn: () => post<LaunchOut>(`/launch/${snapshot.id}/armar`),
    onSuccess: (l) => {
      setLaunch(osId, l);
      navigate(`/os/${osId}/lancamento`);
    },
  });

  const plano = planRun?.plano ?? [];
  const contagens = plano.reduce<Record<string, number>>((acc, item) => {
    acc[item.acao] = (acc[item.acao] ?? 0) + 1;
    return acc;
  }, {});
  const comDrift = (drift.data ?? []).filter((d) => d.estado !== "em_sincronia");

  usePainelContextual(
    <>
      <div className="ctx-title">Log técnico (sync_run)</div>
      {planRun || applyRun ? (
        <div className="rounded-lg bg-claro p-3 font-mono text-[10.5px] leading-relaxed text-claro-paper">
          {planRun && (
            <>
              plan · {planRun.ambiente} · {planRun.estado}
              <br />
              recursos: {plano.length} · api_calls: {planRun.api_calls}
              <br />
            </>
          )}
          {applyRun && (
            <>
              apply · {applyRun.ambiente} · {applyRun.estado}
              <br />
              api_calls: {applyRun.api_calls} · retry/backoff: tenacity
              <br />
              idempotência: externalKey jrn-{"{hash}"}-{"{noId}"}
            </>
          )}
        </div>
      ) : (
        <div className="text-[12px] text-muted">Rode o plan para ver o log.</div>
      )}

      <div className="ctx-title">Sync — explicar em português</div>
      <Copiloto titulo="Sync">
        {planRun ? (
          <>
            O plano tem <b>{plano.length} recursos</b>
            {Object.entries(contagens).map(([acao, n], i) => (
              <span key={acao}>
                {i === 0 ? ": " : " · "}
                {n} a {acao}
              </span>
            ))}
            .{" "}
            {plano.some((i) => i.aviso) ? (
              <>
                Atenção aos <b>avisos destrutivos</b> — operações que reiniciam contatos
                em espera exigem leitura expressa (§5.4.3).
              </>
            ) : (
              "Nenhuma operação destrutiva — os contatos em espera não são afetados."
            )}{" "}
            Rollback compensatório automático se o apply falhar no meio.
          </>
        ) : (
          <>
            O compilador traduz o snapshot aprovado em recursos SFMC (DEs → Event
            Definitions → Assets → Journey) — mesmo hash da aprovação, plan antes de
            apply, zero LLM no caminho.
          </>
        )}
      </Copiloto>

      <div className="ctx-title">Regra do apply em prod</div>
      <div className="mfield">
        <span className="text-[12px]">
          Apply em <b>prod</b> exige: aprovação do cliente (T10) + certificado válido
          (M5) + pré-voo sem FAIL (§5.4.4) — recusas viram 409 com o motivo.
        </span>
      </div>
    </>,
    [planRun, applyRun, plano.length],
  );

  if (!snapshot) {
    return (
      <div>
        <TituloTela
          titulo="Plano de Compilação → SFMC"
          subtitulo="plan/apply determinístico · pré-voo · drift · armar lançamento"
        />
        <EstadoVazio>
          Nenhum snapshot nesta sessão —{" "}
          <Link to={`/os/${osId}/portoes`} className="font-semibold text-blue underline">
            monte o snapshot nos QA (T9)
          </Link>{" "}
          para compilar (o apply exige aprovação + certificado + pré-voo verde).
        </EstadoVazio>
      </div>
    );
  }

  return (
    <div>
      <TituloTela
        titulo={
          <>
            Plano de Compilação → SFMC{" "}
            {applyRun && (
              <span className={`${ESTADO_RUN_CHIP[applyRun.estado]} align-middle`}>
                apply {applyRun.estado}
              </span>
            )}
          </>
        }
        subtitulo={
          <>
            Mesmo hash aprovado: <span className="font-mono">{snapshot.hash.slice(0, 12)}…</span>{" "}
            · ambiente{" "}
            <b>{ambiente}</b> · idempotente por externalKey (re-apply ⇒ 0 mutações)
          </>
        }
      />

      {plan.error != null && <BannerErro erro={plan.error} contexto="Plan" />}
      {apply.error != null && <BannerErro erro={apply.error} contexto="Apply" />}
      {rodarPreflight.error != null && (
        <BannerErro erro={rodarPreflight.error} contexto="Pré-voo" />
      )}
      {drift.error != null && <BannerErro erro={drift.error} contexto="Drift" />}
      {armar.error != null && <BannerErro erro={armar.error} contexto="Armar lançamento" />}

      {/* ------------------------------------------------------------ ações */}
      <div className="mcard mb-3 flex flex-wrap items-center gap-2">
        <div className="flex overflow-hidden rounded-md border border-line2 text-[12px] font-bold">
          {(["homolog", "prod"] as const).map((amb) => (
            <button
              key={amb}
              type="button"
              onClick={() => {
                setAmbiente(amb);
                setPlanRun(null);
                setApplyRun(null);
                setPreflight(null);
              }}
              className={`px-3 py-1.5 ${ambiente === amb ? "bg-steel text-white" : "bg-white text-steel hover:bg-surface2"}`}
            >
              {amb}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="mbtn"
          disabled={plan.isPending}
          onClick={() => plan.mutate()}
        >
          {plan.isPending ? "Planejando…" : "1 · Gerar plano (plan)"}
        </button>
        <button
          type="button"
          className="mbtn-gh"
          disabled={rodarPreflight.isPending}
          onClick={() => rodarPreflight.mutate()}
        >
          {rodarPreflight.isPending ? "Verificando…" : "2 · Rodar pré-voo"}
        </button>
        <button
          type="button"
          className="mbtn"
          disabled={apply.isPending || planRun === null}
          title={planRun === null ? "Apply sem plan prévio → 409 (§8-M9-A1)" : undefined}
          onClick={() => apply.mutate()}
        >
          {apply.isPending ? "Aplicando…" : "3 · Apply"}
        </button>
        <button
          type="button"
          className="mbtn-gh"
          disabled={drift.isFetching}
          onClick={() => void drift.refetch()}
        >
          {drift.isFetching ? "Comparando…" : "Checar drift"}
        </button>
        <span className="flex-1" />
        <button
          type="button"
          className="mbtn-gd !px-4"
          disabled={armar.isPending}
          title="Exige APPLY OK do snapshot (§8-M10)"
          onClick={() => armar.mutate()}
        >
          {armar.isPending ? "Armando…" : "Armar lançamento →"}
        </button>
      </div>

      {/* ------------------------------------------------------------- plano */}
      {planRun === null && !plan.isPending && (
        <EstadoVazio>
          O <b>plano declarativo</b> vem antes de qualquer mutação: criar / alterar /
          manter / destruir por recurso SFMC, com externalKey derivada do hash e aviso
          para operações que reiniciam contatos em espera (§5.4).
        </EstadoVazio>
      )}

      {planRun !== null && (
        <div className="mcard mb-3 overflow-x-auto">
          <div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
            Plano declarativo · {planRun.ambiente}
            <span className={ESTADO_RUN_CHIP[planRun.estado]}>{planRun.estado}</span>
            <span className="font-normal normal-case tracking-normal">
              {Object.entries(contagens)
                .map(([acao, n]) => `${n} ${acao}`)
                .join(" · ")}
            </span>
          </div>
          <table className="w-full min-w-[560px] text-left text-[12px]">
            <thead>
              <tr className="border-b border-linesoft text-[10px] uppercase tracking-[.06em] text-faint">
                <th className="py-1 pr-3">Recurso SFMC (externalKey)</th>
                <th className="py-1 pr-3">Tipo</th>
                <th className="py-1 pr-3">Ação</th>
                <th className="py-1">Aviso</th>
              </tr>
            </thead>
            <tbody>
              {plano.map((item) => (
                <tr key={item.recurso} className="border-b border-linesoft align-top">
                  <td className="py-1.5 pr-3 font-mono text-[11px]">{item.recurso}</td>
                  <td className="py-1.5 pr-3">{item.tipo_sfmc}</td>
                  <td className="py-1.5 pr-3">
                    <span className={ACAO_CHIP[item.acao]}>{item.acao}</span>
                  </td>
                  <td className="py-1.5 text-[11.5px] text-warn">
                    {item.aviso ? `⚠ ${item.aviso}` : <span className="text-faint">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-start gap-3">
        {/* --------------------------------------------------- pré-voo */}
        <div className="mcard min-w-[320px] flex-[1.3]">
          <div className="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
            Checklist de paridade (pré-voo)
            {preflight && (
              <span className={SEMAFORO_CHIP[preflight.resultado]}>{preflight.resultado}</span>
            )}
          </div>
          {preflight ? (
            <div className="grid gap-1">
              {preflight.itens.map((item) => (
                <div key={item.item} className="flex items-start gap-2 text-[12px]">
                  <span className={`font-bold ${STATUS_DOT[item.status] ?? "text-faint"}`}>
                    {item.status === "pass" ? "✓" : item.status === "warn" ? "⚠" : "✗"}
                  </span>
                  <span>
                    <b>{rotuloFonte(item.item)}</b>{" "}
                    <span className="text-[11px] uppercase text-faint">{item.status}</span>
                  </span>
                </div>
              ))}
              <div className="mt-1 text-[11px] text-faint">
                FAIL ⇒ vermelho bloqueia o apply; prod exige pré-voo executado e
                não-vermelho (§5.4.4) · inclui re-varredura last-mile das 7 listas e
                dry-run com seed list.
              </div>
            </div>
          ) : (
            <div className="py-3 text-center text-[12.5px] text-muted">
              Bateria: DEs/schema · freshness Hybris · opt-in · listas last-mile · lint
              AMPscript · limites SFMC · drift=0 · seed dry-run.
            </div>
          )}
        </div>

        {/* ------------------------------------------------------ drift */}
        <div className="mcard min-w-[280px] flex-1">
          <div className="mb-2 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
            Monitor de drift ({ambiente})
          </div>
          {drift.data ? (
            comDrift.length === 0 ? (
              <div className="text-[12.5px] text-good">
                ✓ Zero divergência — twin e SFMC em sincronia ({drift.data.length} recursos
                verificados).
              </div>
            ) : (
              <div className="grid gap-1">
                {comDrift.map((d) => (
                  <div key={d.id} className="mfield !mb-0">
                    <span className="min-w-0 text-[12px]">
                      <span className="block truncate font-mono text-[11px]">{d.recurso}</span>
                      <span className="text-[11px] text-muted">
                        drift em prod abre pendência bloqueante (§8-M9-A4)
                      </span>
                    </span>
                    <span className="mchip-r">{d.estado}</span>
                  </div>
                ))}
              </div>
            )
          ) : (
            <div className="text-[12.5px] text-muted">
              Retrieve do estado real → decompila → compara por hash/campos — job de
              30min + on-demand (§5.4.5).
            </div>
          )}
          {applyRun && (
            <div className="mt-2 border-t border-linesoft pt-2 text-[11.5px] text-slatex">
              Apply <span className={ESTADO_RUN_CHIP[applyRun.estado]}>{applyRun.estado}</span>{" "}
              · {applyRun.api_calls} chamadas de API · re-execução com o mesmo hash ⇒ 0
              mutações (§8-M9-A3).
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
