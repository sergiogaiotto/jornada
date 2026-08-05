/**
 * Cartão do copiloto (mock .cop): vermelho Claro, no painel direito contextual —
 * "o painel direito é a casa do copiloto" (SDD §12 / plano §5).
 */
import type { ReactNode } from "react";

interface Props {
  titulo: string;
  children: ReactNode;
  acao?: string;
  onAcao?: () => void;
}

export function Copiloto({ titulo, children, acao, onAcao }: Props) {
  return (
    <div className="rounded-lg bg-claro p-3 text-[12px] leading-relaxed text-[#FDE9E6]">
      <div className="mb-1.5 flex items-center gap-1.5 text-[12px] font-extrabold text-claro-pale">
        <span className="inline-block h-2 w-2 rounded-full bg-claro-pale" />
        {titulo}
      </div>
      <div>{children}</div>
      {acao && (
        <button
          type="button"
          onClick={onAcao}
          className="mt-2 block w-full rounded-md bg-claro-dark px-2.5 py-1.5 text-left text-[12px] font-semibold text-claro-paper hover:brightness-110"
        >
          {acao} →
        </button>
      )}
    </div>
  );
}
