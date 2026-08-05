/**
 * Tour das páginas (Guia Interativo — referência visual: plataforma Maestro):
 * overlay escurecido com spotlight no item do rail (badge "?" como no Maestro),
 * tooltip ancorada com nome+descrição, Anterior/Próximo/Pular e contador N/total.
 * Navega de fato para cada rota ao avançar (ordem = ordem do rail); itens que
 * exigem OS selecionada seguem no tour com aviso quando não há OS em foco.
 * Acessível: Esc fecha, foco preso no tooltip (role="dialog" aria-modal).
 */
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useUi } from "../stores/ui";
import { useGuia } from "./store";

interface PassoTour {
  /** rótulo idêntico ao do rail */
  rotulo: string;
  /** destino idêntico ao do rail — rota absoluta ou sub-rota de OS ("os:sub") */
  destino: string;
  descricao: string;
}

/** Ordem = ordem do rail (Rail.tsx SECOES). O spotlight acha o item via [data-tour-id]. */
export const PASSOS_TOUR: PassoTour[] = [
  {
    rotulo: "Cockpit",
    destino: "/",
    descricao: "Portfólio de OSs: KPIs do dia, kanban pelas 8 fases e saúde derivada de cada campanha.",
  },
  {
    rotulo: "Briefing · Ideação",
    destino: "os:briefing",
    descricao: "Captura do briefing e ideação assistida por IA para dar partida na OS.",
  },
  {
    rotulo: "Validação",
    destino: "os:validacao",
    descricao:
      "Checagem campo a campo contra as fontes — contagem, schema e frescor — com evidência.",
  },
  {
    rotulo: "War Room",
    destino: "os:warroom",
    descricao: "Sala de decisão colaborativa da OS: discussão, atas e encaminhamentos.",
  },
  {
    rotulo: "Esteira",
    destino: "os:workflow",
    descricao: "Esteira de produção: acompanhamento dos módulos e do fluxo da OS de ponta a ponta.",
  },
  {
    rotulo: "Audiência",
    destino: "os:audiencia",
    descricao: "Definição e refinamento da audiência-alvo da campanha.",
  },
  {
    rotulo: "Data Cloud",
    destino: "os:datacloud",
    descricao: "Segmentos e ativação de dados na Data Cloud para a audiência definida.",
  },
  {
    rotulo: "Criativo",
    destino: "os:criativo",
    descricao: "Estúdio criativo: peças, variações por canal e aprovação dos criativos.",
  },
  {
    rotulo: "Twin · Jornada",
    destino: "os:twin",
    descricao: "Desenho da jornada no canvas (digital twin) com blocos do Journey Builder.",
  },
  {
    rotulo: "Ensaio Geral",
    destino: "os:simulacao",
    descricao: "Simulação da jornada com personas sintéticas antes do lançamento.",
  },
  {
    rotulo: "Portões",
    destino: "os:portoes",
    descricao: "Portões de qualidade: critérios objetivos que liberam (ou seguram) a OS.",
  },
  {
    rotulo: "Pré-voo",
    destino: "os:prevoo",
    descricao: "Checklist final pré-lançamento: tudo verificado antes de disparar.",
  },
  {
    rotulo: "Lançamento",
    destino: "os:lancamento",
    descricao: "Disparo da campanha e configuração da telemetria de acompanhamento.",
  },
  {
    rotulo: "Monitoramento",
    destino: "os:monitor",
    descricao: "Previsto × realizado em tempo real: métricas, alertas e saúde da campanha.",
  },
  {
    rotulo: "Pergunte aos Dados",
    destino: "os:perguntas",
    descricao: "Perguntas em linguagem natural sobre a camada semântica de resultados.",
  },
  {
    rotulo: "Otimização · Retro",
    destino: "os:retro",
    descricao: "Otimização contínua, retrospectiva e calibração dos modelos da campanha.",
  },
  {
    rotulo: "Ateliê de Agentes",
    destino: "/atelie",
    descricao: "Configuração dos agentes de IA, políticas (policy-as-code) e auditoria via_ai.",
  },
];

