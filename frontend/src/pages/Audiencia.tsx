/**
 * T5 · Estúdio de Audiência (mock T5 / SDD §8-M5): waterfall base→líquido pós-compliance
 * com recontagem dinâmica, SQL dinâmico do Engineer (via_ai, explicação por cláusula),
 * holdout (slider, política valida o mínimo) e certificação do Guard determinístico
 * (7 listas + opt-in → certificado com hash e validade).
 */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { BadgeViaAi } from "../components/ai/BadgeViaAi";
import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { ApiError, post, put } from "../lib/api";
import { fmtCompacto, fmtInt, rotuloFonte, tempoRelativo } from "../lib/format";
import { usePainelContextual } from "../lib/hooks";
import type { CertificadoOut, GerarSqlOut, SegmentoOut } from "../lib/types";
import { useProducao } from "../stores/producao";

const CANAL_ROTULO: Record<string, string> = {
  email: "E-mail",
  sms: "SMS",
  push: "Push (Minha Claro)",
  whatsapp: "WhatsApp",
};
const CANAL_COR: Record<string, string> = {
  email: "bg-ch1",
  sms: "bg-ch3",
  push: "bg-ch2",
  whatsapp: "bg-ch4",
};

const INSTRUCOES_PADRAO =
  "Pós-pago com 100% da franquia consumida + ≥2 pacotes avulsos em 3 ciclos, sem UP nos últimos 6 meses.";

/** Chip de frescor por fonte (§8-M5-A4): D-1 (≥20h) em âmbar, resto em verde. */
function ChipFrescor({ fonte, iso }: { fonte: string; iso: string }) {
  const rel = tempoRelativo(iso);
  const velho = rel !== "tempo real" && rel.includes("h") && parseInt(rel.replace(/\D/g, ""), 10) >= 20;
  return (
    <span className={velho ? "mchip-w" : "mchip-g"} title={iso}>
      {rotuloFonte(fonte)} · {rel}
    </span>
  );
}

function LinhaWaterfall({
  rotulo,
  valor,
  pct,
  tom,
  detalhe,
}: {
  rotulo: string;
  valor: number;
  pct: number;
  tom?: "corte" | "liquido";
  detalhe?: string;
}) {
  const cor =
    tom === "liquido" ? "bg-good" : tom === "corte" ? "bg-[#D98E22]" : "bg-blue";
  return (
    <div className="text-[12px]">
      <div className="flex items-baseline justify-between gap-2">
        <span className={tom === "liquido" ? "font-bold" : ""}>
          {rotulo}
          {detalhe && <span className="text-faint"> {detalhe}</span>}
        </span>
        <b className={`tabular-nums ${tom === "liquido" ? "text-good" : ""}`}>
          {fmtInt(valor)}
        </b>
      </div>
      <div className="mbar">
        <i className={cor} style={{ width: `${Math.max(1, Math.min(100, pct))}%` }} />
      </div>
    </div>
  );
}

