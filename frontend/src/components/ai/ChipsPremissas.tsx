/**
 * Contrato de UX da IA (SDD §12): premissas assumidas pelo agente como chips EDITÁVEIS.
 */
import { useState } from "react";

interface Props {
  premissas: string[];
  onEditar?: (indice: number, valor: string) => void;
  onRemover?: (indice: number) => void;
}

export function ChipsPremissas({ premissas, onEditar, onRemover }: Props) {
  const [editando, setEditando] = useState<number | null>(null);
  const [rascunho, setRascunho] = useState("");

  if (premissas.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
        Premissas
      </span>
      {premissas.map((p, i) =>
        editando === i ? (
          <input
            key={i}
            autoFocus
            value={rascunho}
            onChange={(e) => setRascunho(e.target.value)}
            onBlur={() => setEditando(null)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                onEditar?.(i, rascunho.trim() || p);
                setEditando(null);
              }
              if (e.key === "Escape") setEditando(null);
            }}
            className="rounded-full border border-blue bg-white px-2.5 py-0.5 text-[11px] font-semibold text-steel outline-none"
          />
        ) : (
          <span
            key={i}
            className="group inline-flex items-center gap-1 rounded-full border border-line2 bg-white px-2.5 py-0.5 text-[11px] font-semibold text-slatex"
          >
            {p}
            {onEditar && (
              <button
                type="button"
                title="Editar premissa"
                className="text-faint opacity-60 hover:text-blue group-hover:opacity-100"
                onClick={() => {
                  setRascunho(p);
                  setEditando(i);
                }}
              >
                ✎
              </button>
            )}
            {onRemover && (
              <button
                type="button"
                title="Remover premissa"
                className="text-faint opacity-60 hover:text-crit group-hover:opacity-100"
                onClick={() => onRemover(i)}
              >
                ×
              </button>
            )}
          </span>
        ),
      )}
    </div>
  );
}
