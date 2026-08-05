/** Primitivas visuais compartilhadas (gramática dos mocks). */
import type { ReactNode } from "react";

import { ApiError, mensagemDeErro } from "../../lib/api";

export function TituloTela({ titulo, subtitulo }: { titulo: ReactNode; subtitulo?: ReactNode }) {
  return (
    <div className="mb-4">
      <h1 className="text-[19px] font-bold tracking-[-.01em] text-ink2">{titulo}</h1>
      {subtitulo && <div className="text-[12.5px] text-muted">{subtitulo}</div>}
    </div>
  );
}

export function Kpi({
  rotulo,
  valor,
  detalhe,
  tom = "ink",
}: {
  rotulo: string;
  valor: ReactNode;
  detalhe?: ReactNode;
  tom?: "ink" | "good" | "blue" | "crit" | "warn";
}) {
  const cor = {
    ink: "text-ink2",
    good: "text-good",
    blue: "text-blue",
    crit: "text-crit",
    warn: "text-warn",
  }[tom];
  return (
    <div className="mcard min-w-0 flex-1">
      <div className="text-[10px] uppercase tracking-[.06em] text-faint">{rotulo}</div>
      <div className={`text-[22px] font-extrabold tracking-[-.02em] tabular-nums ${cor}`}>
        {valor}
      </div>
      {detalhe && <div className="text-[11.5px] text-muted">{detalhe}</div>}
    </div>
  );
}

export function BarraProgresso({
  pct,
  tom = "blue",
}: {
  pct: number;
  tom?: "blue" | "good" | "warn" | "crit";
}) {
  const cor = { blue: "bg-blue", good: "bg-good", warn: "bg-[#D98E22]", crit: "bg-crit" }[tom];
  return (
    <div className="mbar">
      <i className={cor} style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
    </div>
  );
}

/** Erro RFC-7807 apresentável (detail + extras de domínio quando houver). */
export function BannerErro({ erro, contexto }: { erro: unknown; contexto?: string }) {
  const degradado = erro instanceof ApiError && erro.degradado;
  return (
    <div className="mb-3 rounded-lg border border-warn-line bg-warn-bg px-4 py-3 text-[13px] text-ink">
      <b>{degradado ? "Modo degradado (hub LLM indisponível)" : (contexto ?? "Erro")}:</b>{" "}
      {mensagemDeErro(erro)}
      {degradado && (
        <div className="mt-1 text-[12px] text-muted">
          O caminho crítico não depende de LLM (SDD §10.6) — prossiga em modo manual.
        </div>
      )}
    </div>
  );
}

export function EstadoVazio({ children }: { children: ReactNode }) {
  return (
    <div className="mcard border-dashed py-8 text-center text-[13px] text-muted">{children}</div>
  );
}

export function ChipSaude({ saude }: { saude?: "normal" | "em_risco" }) {
  if (saude === "em_risco") return <span className="mchip-w">Em risco</span>;
  if (saude === "normal") return <span className="mchip-g">Normal</span>;
  return <span className="mchip-n">—</span>;
}
