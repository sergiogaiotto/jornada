/**
 * Contrato de UX da IA (SDD §12 / mocks): badge `via_ai` clicável — abre o rastro
 * completo (agente, versão da SKILL, evidências RAG, humano que aceitou).
 * "Copiloto, nunca portão."
 */
import { useState } from "react";

export interface RastroViaAi {
  agente?: string;
  skill?: string;
  evidencias?: string[];
  humano?: string;
  quando?: string;
}

export function BadgeViaAi({ rastro }: { rastro?: RastroViaAi }) {
  const [aberto, setAberto] = useState(false);

  return (
    <span className="relative inline-block align-middle">
      <button
        type="button"
        onClick={() => setAberto((a) => !a)}
        className="mchip bg-claro text-claro-pale hover:bg-claro-dark"
        title="Ação nascida de agente — clique para ver o rastro"
      >
        via_ai
      </button>
      {aberto && (
        <span
          className="absolute right-0 top-full z-40 mt-1 block w-64 rounded-lg border border-line bg-white p-3 text-left shadow-card"
          onClick={(e) => e.stopPropagation()}
        >
          <span className="mb-1 block text-[10px] font-bold uppercase tracking-[.1em] text-faint">
            Rastro via_ai
          </span>
          <span className="block text-[12px] leading-relaxed text-steel">
            <b>Agente:</b> {rastro?.agente ?? "—"}
            <br />
            <b>SKILL:</b> {rastro?.skill ?? "—"}
            <br />
            <b>Aceito por:</b> {rastro?.humano ?? "pendente de aceite humano"}
            {rastro?.quando && (
              <>
                <br />
                <b>Quando:</b> {rastro.quando}
              </>
            )}
          </span>
          {rastro?.evidencias && rastro.evidencias.length > 0 && (
            <span className="mt-1 block text-[11px] text-muted">
              <b>Evidências RAG:</b> {rastro.evidencias.join(" · ")}
            </span>
          )}
          <span className="mt-2 block border-t border-linesoft pt-1 text-[10px] text-faint">
            IA copilota, humano aprova — ledger `via_ai` (LGPD Art. 20)
          </span>
        </span>
      )}
    </span>
  );
}