function alvoDoPasso(destino: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-tour-id="${destino}"]`);
}

export function Tour() {
  const modo = useGuia((s) => s.modo);
  if (modo !== "tour") return null;
  return <TourAtivo />;
}

function TourAtivo() {
  const passo = useGuia((s) => s.passo);
  const irParaPasso = useGuia((s) => s.irParaPasso);
  const fechar = useGuia((s) => s.fechar);
  const osAtualId = useUi((s) => s.osAtualId);
  const railColapsado = useUi((s) => s.railColapsado);
  const alternarRail = useUi((s) => s.alternarRail);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [rect, setRect] = useState<DOMRect | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const total = PASSOS_TOUR.length;
  const atual = PASSOS_TOUR[passo];
  const ultimoPasso = passo === total - 1;
  const deOs = atual.destino.startsWith("os:");
  const href = deOs
    ? osAtualId
      ? `/os/${osAtualId}/${atual.destino.slice(3)}`
      : null
    : atual.destino;
  const bloqueado = deOs && !osAtualId;

  // rail expandido durante o tour, para o spotlight mostrar os rótulos
  const railColapsadoInicial = useRef(railColapsado);
  useEffect(() => {
    if (railColapsadoInicial.current) alternarRail();
  }, [alternarRail]);

  // navega de fato para a rota de cada passo (itens sem OS ficam só no highlight)
  useEffect(() => {
    if (href && pathname !== href) navigate(href);
  }, [href, pathname, navigate]);

  // mede o item do rail (re-mede em resize e após a transição de largura do rail)
  useLayoutEffect(() => {
    const medir = () => {
      const el = alvoDoPasso(atual.destino);
      setRect(el ? el.getBoundingClientRect() : null);
    };
    alvoDoPasso(atual.destino)?.scrollIntoView({ block: "nearest" });
    const raf = requestAnimationFrame(medir);
    const timer = window.setTimeout(medir, 260);
    window.addEventListener("resize", medir);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
      window.removeEventListener("resize", medir);
    };
  }, [atual.destino, railColapsado]);

  // Esc fecha, mesmo que o foco escape do tooltip
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") fechar();
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [fechar]);

  // foco inicial (e a cada passo) no botão Próximo
  useEffect(() => {
    tooltipRef.current?.querySelector<HTMLElement>("[data-autofocus]")?.focus();
  }, [passo]);

  // foco preso no tooltip (ciclo de Tab)
  const prenderFoco = (e: React.KeyboardEvent) => {
    if (e.key !== "Tab") return;
    const nos = tooltipRef.current?.querySelectorAll<HTMLElement>("button:not([disabled])");
    if (!nos || nos.length === 0) return;
    const lista = Array.from(nos);
    const primeiro = lista[0];
    const ultimo = lista[lista.length - 1];
    const ativo = document.activeElement as HTMLElement | null;
    if (e.shiftKey && (!ativo || ativo === primeiro || !lista.includes(ativo))) {
      e.preventDefault();
      ultimo.focus();
    } else if (!e.shiftKey && ativo === ultimo) {
      e.preventDefault();
      primeiro.focus();
    }
  };

  const topTooltip = rect
    ? Math.min(Math.max(rect.top - 8, 12), Math.max(window.innerHeight - 260, 12))
    : 120;
  const leftTooltip = rect ? rect.right + 14 : 240;

  return (
    <div className="fixed inset-0 z-[70]">
      {/* escurecimento com "furo" no item do rail (spotlight via box-shadow) */}
      {rect ? (
        <div
          className="pointer-events-none fixed rounded-md ring-2 ring-white/80"
          style={{
            left: rect.left - 4,
            top: rect.top - 3,
            width: rect.width + 8,
            height: rect.height + 6,
            boxShadow: "0 0 0 9999px rgba(15,20,30,.55)",
          }}
        />
      ) : (
        <div className="fixed inset-0 bg-ink/50" />
      )}

      {/* badge "?" no item destacado (como no Maestro) */}
      {rect && (
        <span
          aria-hidden
          className="fixed grid h-5 w-5 place-items-center rounded-full bg-white text-[11px] font-bold text-claro shadow-tile"
          style={{ left: rect.right - 6, top: rect.top - 8 }}
        >
          ?
        </span>
      )}

      {/* tooltip ancorada ao item do rail */}
      <div
        ref={tooltipRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Tour das páginas — passo ${passo + 1} de ${total}: ${atual.rotulo}`}
        onKeyDown={prenderFoco}
        className="fixed w-[300px] rounded-xl border border-line bg-white p-4 shadow-card"
        style={{ left: leftTooltip, top: topTooltip }}
      >
        <div className="text-[10px] uppercase tracking-[.12em] text-muted">
          Tour das páginas · {passo + 1}/{total}
        </div>
        <div className="mt-1 text-[14px] font-semibold text-ink">{atual.rotulo}</div>
        <p className="mt-1 text-[12px] leading-relaxed text-steel">{atual.descricao}</p>
        {bloqueado && (
          <p className="mt-2 rounded-md border border-warn-line bg-warn-bg px-2 py-1.5 text-[11px] text-warn">
            Esta tela precisa de uma OS selecionada — abra uma no Cockpit. O tour continua mesmo
            assim.
          </p>
        )}
        <div className="mt-3 flex items-center gap-2">
          <button type="button" onClick={fechar} className="text-[12px] text-muted hover:text-ink">
            Pular
          </button>
          <span className="flex-1" />
          <button
            type="button"
            disabled={passo === 0}
            onClick={() => irParaPasso(passo - 1)}
            className="rounded-md border border-line px-2.5 py-1 text-[12px] text-steel hover:bg-surface2 disabled:opacity-40"
          >
            Anterior
          </button>
          <button
            type="button"
            data-autofocus
            onClick={() => (ultimoPasso ? fechar() : irParaPasso(passo + 1))}
            className="rounded-md bg-claro px-3 py-1 text-[12px] font-semibold text-white hover:bg-claro-dark"
          >
            {ultimoPasso ? "Concluir" : "Próximo"}
          </button>
        </div>
      </div>
    </div>
  );
}
