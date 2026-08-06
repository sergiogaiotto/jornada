/**
 * Topbar vermelha Claro (fidelidade ao mock): logo Jornada · breadcrumb · pill ⌘K ·
 * pill de fase da OS em foco · menu do usuário.
 *
 * Emenda E04: o avatar deixou de ser o "SG" decorativo com seletor de papel por
 * localStorage (o usuário escolhia quem era). Agora mostra QUEM está logado, o papel e
 * o tenant vindos da SESSÃO, e é a única porta de saída (logout de verdade, revogando
 * a sessão no servidor).
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { DropdownGuia } from "../../guia/DropdownGuia";
import { useFecharForaEsc, useOs } from "../../lib/hooks";
import { eAdmin, iniciais, papelPrincipal, useSessao } from "../../lib/sessao";
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
  portoes: "QA",
  prevoo: "Pré-voo",
  lancamento: "Lançamento",
  monitor: "Monitoramento",
  perguntas: "Pergunte aos Dados",
  retro: "Otimização & Retro",
};

/** Menu do usuário logado — identidade, troca de senha, administração e saída. */
function MenuUsuario() {
  const navegar = useNavigate();
  const queryClient = useQueryClient();
  const sessao = useSessao((s) => s.sessao);
  const sair = useSessao((s) => s.sair);
  const [aberto, setAberto] = useState(false);
  const fechar = useCallback(() => setAberto(false), []);
  const raiz = useFecharForaEsc(aberto, fechar);

  if (!sessao) return null;

  async function encerrar() {
    setAberto(false);
    await sair();
    // Cache do TanStack guarda dado de cliente (PII): sair sem limpar deixaria a tela
    // do próximo login pintada com os dados do usuário anterior.
    queryClient.clear();
    navegar("/login", { replace: true });
  }

  return (
    <div ref={raiz} className="relative">
      <button
        type="button"
        onClick={() => setAberto((a) => !a)}
        aria-haspopup="menu"
        aria-expanded={aberto}
        title={`${sessao.nome} · ${papelPrincipal(sessao)}`}
        className="flex items-center gap-2 rounded-full bg-claro-dark py-0.5 pl-0.5 pr-2.5 text-[11px] text-claro-rose hover:text-white"
      >
        <span className="grid h-6 w-6 place-items-center rounded-full bg-claro-avatar text-[10px] font-bold text-white">
          {iniciais(sessao.nome)}
        </span>
        <span className="max-w-[160px] truncate">
          {sessao.nome} · {papelPrincipal(sessao)}
        </span>
      </button>

      {aberto && (
        <div
          role="menu"
          className="absolute right-0 top-9 z-50 w-64 rounded-lg border border-line bg-white p-2 text-ink shadow-card"
        >
          <div className="border-b border-linesoft px-2 pb-2 text-[12px]">
            <div className="font-bold text-ink2">{sessao.nome}</div>
            <div className="text-[11.5px] text-muted">{sessao.email}</div>
            <div className="mt-1 flex flex-wrap gap-1">
              {sessao.papeis.map((p) => (
                <span key={p} className={p === "admin" ? "mchip-v" : "mchip-n"}>
                  {p}
                </span>
              ))}
              <span className="mchip-b">{sessao.tenant_id}</span>
            </div>
          </div>
          <button
            type="button"
            role="menuitem"
            className="w-full rounded px-2 py-1.5 text-left text-[12.5px] hover:bg-surface2"
            onClick={() => {
              setAberto(false);
              navegar("/trocar-senha");
            }}
          >
            Trocar senha
          </button>
          {eAdmin(sessao) && (
            <button
              type="button"
              role="menuitem"
              className="w-full rounded px-2 py-1.5 text-left text-[12.5px] hover:bg-surface2"
              onClick={() => {
                setAberto(false);
                navegar("/usuarios");
              }}
            >
              Usuários
            </button>
          )}
          <button
            type="button"
            role="menuitem"
            className="w-full rounded px-2 py-1.5 text-left text-[12.5px] text-crit hover:bg-crit-soft"
            onClick={() => void encerrar()}
          >
            Sair
          </button>
        </div>
      )}
    </div>
  );
}

export function Topbar() {
  const { pathname } = useLocation();
  const osAtualId = useUi((s) => s.osAtualId);
  const setCmdkAberto = useUi((s) => s.setCmdkAberto);
  const tenantDaSessao = useSessao((s) => s.sessao?.tenant_id ?? "");
  const emOs = pathname.startsWith("/os/");
  const { data: os } = useOs(emOs ? osAtualId : null);

  const secao = emOs ? (ROTULO_SECAO[pathname.split("/")[3] ?? ""] ?? "") : "";
  const breadcrumb = emOs
    ? `${os?.codigo ?? "OS"}${secao ? ` · ${secao}` : ""}`
    : pathname.startsWith("/atelie")
      ? "Ateliê de Agentes"
      : `Portfólio · ${tenantDaSessao === "torre-movel" ? "Torre Móvel" : tenantDaSessao}`;

  return (
    <header className="flex flex-none items-center gap-3 bg-claro px-4 py-2 text-[13px] text-claro-paper">
      <Link to="/" className="flex items-center gap-2 font-extrabold tracking-[.02em]">
        <span className="inline-block h-2.5 w-2.5 rounded-[3px] bg-white" />
        Jornada
      </Link>
      <span className="truncate text-[12px] text-claro-rose2">{breadcrumb}</span>
      <span className="flex-1" />
      <DropdownGuia />
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
      <MenuUsuario />
    </header>
  );
}
