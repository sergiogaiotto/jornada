/**
 * Rail esquerdo colapsável — chrome vermelho Claro (#D0271C), item ativo #A81E14 com
 * filete branco à esquerda (fidelidade ao mock). Itens de OS apontam para a OS em foco.
 */
import { NavLink, useLocation } from "react-router-dom";

import { useUi } from "../../stores/ui";

interface Item {
  rotulo: string;
  /** rota absoluta ou sub-rota de OS (prefixo "os:") */
  destino: string;
}

interface Secao {
  titulo: string;
  itens: Item[];
}

const SECOES: Secao[] = [
  {
    titulo: "Principal",
    itens: [
      { rotulo: "Cockpit", destino: "/" },
      { rotulo: "Briefing · Ideação", destino: "os:briefing" },
      { rotulo: "Validação", destino: "os:validacao" },
      { rotulo: "War Room", destino: "os:warroom" },
      { rotulo: "Esteira", destino: "os:workflow" },
    ],
  },
  {
    titulo: "Produção",
    itens: [
      { rotulo: "Audiência", destino: "os:audiencia" },
      { rotulo: "Data Cloud", destino: "os:datacloud" },
      { rotulo: "Criativo", destino: "os:criativo" },
      { rotulo: "Twin · Jornada", destino: "os:twin" },
    ],
  },
  {
    titulo: "Avaliação",
    itens: [
      { rotulo: "Ensaio Geral", destino: "os:simulacao" },
      { rotulo: "QA", destino: "os:portoes" },
      { rotulo: "Pré-voo", destino: "os:prevoo" },
    ],
  },
  {
    titulo: "Operação",
    itens: [
      { rotulo: "Lançamento", destino: "os:lancamento" },
      { rotulo: "Monitoramento", destino: "os:monitor" },
      { rotulo: "Pergunte aos Dados", destino: "os:perguntas" },
      { rotulo: "Otimização · Retro", destino: "os:retro" },
    ],
  },
  {
    titulo: "Plataforma",
    itens: [{ rotulo: "Ateliê de Agentes", destino: "/atelie" }],
  },
];

function ItemRail({ item }: { item: Item }) {
  const colapsado = useUi((s) => s.railColapsado);
  const osAtualId = useUi((s) => s.osAtualId);
  const { pathname } = useLocation();

  const deOs = item.destino.startsWith("os:");
  const sub = deOs ? item.destino.slice(3) : null;
  const href = deOs ? (osAtualId ? `/os/${osAtualId}/${sub}` : null) : item.destino;
  const ativo = deOs
    ? pathname.endsWith(`/${sub}`) || pathname.includes(`/${sub}/`)
    : item.destino === "/"
      ? pathname === "/"
      : pathname.startsWith(item.destino);

  const classes = [
    "flex items-center gap-2 py-[5px] text-[13px] transition-colors",
    colapsado ? "justify-center px-0" : "px-3",
    ativo
      ? "border-l-2 border-white bg-claro-dark pl-[10px] font-semibold text-white"
      : "text-claro-rose hover:bg-claro-dark/60 hover:text-white",
    ativo && colapsado ? "pl-0 border-l-0" : "",
  ].join(" ");

  const icone = (
    <span
      className={`inline-block h-[9px] w-[9px] flex-none rounded-[3px] ${ativo ? "bg-white" : "bg-claro-icon"}`}
    />
  );

  if (!href) {
    return (
      <span
        data-tour-id={item.destino}
        className={`${classes} cursor-not-allowed opacity-40`}
        title={`${item.rotulo} — selecione uma OS no Cockpit`}
      >
        {icone}
        {!colapsado && <span className="truncate">{item.rotulo}</span>}
      </span>
    );
  }

  return (
    <NavLink to={href} data-tour-id={item.destino} className={classes} title={item.rotulo}>
      {icone}
      {!colapsado && <span className="truncate">{item.rotulo}</span>}
    </NavLink>
  );
}

export function Rail() {
  const colapsado = useUi((s) => s.railColapsado);
  const alternarRail = useUi((s) => s.alternarRail);

  return (
    <nav
      aria-label="Navegação principal"
      className={`flex flex-none flex-col gap-px overflow-y-auto bg-claro pb-3 pt-2 transition-all ${
        colapsado ? "w-12" : "w-52"
      }`}
    >
      {SECOES.map((secao) => (
        <div key={secao.titulo}>
          {!colapsado && (
            <div className="px-3 pb-1 pt-3 text-[10px] uppercase tracking-[.12em] text-claro-rose2">
              {secao.titulo}
            </div>
          )}
          {colapsado && <div className="mx-3 my-2 border-t border-claro-dark" />}
          {secao.itens.map((item) => (
            <ItemRail key={item.rotulo} item={item} />
          ))}
        </div>
      ))}
      <div className="mt-auto pt-3">
        <button
          type="button"
          onClick={alternarRail}
          className="flex w-full items-center gap-2 px-3 py-1.5 text-[12px] text-claro-rose2 hover:text-white"
          title={colapsado ? "Expandir menu" : "Colapsar menu"}
        >
          <span className="inline-block h-[9px] w-[9px] rounded-[3px] bg-claro-icon" />
          {!colapsado && <span>Colapsar</span>}
          <span className="ml-auto pr-1">{colapsado ? "»" : "«"}</span>
        </button>
      </div>
    </nav>
  );
}
