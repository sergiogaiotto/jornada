/**
 * "Ajuda desta página" — drawer direito do Guia Interativo (referência visual:
 * plataforma Maestro): eyebrow vermelha, título + descrição, abas navegáveis
 * (O que é / Fundamentos / Campos da tela / Casos de uso / Exemplo prático /
 * Pegadinhas), RELACIONADOS como chips que navegam, e rodapé com o botão
 * gradiente "✨ IA, me ajude com esta página!" (hook do chat da próxima fase).
 * Conteúdo por rota em conteudo.ts; página pinada quando aberta pelo Guia dos
 * Módulos, senão segue a rota atual.
 */
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useUi } from "../stores/ui";
import {
  type ChaveGuia,
  CONTEUDO_GUIA,
  chaveDaRota,
  hrefDaChave,
} from "./conteudo";
import { useGuia } from "./store";

const ABAS = [
  { id: "oquee", rotulo: "O que é" },
  { id: "fundamentos", rotulo: "Fundamentos" },
  { id: "campos", rotulo: "Campos da tela" },
  { id: "casos", rotulo: "Casos de uso" },
  { id: "exemplo", rotulo: "Exemplo prático" },
  { id: "pegadinhas", rotulo: "Pegadinhas" },
] as const;

type AbaId = (typeof ABAS)[number]["id"];

export function AjudaPagina() {
  const modo = useGuia((s) => s.modo);
  if (modo !== "ajuda") return null;
  return <AjudaAberta />;
}

function AjudaAberta() {
  const fechar = useGuia((s) => s.fechar);
  const paginaAjuda = useGuia((s) => s.paginaAjuda);
  const setPaginaAjuda = useGuia((s) => s.setPaginaAjuda);
  const abrirChat = useGuia((s) => s.abrirChat);
  const osAtualId = useUi((s) => s.osAtualId);
  const navigate = useNavigate();
  const { pathname } = useLocation();

  const chave: ChaveGuia = paginaAjuda ?? chaveDaRota(pathname);
  const pagina = CONTEUDO_GUIA[chave];
  const [aba, setAba] = useState<AbaId>("oquee");

  // trocar de página volta para a primeira aba
  useEffect(() => {
    setAba("oquee");
  }, [chave]);

  // Esc fecha o drawer
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") fechar();
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [fechar]);

  const irParaRelacionado = (destino: ChaveGuia) => {
    setPaginaAjuda(destino);
    const href = hrefDaChave(destino, osAtualId);
    if (href && pathname !== href) navigate(href);
  };

  return (
    <div className="fixed inset-0 z-[70]">
      {/* backdrop — clique fecha */}
      <button
        type="button"
        aria-label="Fechar ajuda"
        onClick={fechar}
        className="absolute inset-0 h-full w-full cursor-default bg-ink/30"
      />

      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`Ajuda desta página — ${pagina.titulo}`}
        className="absolute right-0 top-0 flex h-full w-full max-w-[430px] flex-col bg-white shadow-card"
      >
        {/* cabeçalho */}
        <div className="border-b border-line px-5 pb-3 pt-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[10px] font-bold uppercase tracking-[.14em] text-claro">
                Ajuda desta página
              </div>
              <h2 className="mt-1 text-[18px] font-semibold leading-tight text-ink">
                {pagina.titulo}
              </h2>
              <p className="mt-1 text-[12px] leading-snug text-muted">{pagina.descricao}</p>
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

          {/* abas */}
          <div
            role="tablist"
            aria-label="Seções da ajuda"
            className="mt-3 flex gap-1 overflow-x-auto"
          >
            {ABAS.map((a) => (
              <button
                key={a.id}
                type="button"
                role="tab"
                aria-selected={aba === a.id}
                onClick={() => setAba(a.id)}
                className={`whitespace-nowrap rounded-full px-3 py-1 text-[11.5px] font-semibold transition-colors ${
                  aba === a.id
                    ? "bg-claro text-white"
                    : "bg-surface2 text-steel hover:bg-claro-soft hover:text-claro-dark"
                }`}
              >
                {a.rotulo}
              </button>
            ))}
          </div>
        </div>

        {/* conteúdo da aba */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {aba === "oquee" && (
            <div className="space-y-3">
              {pagina.oQueE.map((p) => (
                <p key={p.slice(0, 40)} className="text-[12.5px] leading-relaxed text-steel">
                  {p}
                </p>
              ))}
            </div>
          )}

          {aba === "fundamentos" && (
            <dl className="space-y-3">
              {pagina.fundamentos.map((f) => (
                <div key={f.termo} className="rounded-lg border border-line bg-surface2 p-3">
                  <dt className="text-[12px] font-semibold text-ink">{f.termo}</dt>
                  <dd className="mt-0.5 text-[12px] leading-relaxed text-steel">{f.definicao}</dd>
                </div>
              ))}
            </dl>
          )}

          {aba === "campos" && (
            <ul className="space-y-2">
              {pagina.campos.map((c) => (
                <li key={c.campo} className="flex gap-2 border-b border-linesoft pb-2 text-[12px]">
                  <span className="w-[132px] flex-none font-semibold text-ink">{c.campo}</span>
                  <span className="leading-snug text-steel">{c.significado}</span>
                </li>
              ))}
            </ul>
          )}

          {aba === "casos" && (
            <ul className="space-y-2.5">
              {pagina.casosDeUso.map((c) => (
                <li key={c.slice(0, 40)} className="flex gap-2 text-[12.5px] leading-snug text-steel">
                  <span aria-hidden className="mt-[5px] h-[7px] w-[7px] flex-none rounded-[2px] bg-claro" />
                  {c}
                </li>
              ))}
            </ul>
          )}

          {aba === "exemplo" && (
            <div>
              <p className="mb-3 rounded-md bg-blue-soft px-3 py-2 text-[11.5px] leading-snug text-blue">
                Passo a passo com a campanha demo <strong>OS-2026-0457</strong> — siga na própria
                tela.
              </p>
              <ol className="space-y-2.5">
                {pagina.exemplo.map((p, i) => (
                  <li key={p.slice(0, 40)} className="flex gap-2.5 text-[12.5px] leading-snug text-steel">
                    <span className="grid h-5 w-5 flex-none place-items-center rounded-full bg-claro-soft text-[11px] font-bold text-claro-dark">
                      {i + 1}
                    </span>
                    <span className="pt-0.5">{p}</span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {aba === "pegadinhas" && (
            <ul className="space-y-2.5">
              {pagina.pegadinhas.map((p) => (
                <li
                  key={p.slice(0, 40)}
                  className="rounded-md border border-warn-line bg-warn-bg px-3 py-2 text-[12px] leading-snug text-warn"
                >
                  ⚠ {p}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* relacionados + CTA */}
        <div className="border-t border-line px-5 pb-4 pt-3">
          <div className="text-[10px] font-bold uppercase tracking-[.14em] text-muted">
            Relacionados
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {pagina.relacionados.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => irParaRelacionado(r)}
                className="rounded-full border border-line bg-surface2 px-2.5 py-1 text-[11px] font-semibold text-steel transition-colors hover:border-claro hover:bg-claro-soft hover:text-claro-dark"
              >
                {CONTEUDO_GUIA[r].titulo}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={abrirChat}
            className="mt-3 w-full rounded-lg bg-gradient-to-r from-claro-dark to-blue/80 px-4 py-2.5 text-[13px] font-semibold text-white shadow-tile transition-opacity hover:opacity-90"
          >
            ✨ IA, me ajude com esta página!
          </button>
        </div>
      </aside>
    </div>
  );
}
