/**
 * Paleta lateral do editor T7 (mock Journey Builder): atividades §5.2 agrupadas nas
 * categorias JB com as cores jb-*, busca por nome/tipo e tooltip do §5.2 (title).
 * Drag & drop nativo: o item põe o `type` do JGC em `application/jornada-tipo`;
 * o EditorJornada materializa o nó no onDrop com o data default do catálogo.
 */
import { useMemo, useState } from "react";

import { CATALOGO, COR_CATEGORIA, GRUPOS_PALETA } from "./catalogo";

export function Paleta() {
  const [busca, setBusca] = useState("");

  const grupos = useMemo(() => {
    const filtro = busca.trim().toLowerCase();
    const visiveis = CATALOGO.filter(
      (a) =>
        filtro.length === 0 ||
        a.rotulo.toLowerCase().includes(filtro) ||
        a.tipo.toLowerCase().includes(filtro),
    );
    return GRUPOS_PALETA.map((grupo) => ({
      grupo,
      itens: visiveis.filter((a) => a.grupo === grupo),
    })).filter((g) => g.itens.length > 0);
  }, [busca]);

  return (
    <div className="flex h-full w-44 flex-none flex-col border-r border-line bg-surface2">
      <div className="border-b border-line p-2">
        <input
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          placeholder="Buscar atividade…"
          aria-label="Buscar atividade da paleta"
          className="w-full rounded-md border border-line2 bg-white px-2 py-1 text-[11.5px] outline-none focus:border-blue"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {grupos.length === 0 && (
          <div className="px-1 py-2 text-[11px] text-muted">Nada encontrado.</div>
        )}
        {grupos.map(({ grupo, itens }) => (
          <div key={grupo} className="mb-2">
            <div className="mb-1 px-1 text-[9.5px] font-bold uppercase tracking-[.08em] text-faint">
              {grupo}
            </div>
            <div className="grid gap-1">
              {itens.map((a) => (
                <div
                  key={a.tipo}
                  draggable
                  title={a.tooltip}
                  onDragStart={(e) => {
                    e.dataTransfer.setData("application/jornada-tipo", a.tipo);
                    e.dataTransfer.effectAllowed = "move";
                  }}
                  className="flex cursor-grab items-center gap-2 rounded-md border border-line bg-white px-2 py-1.5 text-[11.5px] font-bold text-steel shadow-tile transition-colors hover:border-blue active:cursor-grabbing"
                >
                  <span
                    className={`grid h-5 w-5 flex-none place-items-center text-[10px] text-white ${
                      a.categoria === "flow" ? "rotate-45 rounded-[3px]" : "rounded-full"
                    }`}
                    style={{ background: COR_CATEGORIA[a.categoria] }}
                  >
                    <span className={a.categoria === "flow" ? "-rotate-45" : undefined}>
                      {a.icone}
                    </span>
                  </span>
                  {a.rotulo}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="border-t border-line px-2 py-1.5 text-[9.5px] leading-snug text-faint">
        Arraste para o canvas. Tudo que se desenha é materializável 1:1 no SFMC (§5).
      </div>
    </div>
  );
}