export function Audiencia() {
  const { id } = useParams<{ id: string }>();
  const osId = id ?? "";

  const segmento = useProducao((s) => s.segmentos[osId]);
  const certificado = useProducao((s) => s.certificados[osId]);
  const setSegmento = useProducao((s) => s.setSegmento);
  const setCertificado = useProducao((s) => s.setCertificado);
  const limparCertificado = useProducao((s) => s.limparCertificado);

  const [instrucoes, setInstrucoes] = useState(INSTRUCOES_PADRAO);
  const [saidaEngineer, setSaidaEngineer] = useState<GerarSqlOut | null>(null);
  const [holdout, setHoldout] = useState<number | null>(null);

  const holdoutPct = holdout ?? segmento?.holdout_pct ?? 10;

  const gerarSql = useMutation({
    mutationFn: (texto: string) =>
      post<GerarSqlOut>(`/os/${osId}/segmento/gerar-sql`, { instrucoes: texto }),
    onSuccess: (saida) => {
      setSaidaEngineer(saida);
      setSegmento(osId, saida.segmento);
      limparCertificado(osId); // novo SQL → certificado anterior não vale
      setHoldout(null);
    },
  });

  const recontar = useMutation({
    mutationFn: (segmentoId: string) => post<SegmentoOut>(`/segmentos/${segmentoId}/recontar`),
    onSuccess: (s) => setSegmento(osId, s),
  });

  const definirHoldout = useMutation({
    mutationFn: ({ segmentoId, pct }: { segmentoId: string; pct: number }) =>
      put<SegmentoOut>(`/segmentos/${segmentoId}/holdout`, { holdout_pct: pct }),
    onSuccess: (s) => {
      setSegmento(osId, s);
      setHoldout(null);
    },
  });

  const certificar = useMutation({
    mutationFn: (segmentoId: string) =>
      post<CertificadoOut>(`/segmentos/${segmentoId}/certificar`),
    onSuccess: (c) => setCertificado(osId, c),
  });

  const bruto = segmento?.contagem_bruta ?? null;
  const liquido = segmento?.contagem_liquida ?? null;
  const controle = liquido !== null ? Math.round((liquido * holdoutPct) / 100) : null;
  const volume = Object.entries(segmento?.volume_abordagem ?? {});

  // 422 do Guard (A1): listas faltantes no WHERE
  const listasFaltantes =
    certificar.error instanceof ApiError
      ? ((certificar.error.problem["listas_faltantes"] as string[] | undefined) ?? [])
      : [];

  usePainelContextual(
    <>
      <div className="ctx-title">Volume de abordagem por canal</div>
      {volume.length > 0 ? (
        <div className="mfield block">
          {volume.map(([canal, v]) => (
            <span key={canal} className="block text-[12px]">
              <span className="flex items-baseline justify-between">
                {CANAL_ROTULO[canal] ?? canal}
                <b className="tabular-nums">
                  {fmtCompacto(v.n)} · {v.pct.toLocaleString("pt-BR")}%
                </b>
              </span>
              <span className="mbar block">
                <i
                  className={CANAL_COR[canal] ?? "bg-blue"}
                  style={{ width: `${Math.min(100, v.pct)}%` }}
                />
              </span>
            </span>
          ))}
          <span className="block text-[11px] text-faint">
            pós caps + quiet hours + colisões do governor (§8-M5)
          </span>
        </div>
      ) : (
        <div className="text-[12px] text-muted">Reconte o segmento para calcular.</div>
      )}
      <div className="ctx-title">Refinamento sugerido</div>
      <Copiloto
        titulo="Engineer"
        acao="Aplicar ao SQL (regenera prévia)"
        onAcao={() =>
          gerarSql.mutate(
            `${instrucoes} Excluir quem recebeu oferta de upgrade nos últimos 30 dias.`,
          )
        }
      >
        Excluir quem recebeu oferta de upgrade nos últimos 30 dias reduz o público em ~6%,
        mas historicamente <b>dobra o CTR</b>. Aplicar?
      </Copiloto>
      <div className="ctx-title">Materialização (Activate)</div>
      <div className="mfield">
        <span className="block text-[11.5px] text-slatex">
          DEs a criar no SFMC: <span className="font-mono">DE_457_entrada</span>,{" "}
          <span className="font-mono">DE_457_mensuracao</span> — só campos do contrato de
          minimização (LGPD).
        </span>
      </div>
    </>,
    [volume.length, instrucoes, gerarSql.isPending],
  );

  return (
    <div>
      <TituloTela
        titulo="Estúdio de Audiência"
        subtitulo="Base elegível → líquido pós-compliance · recontagem dinâmica · certificação do Guard"
      />

      {gerarSql.error != null && <BannerErro erro={gerarSql.error} contexto="Engineer" />}
      {recontar.error != null && <BannerErro erro={recontar.error} contexto="Recontagem" />}
      {definirHoldout.error != null && (
        <BannerErro erro={definirHoldout.error} contexto="Holdout" />
      )}
      {certificar.error != null && (
        <div>
          <BannerErro erro={certificar.error} contexto="Guard reprovou a certificação" />
          {listasFaltantes.length > 0 && (
            <div className="-mt-1 mb-3 text-[12px] text-crit">
              Listas ausentes no WHERE:{" "}
              {listasFaltantes.map((l) => (
                <span key={l} className="mchip-r mr-1">
                  {rotuloFonte(l)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ------------------------------------------------ entrada do Engineer */}
      <div className="mcard mb-3">
        <div className="mb-1 text-[10px] font-bold uppercase tracking-[.08em] text-faint">
          Pedido ao Engineer (NL → SQL do público)
        </div>
        <div className="flex items-start gap-2">
          <textarea
            value={instrucoes}
            onChange={(e) => setInstrucoes(e.target.value)}
            rows={2}
            className="min-w-0 flex-1 resize-y rounded-md border border-line2 px-3 py-2 text-[13px] outline-none focus:border-blue"
            placeholder="Descreva o público em português — o Engineer gera o SQL com as 7 listas no WHERE."
          />
          <button
            type="button"
            className="mbtn flex-none"
            disabled={gerarSql.isPending || instrucoes.trim().length === 0}
            onClick={() => gerarSql.mutate(instrucoes.trim())}
          >
            {gerarSql.isPending ? "Gerando…" : segmento ? "Regenerar SQL" : "Gerar SQL"}
          </button>
        </div>
        <div className="mt-1 text-[11.5px] text-muted">
          Alternativa: partir de um segmento já publicado no{" "}
          <Link to={`/os/${osId}/datacloud`} className="font-semibold text-blue underline">
            Data Cloud (T5a)
          </Link>{" "}
          — lineage preservado.
        </div>
      </div>

      {!segmento && (
        <EstadoVazio>
          Nenhum segmento nesta OS ainda — gere o SQL com o Engineer acima ou use um
          segmento do Data Cloud (T5a).
        </EstadoVazio>
      )}

      {segmento && (
        <div className="flex flex-wrap items-start gap-3">
          {/* -------------------------------------------------- waterfall */}
          <div className="mcard min-w-[320px] flex-[1.15]">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                Waterfall de audiência
              </div>
              <button
                type="button"
                className="mbtn !px-2.5 !py-1 !text-[11px]"
                disabled={recontar.isPending}
                onClick={() => recontar.mutate(segmento.id)}
              >
                {recontar.isPending ? "Recontando…" : "Recontar"}
              </button>
            </div>

            {segmento.waterfall.length === 0 || bruto === null ? (
              <div className="py-4 text-center text-[12.5px] text-muted">
                Sem contagens ainda — <b>Recontar</b> roda o dry-run no read model
                (waterfall + líquido + volume por canal).
              </div>
            ) : (
              <div className="grid gap-1.5">
                <LinhaWaterfall rotulo="Base do segmento (bruta)" valor={bruto} pct={100} />
                {segmento.waterfall.map((e) => (
                  <LinhaWaterfall
                    key={e.etapa}
                    rotulo={
                      e.etapa === "sem_opt_in"
                        ? "− sem opt-in em nenhum canal"
                        : e.etapa === "criterios"
                          ? "− fora dos critérios do segmento"
                          : `− lista ${rotuloFonte(e.etapa).toUpperCase()}`
                    }
                    detalhe={`−${fmtCompacto(e.corte)}`}
                    valor={e.restante}
                    pct={bruto > 0 ? (100 * e.restante) / bruto : 0}
                    tom="corte"
                  />
                ))}
                {liquido !== null && (
                  <LinhaWaterfall
                    rotulo="Líquido com opt-in válido"
                    valor={liquido}
                    pct={bruto > 0 ? (100 * liquido) / bruto : 0}
                    tom="liquido"
                  />
                )}
              </div>
            )}

            {/* ------------------------------------------------- holdout */}
            <div className="mt-3 border-t border-linesoft pt-2 text-[12px]">
              <div className="flex items-center gap-2">
                <span className="font-bold">Holdout {holdoutPct.toLocaleString("pt-BR")}%</span>
                <input
                  type="range"
                  min={0}
                  max={30}
                  step={1}
                  value={holdoutPct}
                  onChange={(e) => setHoldout(Number(e.target.value))}
                  className="min-w-0 flex-1 accent-claro"
                  aria-label="Percentual de holdout"
                />
                <button
                  type="button"
                  className="mbtn-gh !px-2.5 !py-1 !text-[11px]"
                  disabled={definirHoldout.isPending || holdout === null}
                  onClick={() =>
                    definirHoldout.mutate({ segmentoId: segmento.id, pct: holdoutPct })
                  }
                >
                  {definirHoldout.isPending ? "Aplicando…" : "Aplicar holdout"}
                </button>
              </div>
              {liquido !== null && controle !== null && (
                <div className="mt-1 text-slatex">
                  (aleatório) → controle <b>{fmtInt(controle)}</b> · tratamento{" "}
                  <b>{fmtInt(liquido - controle)}</b>{" "}
                  <span className="mchip-b">política valida o mínimo</span>
                </div>
              )}
            </div>
          </div>

          {/* ------------------------------------------------- SQL dinâmico */}
          <div className="mcard min-w-[320px] flex-1">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                SQL do público · CLARO Engineer{" "}
                <BadgeViaAi
                  rastro={{
                    agente: "engineer",
                    skill: "v3.2",
                    evidencias: saidaEngineer?.evidencias,
                  }}
                />
              </div>
              <button
                type="button"
                className="mbtn-gd !px-2.5 !py-1 !text-[11px]"
                disabled={certificar.isPending}
                title={
                  segmento.origem === "data_cloud"
                    ? "Guard determinístico: certifica pelas contagens da consulta ao Data Cloud"
                    : "Guard determinístico: varre as 7 listas + opt-in no WHERE"
                }
                onClick={() => certificar.mutate(segmento.id)}
              >
                {certificar.isPending ? "Certificando…" : "Certificar (Guard)"}
              </button>
            </div>

            {segmento.origem === "data_cloud" ? (
              <div className="rounded-lg bg-surface2 p-3 text-[12px] text-slatex">
                Segmento vindo do <b>Data Cloud</b> (consulta, não cópia) —{" "}
                <span className="font-mono">{segmento.dc_segment_id}</span>. Critérios:{" "}
                {segmento.criterios_resumo ?? "—"}.
              </div>
            ) : (
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-claro p-3 font-mono text-[11px] leading-relaxed text-claro-paper">
                {segmento.sql_publico ?? "— sem SQL —"}
              </pre>
            )}

            {saidaEngineer && saidaEngineer.explicacao.length > 0 && (
              <div className="mt-2 grid gap-1">
                <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                  Explicação por cláusula
                </div>
                {saidaEngineer.explicacao.map((linha, i) => (
                  <div key={i} className="rounded-md bg-surface2 px-2.5 py-1.5 text-[11.5px]">
                    {Object.entries(linha).map(([clausula, motivo]) => (
                      <span key={clausula} className="block">
                        <span className="font-mono font-bold text-steel">{clausula}</span>{" "}
                        <span className="text-slatex">{motivo}</span>
                      </span>
                    ))}
                  </div>
                ))}
              </div>
            )}

            {saidaEngineer && saidaEngineer.avisos.length > 0 && (
              <div className="mt-2 rounded-md border border-warn-line bg-warn-bg px-2.5 py-1.5 text-[11.5px] text-warn">
                <b>Pré-check do Guard:</b> {saidaEngineer.avisos.join(" · ")}
              </div>
            )}

            {Object.keys(segmento.frescor).length > 0 && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11.5px] text-slatex">
                Frescor:
                {Object.entries(segmento.frescor).map(([fonte, iso]) => (
                  <ChipFrescor key={fonte} fonte={fonte} iso={iso} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ------------------------------------------------------ certificado */}
      {certificado && (
        <div className="mcard mt-3 border-good/50 bg-good-soft/40">
          <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
            <span className="mchip-g">certificado_elegibilidade</span>
            <b>líquido {fmtInt(certificado.liquido)}</b>
            <span className="text-slatex">
              hash <span className="font-mono">{certificado.hash.slice(0, 16)}…</span>
            </span>
            <span className="text-slatex">
              válido até{" "}
              <b>
                {certificado.valido_ate
                  ? new Date(certificado.valido_ate).toLocaleString("pt-BR")
                  : "—"}
              </b>
            </span>
            <span className="text-[11px] text-faint">
              publish (M8) recusa certificado expirado
            </span>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11.5px]">
            {Object.entries(certificado.suprimidos).map(([lista, n]) => (
              <span key={lista} className="mchip-n">
                {rotuloFonte(lista)} −{fmtCompacto(n)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
