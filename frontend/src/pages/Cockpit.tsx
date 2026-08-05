/**
 * T1 · Cockpit Jornada — home do portfólio (mock T1): KPIs + kanban por fase, saúde
 * DERIVADA (GET /os/{id}/saude — nunca editável), painel direito com a OS selecionada
 * e o digest do copiloto.
 */
import { useQueries } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Copiloto } from "../components/ai/Copiloto";
import { BadgeViaAi } from "../components/ai/BadgeViaAi";
import {
  BannerErro,
  ChipSaude,
  EstadoVazio,
  Kpi,
  TituloTela,
} from "../components/ui/basics";
import { get } from "../lib/api";
import { useOsLista, usePainelContextual } from "../lib/hooks";
import type { OsOut, SaudeOut } from "../lib/types";

const COLUNAS: { rotulo: string; fases: string[] }[] = [
  { rotulo: "Pensada", fases: ["pensada"] },
  { rotulo: "Discutida", fases: ["discutida"] },
  { rotulo: "Criada", fases: ["criada"] },
  { rotulo: "Avaliada", fases: ["avaliada"] },
  { rotulo: "Configurada", fases: ["configurada"] },
  { rotulo: "No ar", fases: ["disparada", "monitorada"] },
  { rotulo: "Encerrada", fases: ["encerrada"] },
];

function CartaoOs({
  os,
  saude,
  selecionada,
  onSelecionar,
}: {
  os: OsOut;
  saude?: "normal" | "em_risco";
  selecionada: boolean;
  onSelecionar: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelecionar}
      className={`mfield w-full cursor-pointer text-left transition-colors hover:border-blue ${
        selecionada ? "border-blue bg-blue-soft/40" : ""
      }`}
    >
      <span className="min-w-0">
        <span className="block truncate text-[12.5px] font-bold text-ink2">
          {os.codigo} · {os.nome}
        </span>
        <span className="block text-[11.5px] text-slatex">
          {os.tshirt} · fase {os.fase}
        </span>
      </span>
      <ChipSaude saude={saude} />
    </button>
  );
}

export function Cockpit() {
  const { data: oss, isLoading, error } = useOsLista();
  const [selecionadaId, setSelecionadaId] = useState<string | null>(null);

  const saudes = useQueries({
    queries: (oss ?? []).map((os) => ({
      queryKey: ["os", os.id, "saude"],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        get<SaudeOut>(`/os/${os.id}/saude`, signal),
    })),
  });

  const saudePorOs = useMemo(() => {
    const mapa = new Map<string, "normal" | "em_risco">();
    saudes.forEach((q) => {
      if (q.data) mapa.set(q.data.os_id, q.data.saude);
    });
    return mapa;
  }, [saudes]);

  const selecionada = (oss ?? []).find((o) => o.id === selecionadaId) ?? null;
  const noAr = (oss ?? []).filter((o) => o.fase === "disparada" || o.fase === "monitorada");
  const aguardando = (oss ?? []).filter((o) => o.fase === "avaliada");
  const emRisco = [...saudePorOs.values()].filter((s) => s === "em_risco").length;

  usePainelContextual(
    <>
      <div className="ctx-title">
        {selecionada ? `${selecionada.codigo} · Selecionada` : "Portfólio"}
      </div>
      {selecionada ? (
        <>
          <div className="mfield">
            <span>
              <span className="block text-[12px] font-bold">Fase atual</span>
              <span className="block text-[11.5px] text-slatex">
                {selecionada.fase} · t-shirt {selecionada.tshirt}
              </span>
            </span>
          </div>
          <div className="mfield">
            <span>
              <span className="block text-[12px] font-bold">Saúde (derivada)</span>
              <span className="block text-[11.5px] text-slatex">
                atraso vs SLA + pendências + breakers — nunca editável
              </span>
            </span>
            <ChipSaude saude={saudePorOs.get(selecionada.id)} />
          </div>
          <div className="mfield">
            <span>
              <span className="block text-[12px] font-bold">Últimas ações</span>
              <span className="block text-[11.5px] text-slatex">
                Briefing estruturado <BadgeViaAi rastro={{ agente: "consultor" }} />
              </span>
            </span>
          </div>
          <Link to={`/os/${selecionada.id}/briefing`} className="mbtn mb-2 mt-1 w-full justify-center">
            Abrir OS →
          </Link>
        </>
      ) : (
        <div className="text-[12px] text-muted">
          Selecione uma campanha no kanban para ver SLA, portões e ações.
        </div>
      )}
      <div className="ctx-title">Copiloto — digest</div>
      <Copiloto titulo="Hoje no portfólio">
        {oss && oss.length > 0 ? (
          <>
            {oss.length} campanha(s) no ciclo · {noAr.length} no ar · {aguardando.length}{" "}
            aguardando aprovação · <b>{emRisco} em risco</b>.
            {emRisco > 0 && " Comece pelas pendências bloqueantes."}
          </>
        ) : (
          "Sem campanhas no ciclo — importe do Hike (T4a) ou crie um pedido na Sala de Ideação."
        )}
      </Copiloto>
    </>,
    [selecionada, oss, emRisco, noAr.length, aguardando.length, saudePorOs],
  );

  return (
    <div>
      <TituloTela
        titulo="Cockpit"
        subtitulo={`Portfólio · ${oss?.length ?? "…"} campanha(s) no ciclo · saúde derivada, nunca editável`}
      />
      {error != null && <BannerErro erro={error} contexto="Falha ao listar OSs" />}

      <div className="mb-4 flex gap-3 overflow-x-auto">
        <Kpi rotulo="No ar" valor={noAr.length} detalhe="disparada + monitorada" />
        <Kpi
          rotulo="Aguardando aprovação"
          valor={aguardando.length}
          tom="warn"
          detalhe="fase avaliada"
        />
        <Kpi rotulo="Em risco" valor={emRisco} tom="crit" detalhe="saúde derivada" />
        <Kpi rotulo="No ciclo" valor={oss?.length ?? 0} tom="blue" detalhe="todas as fases" />
      </div>

      {isLoading && <EstadoVazio>Carregando portfólio…</EstadoVazio>}
      {oss && oss.length === 0 && (
        <EstadoVazio>
          Nenhuma OS no tenant — suba o backend com <code>DEMO_MODE=true</code> (seeds
          OS-2026-0457, SDD §11.4) ou importe o export do Hike.
        </EstadoVazio>
      )}

      {oss && oss.length > 0 && (
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          {COLUNAS.map((col) => {
            const daColuna = oss.filter((o) => col.fases.includes(o.fase));
            if (daColuna.length === 0 && ["Configurada", "Encerrada"].includes(col.rotulo))
              return null;
            return (
              <div key={col.rotulo} className="mcard">
                <div className="mb-2 text-[10px] font-bold uppercase tracking-[.06em] text-faint">
                  {col.rotulo} · {daColuna.length}
                </div>
                {daColuna.map((os) => (
                  <CartaoOs
                    key={os.id}
                    os={os}
                    saude={saudePorOs.get(os.id)}
                    selecionada={os.id === selecionadaId}
                    onSelecionar={() => setSelecionadaId(os.id)}
                  />
                ))}
                {daColuna.length === 0 && (
                  <div className="py-2 text-center text-[11.5px] text-ghost">vazio</div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
