/**
 * Pill "Guia Interativo" do Topbar (gradiente vermelho→azul sutil, ícone ✨ —
 * referência visual: plataforma Maestro) com dropdown de 3 modos do guia:
 * Tour das páginas, Guia dos Módulos e Ajuda desta página.
 */
import { useEffect, useRef } from "react";

import { type ModoGuia, useGuia } from "./store";

const ITENS: {
  modo: Exclude<ModoGuia, null>;
  icone: string;
  titulo: string;
  subtitulo: string;
}[] = [
  {
    modo: "tour",
    icone: "🎯",
    titulo: "Tour das páginas",
    subtitulo: "Highlight do menu lateral, página por página",
  },
  {
    modo: "modulos",
    icone: "📚",
    titulo: "Guia dos Módulos",
    subtitulo: "Fundamento, aplicação e como usar — 18 telas",
  },
  {
    modo: "ajuda",
    icone: "💡",
    titulo: "Ajuda desta página",
    subtitulo: "O que é, fundamento e como usar — contexto da página atual",
  },
];

export function DropdownGuia() {
  const aberto = useGuia((s) => s.dropdownAberto);
  const setAberto = useGuia((s) => s.setDropdownAberto);
  const abrir = useGuia((s) => s.abrir);
  const raiz = useRef<HTMLDivElement>(null);

  // clique fora / Esc fecham o dropdown
  useEffect(() => {
    if (!aberto) return;
    const clique = (e: MouseEvent) => {
      if (raiz.current && !raiz.current.contains(e.target as Node)) setAberto(false);
    };
    const tecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAberto(false);
    };
    document.addEventListener("mousedown", clique);
    document.addEventListener("keydown", tecla);
    return () => {
      document.removeEventListener("mousedown", clique);
      document.removeEventListener("keydown", tecla);
    };
  }, [aberto, setAberto]);

  return (
    <div ref={raiz} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={aberto}
        onClick={() => setAberto(!aberto)}
        className="rounded-full bg-gradient-to-r from-claro-dark to-blue/80 px-3 py-0.5 text-[11px] font-semibold text-white ring-1 ring-white/25 transition-shadow hover:ring-white/60"
        title="Guia Interativo"
      >
        ✨ Guia Interativo
      </button>
      {aberto && (
        <div
          role="menu"
          aria-label="Guia Interativo"
          className="absolute right-0 top-full z-[60] mt-2 w-80 overflow-hidden rounded-xl border border-line bg-white py-1 shadow-card"
        >
          {ITENS.map((item) => (
            <button
              key={item.modo}
              type="button"
              role="menuitem"
              onClick={() => abrir(item.modo)}
              className="flex w-full items-start gap-2.5 px-4 py-2.5 text-left hover:bg-blue-soft"
            >
              <span className="mt-0.5 text-[15px]" aria-hidden>
                {item.icone}
              </span>
              <span>
                <span className="block text-[13px] font-semibold text-ink">{item.titulo}</span>
                <span className="block text-[11px] leading-snug text-muted">{item.subtitulo}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
