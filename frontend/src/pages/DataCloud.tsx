/**
 * T5a · Segmentos do Data Cloud (mock T5a / SDD §8-M5): catálogo dinâmico (consulta, não
 * cópia) com membros, DMOs e frescor de republicação; relatório de tamanho de público
 * (bruto→elegível→líquido→sobreposição) e volume de abordagem por canal pós caps/quiet
 * hours/colisões do governor; "usar como entrada no Estúdio (T5)" com lineage.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { cabecalhosDaSessao, get, post } from "../lib/api";
import { fmtCompacto, fmtInt, rotuloFonte, tempoRelativo } from "../lib/format";
import { usePainelContextual } from "../lib/hooks";
import type { DcSegmentoOut, RelatorioDcOut, SegmentoOut } from "../lib/types";
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

function ChipStatus({ status }: { status: string | null }) {
  if (status === "publicado") return <span className="mchip-g">publicado</span>;
  if (status === "republicando") return <span className="mchip-w">republicando</span>;
  return <span className="mchip-n">{status ?? "—"}</span>;
}

/**
 * Download autenticado do .docx (§8-M5) — <a href> puro não levaria o X-Tenant.
 * Emenda E04: a credencial é o cookie de sessão httpOnly (`credentials: "include"`),
 * não mais um Bearer de dev montado pelo cliente.
 */
