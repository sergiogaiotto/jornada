/**
 * Contrato de UX da IA (SDD §1.1.3 / §12): TODA sugestão de agente chega como
 * prévia/diff com Aplicar / Rejeitar — nunca aplicada direto.
 */
import { useState } from "react";

import { BadgeViaAi, type RastroViaAi } from "./BadgeViaAi";
import { ChipsPremissas } from "./ChipsPremissas";

export interface ItemDiff {
  rotulo: string;
  antes?: string;
  depois: string;
}

interface Props {
  titulo: string;
  itens: ItemDiff[];
  premissas?: string[];
  rastro?: RastroViaAi;
  onAplicar: () => void | Promise<void>;
  onRejeitar: () => void;
  rotuloAplicar?: string;
}

export function PreviaDiff({
  titulo,
  itens,
  premissas,
  rastro,
  onAplicar,
  onRejeitar,
  rotuloAplicar = "Aplicar",
}: Props) {
  const [aplicando, setAplicando] = useState(false);

  return (
    <div className="rounded-lg border border-blue/40 bg-blue-soft/40 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-[12px] font-bold text-ink2">
          Prévia · {titulo} <BadgeViaAi rastro={rastro} />
        </div>
      </div>
      <div className="mb-2 grid gap-1.5">
        {itens.map((item, i) => (
          <div key={i} className="rounded-md border border-line bg-white px-3 py-2">
            <div className="text-[10px] font-bold uppercase tracking-[.06em] text-faint">
              {item.rotulo}
            </div>
            {item.antes !== undefined && item.antes !== "" && (
              <div className="text-[12px] text-crit line-through decoration-crit/60">
                {item.antes}
              </div>
            )}
            <div className="text-[12px] font-semibold text-good">{item.depois}</div>
          </div>
        ))}
      </div>
      {premissas && premissas.length > 0 && (
        <div className="mb-2">
          <ChipsPremissas premissas={premissas} />
        </div>
      )}
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="mbtn"
          disabled={aplicando}
          onClick={async () => {
            setAplicando(true);
            try {
              await onAplicar();
            } finally {
              setAplicando(false);
            }
          }}
        >
          {aplicando ? "Aplicando…" : rotuloAplicar}
        </button>
        <button type="button" className="mbtn-gh" disabled={aplicando} onClick={onRejeitar}>
          Rejeitar
        </button>
        <span className="text-[10px] text-faint">IA copilota · humano aprova</span>
      </div>
    </div>
  );
}
