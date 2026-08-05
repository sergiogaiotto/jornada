/**
 * "Guia dos Módulos" — modal do Guia Interativo com o grid das 18 telas
 * (nome, fase do fluxo e descrição curta). Clicar num cartão abre a
 * "Ajuda desta página" pinada naquela tela (conteúdo completo por abas).
 */
import { useEffect } from "react";

import { type ChaveGuia, CONTEUDO_GUIA, ORDEM_GUIA } from "./conteudo";
import { useGuia } from "./store";

/** cor do selo de fase (grupos do fluxo) */
const COR_FASE: Record<string, string> = {
  Principal: "bg-claro-soft text-claro-dark",
  "Produção": "bg-blue-soft text-blue",
  "Avaliação": "bg-viol-soft text-viol",
  "Operação": "bg-good-soft text-good",
  Plataforma: "bg-warn-soft text-warn",
};

export function GuiaModulos() {
  const modo = useGuia((s) => s.modo);
  if (modo !== "modulos") return null;
  return <ModulosAberto />;
}

function ModulosAberto() {
  const fechar = useGuia((s) => s.fechar);
  const abrir = useGuia((s) => s.abrir);

  // Esc fecha o modal
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") fechar();
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [fechar]);

  const abrirAjuda = (chave: ChaveGuia) => abrir("ajuda", chave);

  return (
    <div className="fixed inset-0 z-[70] overflow-y-auto">
      {/* backdrop — clique fecha */}
      <button
        type="button"
        aria-label="Fechar guia dos módulos"
        onClick={fechar}
        className="fixed inset-0 h-full w-full cursor-default bg-ink/40"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Guia dos Módulos"
        className="relative mx-auto my-8 w-[min(960px,calc(100vw-32px))] rounded-2xl border border-line bg-white p-6 shadow-card"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-bold uppercase tracking-[.14em] text-claro">
              Guia Interativo
            </div>
            <h2 className="mt-1 text-[20px] font-semibold text-ink">Guia dos Módulos</h2>
            <p className="mt-1 text-[12.5px] text-muted">
              As 18 telas da Jornada, na ordem do fluxo da campanha. Clique numa tela para abrir a
              ajuda completa — fundamento, campos, casos de uso, exemplo prático e pegadinhas.
            </p>
          </div>
          <button
            type="button"
            onClick={fechar}
            aria-label="Fechar"
            className="grid h-7 w-7 flex-none place-items-center rounded-md text-[16px] text-muted hover:bg-surface2 hover:text-ink"
          >
            ×
          </button>
        </div>

        <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {ORDEM_GUIA.map((chave, i) => {
            const p = CONTEUDO_GUIA[chave];
            return (
              <button
                key={chave}
                type="button"
                onClick={() => abrirAjuda(chave)}
                className="group flex flex-col rounded-xl border border-line bg-surface2 p-3.5 text-left transition-colors hover:border-claro hover:bg-white"
              >
                <div className="flex items-center gap-2">
                  <span className="text-[10.5px] font-bold text-ghost">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${COR_FASE[p.fase] ?? "bg-surface2 text-muted"}`}
                  >
                    {p.fase}
                  </span>
                </div>
                <div className="mt-1.5 text-[13px] font-semibold text-ink group-hover:text-claro-dark">
                  {p.titulo}
                </div>
                <p className="mt-1 text-[11.5px] leading-snug text-muted">{p.descricao}</p>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