async function baixarRelatorioDocx(segmentoId: string): Promise<void> {
  const res = await fetch(`/api/v1/datacloud/segmentos/${segmentoId}/relatorio.docx`, {
    headers: cabecalhosDaSessao(),
    credentials: "include",
  });
  if (!res.ok) throw new Error(`Falha ao gerar o .docx (HTTP ${res.status}).`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${segmentoId}-relatorio.docx`;
  a.click();
  URL.revokeObjectURL(url);
}

export function DataCloud() {
  const { id } = useParams<{ id: string }>();
  const osId = id ?? "";
  const navegar = useNavigate();
  const setSegmento = useProducao((s) => s.setSegmento);

  const [escolhido, setEscolhido] = useState<string | null>(null);

  const catalogo = useQuery({
    queryKey: ["datacloud", "segmentos"],
    queryFn: ({ signal }) => get<DcSegmentoOut[]>("/datacloud/segmentos", signal),
  });

  const selecionado = escolhido ?? catalogo.data?.[0]?.id ?? null;
  const segmentoDc = catalogo.data?.find((s) => s.id === selecionado) ?? null;

  const relatorio = useQuery({
    queryKey: ["datacloud", "segmentos", selecionado, "relatorio"],
    queryFn: ({ signal }) =>
      get<RelatorioDcOut>(`/datacloud/segmentos/${selecionado}/relatorio`, signal),
    enabled: selecionado !== null,
  });

  const usar = useMutation({
    mutationFn: (segmentoId: string) =>
      post<SegmentoOut>(`/datacloud/segmentos/${segmentoId}/usar`, { os_id: osId }),
    onSuccess: (s) => {
      setSegmento(osId, s); // lineage preservado — T5 abre com o segmento em foco
      navegar(`/os/${osId}/audiencia`);
    },
  });

  const exportar = useMutation({
    mutationFn: (segmentoId: string) => baixarRelatorioDocx(segmentoId),
  });

  const r = relatorio.data;

  usePainelContextual(
    <>
      <div className="ctx-title">Segmento selecionado</div>
      {segmentoDc ? (
        <>
          <div className="mfield">
            <span className="min-w-0">
              <span className="block text-[12px] font-bold">Origem (DMOs)</span>
              <span className="block text-[11.5px] leading-relaxed text-slatex">
                {segmentoDc.dmos.length > 0 ? segmentoDc.dmos.join(" · ") : "—"}
              </span>
            </span>
          </div>
          <div className="mfield">
            <span className="min-w-0">
              <span className="block text-[12px] font-bold">
                Critérios (resumo) <span className="mchip bg-claro text-claro-pale">via_ai</span>
              </span>
              <span className="block text-[11.5px] leading-relaxed text-slatex">
                {segmentoDc.criterios_resumo ?? "—"}
              </span>
            </span>
          </div>
          <div className="ctx-title">Ações</div>
          <button
            type="button"
            className="mbtn mb-2 w-full justify-center"
            disabled={usar.isPending}
            onClick={() => usar.mutate(segmentoDc.id)}
          >
            {usar.isPending ? "Levando ao Estúdio…" : "Usar como entrada no Estúdio (T5)"}
          </button>
          <button
            type="button"
            className="mbtn-gh mb-2 w-full justify-center"
            disabled={exportar.isPending}
            onClick={() => exportar.mutate(segmentoDc.id)}
          >
            {exportar.isPending ? "Gerando…" : "⇩ Exportar relatório (.docx)"}
          </button>
          <Copiloto titulo="Engineer">
            Este segmento cobre ~99% do público que o briefing descreve. Recomendo usá-lo
            como entrada e aplicar o refinamento de exclusão de ofertas 30d no Estúdio —
            lineage preservado, consulta em vez de cópia.
          </Copiloto>
        </>
      ) : (
        <div className="text-[12px] text-muted">Selecione um segmento no catálogo.</div>
      )}
    </>,
    [segmentoDc?.id, usar.isPending, exportar.isPending],
  );

  return (
    <div>
      <TituloTela
        titulo={
          <>
            Segmentos do Data Cloud{" "}
            {catalogo.data && <span className="mchip-g">{catalogo.data.length} publicados</span>}
          </>
        }
        subtitulo="Consulta, não cópia · selecione um segmento para o relatório de público"
      />

      {catalogo.error != null && <BannerErro erro={catalogo.error} contexto="Data Cloud" />}
      {relatorio.error != null && <BannerErro erro={relatorio.error} contexto="Relatório" />}
      {usar.error != null && <BannerErro erro={usar.error} contexto="Usar segmento" />}
      {exportar.error != null && <BannerErro erro={exportar.error} contexto="Exportar .docx" />}

      {/* ---------------------------------------------------------- catálogo */}
      <div className="mcard mb-3 overflow-x-auto p-0">
        <table className="w-full border-collapse text-[12.5px]">
          <thead>
            <tr className="border-b border-line text-left text-[10px] uppercase tracking-[.06em] text-faint">
              <th className="px-4 py-2">Segmento</th>
              <th className="px-3 py-2 text-right">Membros</th>
              <th className="px-3 py-2">Republicado</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {catalogo.isLoading && (
              <tr>
                <td colSpan={5} className="px-4 py-4 text-center text-muted">
                  Consultando o Data Cloud…
                </td>
              </tr>
            )}
            {(catalogo.data ?? []).map((s) => {
              const ativo = s.id === selecionado;
              return (
                <tr
                  key={s.id}
                  className={`cursor-pointer border-b border-linesoft last:border-0 ${
                    ativo ? "bg-claro-soft" : "hover:bg-surface2"
                  }`}
                  onClick={() => setEscolhido(s.id)}
                >
                  <td className="px-4 py-2">
                    <b>{s.nome ?? s.id}</b>
                    {s.criterios_resumo && (
                      <span className="text-slatex"> · {s.criterios_resumo}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right font-bold tabular-nums">
                    {fmtInt(s.membros)}
                  </td>
                  <td className="px-3 py-2 text-slatex">
                    {tempoRelativo(s.republicado_em)}
                    {s.ciclo && <span className="text-faint"> · ciclo {s.ciclo}</span>}
                  </td>
                  <td className="px-3 py-2">
                    <ChipStatus status={s.status} />
                  </td>
                  <td className="px-3 py-2">
                    <span className="flex items-center justify-end gap-1.5 whitespace-nowrap">
                      <span className={ativo ? "mbtn !px-2.5 !py-1 !text-[11px]" : "mbtn-gh !px-2.5 !py-1 !text-[11px]"}>
                        Relatório {ativo ? "▾" : ""}
                      </span>
                      {/* A12 (UAT): ação por segmento — POST /datacloud/segmentos/{id}/usar
                          (lineage §8-M5); sucesso navega ao Estúdio (T5) com o segmento
                          em foco; erro aparece no BannerErro "Usar segmento" acima. */}
                      <button
                        type="button"
                        className="mbtn !px-2.5 !py-1 !text-[11px]"
                        disabled={usar.isPending}
                        title="Vira segmento de trabalho da OS com lineage (consulta, não cópia) e abre o Estúdio de Audiência"
                        onClick={(ev) => {
                          ev.stopPropagation();
                          setEscolhido(s.id);
                          usar.mutate(s.id);
                        }}
                      >
                        {usar.isPending && usar.variables === s.id
                          ? "Levando ao Estúdio…"
                          : "Usar como entrada no Estúdio (T5)"}
                      </button>
                    </span>
                  </td>
                </tr>
              );
            })}
            {catalogo.data && catalogo.data.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-4">
                  <EstadoVazio>Nenhum segmento publicado no Data Cloud.</EstadoVazio>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* --------------------------------------------------------- relatório */}
      {r && (
        <div className="flex flex-wrap items-start gap-3">
          <div className="mcard min-w-[300px] flex-1">
            <div className="text-[12.5px] font-bold">
              Relatório de tamanho de público · {r.segmento.nome ?? r.segmento.id}
            </div>
            <div className="mt-2 grid gap-1.5 text-[12px]">
              <div>
                <div className="flex items-baseline justify-between">
                  Contagem bruta no Data Cloud <b className="tabular-nums">{fmtInt(r.funil.bruto)}</b>
                </div>
                <div className="mbar">
                  <i className="bg-blue" style={{ width: "100%" }} />
                </div>
              </div>
              <div>
                <div className="flex items-baseline justify-between">
                  Elegível (− 7 listas de exclusão){" "}
                  <b className="tabular-nums">{fmtInt(r.funil.elegivel)}</b>
                </div>
                <div className="mbar">
                  <i
                    className="bg-[#D98E22]"
                    style={{
                      width: `${r.funil.bruto > 0 ? (100 * r.funil.elegivel) / r.funil.bruto : 0}%`,
                    }}
                  />
                </div>
              </div>
              <div>
                <div className="flex items-baseline justify-between font-bold">
                  Público líquido (opt-in válido ≥ 1 canal){" "}
                  <b className="tabular-nums text-good">{fmtInt(r.funil.liquido)}</b>
                </div>
                <div className="mbar">
                  <i
                    className="bg-good"
                    style={{
                      width: `${r.funil.bruto > 0 ? (100 * r.funil.liquido) / r.funil.bruto : 0}%`,
                    }}
                  />
                </div>
              </div>
            </div>
            {Object.keys(r.sobreposicao).length > 0 && (
              <div className="mt-2 rounded-md border border-warn-line bg-warn-bg px-2.5 py-1.5 text-[11.5px] text-warn">
                ⚠ Sobreposição com campanhas ativas:{" "}
                {Object.entries(r.sobreposicao)
                  .map(([os, n]) => `${fmtCompacto(n)} em ${os}`)
                  .join(" · ")}
              </div>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11.5px] text-slatex">
              Frescor:
              {Object.entries(r.frescor).map(([fonte, iso]) => (
                <span
                  key={fonte}
                  className={tempoRelativo(iso).includes("d") || (tempoRelativo(iso).includes("h") && parseInt(tempoRelativo(iso).replace(/\D/g, "") || "0", 10) >= 20) ? "mchip-w" : "mchip-g"}
                  title={iso}
                >
                  {rotuloFonte(fonte)} · {tempoRelativo(iso)}
                </span>
              ))}
            </div>
          </div>

          <div className="mcard min-w-[300px] flex-1">
            <div className="text-[12.5px] font-bold">
              Volume de abordagem por canal{" "}
              <span className="mchip-b">pós caps + quiet hours + colisões</span>
            </div>
            <div className="mt-2 grid gap-1.5 text-[12px]">
              {Object.entries(r.volume_abordagem).map(([canal, v]) => (
                <div key={canal}>
                  <div className="flex items-baseline justify-between">
                    {CANAL_ROTULO[canal] ?? canal}
                    <b className="tabular-nums">
                      {fmtCompacto(v.n)} · {v.pct.toLocaleString("pt-BR")}%
                    </b>
                  </div>
                  <div className="mbar">
                    <i
                      className={CANAL_COR[canal] ?? "bg-blue"}
                      style={{ width: `${Math.min(100, v.pct)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-2 text-[11.5px] text-slatex">
              Colisões do governor:{" "}
              {Object.entries(r.colisoes)
                .map(([canal, n]) => `${CANAL_ROTULO[canal] ?? canal} ${fmtCompacto(n)}`)
                .join(" · ")}
            </div>
            <div className="mt-1 text-[11.5px] text-muted">
              Mix recomendado: âncora e-mail + SMS de reforço · WhatsApp só heavy users
              (custo unitário R$ 0,3597).
            </div>
          </div>
        </div>
      )}
      {selecionado !== null && relatorio.isLoading && (
        <EstadoVazio>Montando o relatório de público…</EstadoVazio>
      )}
    </div>
  );
}
