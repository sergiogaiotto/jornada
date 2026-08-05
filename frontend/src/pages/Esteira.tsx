/**
 * T4a · Esteira de Produção — ex-Hike (mock T4a): 7 etapas com responsável, SLA,
 * checklist e dependências (GET/PATCH /os/{id}/workflow). Dependência insatisfeita →
 * 409 RFC-7807 exibido; etapa selecionada detalhada no painel contextual (hike_ref).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { patch } from "../lib/api";
import { usePainelContextual, useWorkflow } from "../lib/hooks";
import type { EtapaOut, WorkflowOut } from "../lib/types";

const ROTULO_ETAPA: Record<string, string> = {
  briefing: "Briefing",
  discovery: "Discovery",
  audiencia: "Audiência",
  criativos: "Criativos",
  configuracao: "Configuração",
  disparo: "Disparo",
  acompanhamento: "Acompanhamento",
};

function ChipEstado({ estado }: { estado: string }) {
  if (estado === "concluida") return <span className="mchip-g">concluída</span>;
  if (estado === "em_andamento") return <span className="mchip-b">em andamento</span>;
  if (estado === "bloqueada") return <span className="mchip-r">bloqueada</span>;
  return <span className="mchip-n">pendente</span>;
}

export function Esteira() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: workflow, isLoading, error } = useWorkflow(id);
  const [selecionadaNome, setSelecionadaNome] = useState<string | null>(null);

  const mudar = useMutation({
    mutationFn: (corpo: {
      etapa: string;
      estado?: string;
      checklist?: { item: string; feito: boolean }[];
    }) => patch<WorkflowOut>(`/os/${id}/workflow`, corpo),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["os", id, "workflow"] });
    },
  });

  const etapas = [...(workflow?.etapas ?? [])].sort((a, b) => a.ordem - b.ordem);
  const selecionada = etapas.find((e) => e.nome === selecionadaNome) ?? null;
  const concluidas = etapas.filter((e) => e.estado === "concluida").length;

  usePainelContextual(
    <>
      <div className="ctx-title">
        {selecionada
          ? `Etapa selecionada · ${ROTULO_ETAPA[selecionada.nome] ?? selecionada.nome}`
          : "Esteira"}
      </div>
      {selecionada ? (
        <>
          <div className="mfield">
            <span>
              <span className="block text-[12px] font-bold">SLA blindado</span>
              <span className="block text-[11.5px] text-slatex">
                {selecionada.sla_dias != null
                  ? `${selecionada.sla_dias}d úteis · congelado no GO`
                  : "sem SLA definido"}
              </span>
            </span>
            <ChipEstado estado={selecionada.estado} />
          </div>
          <div className="mfield">
            <span>
              <span className="block text-[12px] font-bold">Dependências</span>
              <span className="block text-[11.5px] text-slatex">
                {selecionada.dependencias.length > 0
                  ? selecionada.dependencias
                      .map((d) => ROTULO_ETAPA[d] ?? d)
                      .join(" → ")
                  : "nenhuma"}
              </span>
            </span>
          </div>
          {selecionada.hike_ref && (
            <div className="mfield">
              <span>
                <span className="block text-[12px] font-bold">Migração Hike</span>
                <span className="block break-all text-[11px] text-slatex">
                  card {String(selecionada.hike_ref["card_id"] ?? "—")} · histórico e
                  anexos importados · original arquivado (read-only)
                </span>
              </span>
              <span className="mchip-g">ok</span>
            </div>
          )}
        </>
      ) : (
        <div className="text-[12px] text-muted">
          Selecione uma etapa para ver SLA, dependências e origem Hike.
        </div>
      )}
      <div className="ctx-title">Copiloto da esteira</div>
      <Copiloto titulo="Antecipação de atrasos">
        {concluidas} de {etapas.length} etapas concluídas. Dependência insatisfeita
        bloqueia o avanço por construção (409) — a saúde continua derivada.
      </Copiloto>
    </>,
    [selecionada, concluidas, etapas.length],
  );

  const acaoDaEtapa = (etapa: EtapaOut) => {
    if (etapa.estado === "pendente")
      return { rotulo: "Iniciar", estado: "em_andamento" as const };
    if (etapa.estado === "em_andamento")
      return { rotulo: "Concluir", estado: "concluida" as const };
    return null;
  };

  return (
    <div>
      <TituloTela
        titulo="Esteira de Produção"
        subtitulo={
          <>
            <span className="mchip-b">{etapas.length} etapas</span>{" "}
            <span className="mchip-g">workflow 100% na plataforma · ex-Hike</span> ·
            responsável, SLA e checklist por etapa · dependências explícitas
          </>
        }
      />
      {error != null && <BannerErro erro={error} contexto="Workflow" />}
      {mudar.error != null && <BannerErro erro={mudar.error} contexto="Atualização de etapa" />}
      {isLoading && <EstadoVazio>Carregando esteira…</EstadoVazio>}
      {workflow && etapas.length === 0 && (
        <EstadoVazio>Sem workflow — as 7 etapas nascem com a OS (M2).</EstadoVazio>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
        {etapas.map((etapa) => {
          const acao = acaoDaEtapa(etapa);
          const feitos = etapa.checklist.filter((c) => c.feito).length;
          return (
            <div
              key={etapa.id}
              className={`mcard cursor-pointer transition-colors ${
                etapa.estado === "em_andamento" ? "border-blue" : ""
              } ${selecionadaNome === etapa.nome ? "ring-1 ring-blue" : ""}`}
              onClick={() => setSelecionadaNome(etapa.nome)}
            >
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-[10px] font-bold uppercase tracking-[.06em] text-faint">
                  {etapa.ordem} · {ROTULO_ETAPA[etapa.nome] ?? etapa.nome}
                </span>
                <ChipEstado estado={etapa.estado} />
              </div>
              <div className="text-[11.5px] text-slatex">
                {etapa.sla_dias != null ? `SLA ${etapa.sla_dias}d` : "sem SLA"}
                {etapa.checklist.length > 0 &&
                  ` · checklist ${feitos}/${etapa.checklist.length}`}
              </div>
              {etapa.checklist.length > 0 && (
                <div className="mt-2 space-y-1">
                  {etapa.checklist.map((item) => (
                    <label
                      key={item.item}
                      className="flex cursor-pointer items-center gap-2 text-[12px] text-steel"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <input
                        type="checkbox"
                        checked={item.feito}
                        disabled={mudar.isPending}
                        onChange={() =>
                          mudar.mutate({
                            etapa: etapa.nome,
                            checklist: [{ item: item.item, feito: !item.feito }],
                          })
                        }
                      />
                      <span className={item.feito ? "text-muted line-through" : ""}>
                        {item.item}
                      </span>
                    </label>
                  ))}
                </div>
              )}
              {acao && (
                <button
                  type="button"
                  className="mbtn-gh mt-2 !px-2.5 !py-1 !text-[11px]"
                  disabled={mudar.isPending}
                  onClick={(e) => {
                    e.stopPropagation();
                    mudar.mutate({ etapa: etapa.nome, estado: acao.estado });
                  }}
                >
                  {acao.rotulo}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
