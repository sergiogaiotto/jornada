/**
 * Topbar vermelha Claro (fidelidade ao mock): logo Jornada · breadcrumb · pill ⌘K ·
 * pill de fase da OS em foco · avatar.
 */
import { Link, useLocation } from "react-router-dom";

import { useOs } from "../../lib/hooks";
import { tenant } from "../../lib/api";
import { useUi } from "../../stores/ui";

const ROTULO_FASE: Record<string, string> = {
  pensada: "Fase 1 · Pensada",
  discutida: "Fase 2 · Discutida",
  criada: "Fase 3 · Criada",
  avaliada: "Fase 4 · Avaliada",
  configurada: "Fase 5 · Configurada",
  disparada: "Fase 6 · Disparada",
  monitorada: "Fase 7 · Monitorada",
  encerrada: "Encerrada",
};

const ROTULO_SECAO: Record<string, string> = {
  briefing: "Briefing",
  validacao: "Validação",
  warroom: "War Room",
  workflow: "Esteira de Produção",
  audiencia: "Audiência",
  datacloud: "Audiência · Data Cloud",
  criativo: "Criativo",
  twin: "Twin · Jornada",
  simulacao: "Ensaio Geral",
  portoes: "Portões",
  prevoo: "Pré-voo",
  lancamento: "Lançamento",
  monitor: "Monitoramento",
  perguntas: "Pergunte aos Dados",
  retro: "Otimização & Retro",
};

export function Topbar() {
  const { pathname } = useLocation();
  const osAtualId = useUi((s) => s.osAtualId);
  const setCmdkAberto = useUi((s) => s.setCmdkAberto);
  const emOs = pathname.startsWith("/os/");
  const { data: os } = useOs(emOs ? osAtualId : null);

  const secao = emOs ? (ROTULO_SECAO[pathname.split("/")[3] ?? ""] ?? "") : "";
  const breadcrumb = emOs
    ? `${os?.codigo ?? "OS"}${secao ? ` · ${secao}` : ""}`
    : pathname.startsWith("/atelie")
      ? "Ateliê de Agentes"
      : `Portfólio · ${tenant() === "torre-movel" ? "Torre Móvel" : tenant()}`;

  return (
    <header className="flex flex-none items-center gap-3 bg-claro px-4 py-2 text-[13px] text-claro-paper">
      <Link to="/" className="flex items-center gap-2 font-extrabold tracking-[.02em]">
        <span className="inline-block h-2.5 w-2.5 rounded-[3px] bg-white" />
        Jornada
      </Link>
      <span className="truncate text-[12px] text-claro-rose2">{breadcrumb}</span>
      <span className="flex-1" />
      <button
        type="button"
        onClick={() => setCmdkAberto(true)}
        className="rounded-full bg-claro-dark px-3 py-0.5 text-[11px] text-claro-rose hover:text-white"
        title="Busca rápida (⌘K / Ctrl+K)"
      >
        ⌘K Buscar
      </button>
      {emOs && os && (
        <span className="rounded-full bg-claro-dark px-3 py-0.5 text-[11px] text-claro-rose">
          {ROTULO_FASE[os.fase] ?? os.fase}
        </span>
      )}
      <span
        className="grid h-6 w-6 place-items-center rounded-full bg-claro-avatar text-[10px] font-bold text-white"
        title="Dev Analista (Bearer dev)"
      >
        SG
      </span>
    </header>
  );
}
