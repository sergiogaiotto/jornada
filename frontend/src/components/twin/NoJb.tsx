/**
 * Nó custom do canvas T7 na paleta Journey Builder (SDD §12 / mock .jbn): tile com
 * ícone + rótulo + volumetria. Entry verde (círculo), mensagens teal, flow control
 * laranja (LOSANGO para splits, círculo para waits), otimização roxa, updates azul,
 * meta/exit cinza — quem vive no JB reconhece cada nó à primeira vista.
 */
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

export type CategoriaJb = "entry" | "msg" | "flow" | "wait" | "ein" | "upd" | "exit";

export type DadosNoJb = {
  rotulo: string;
  categoria: CategoriaJb;
  icone: string;
  volumetria?: string;
  /** lint/422 apontando este nó (editor T7) — anel vermelho */
  erro?: boolean;
};

export type NoJbFlow = Node<DadosNoJb, "jb">;

const COR_TILE: Record<CategoriaJb, string> = {
  entry: "bg-jb-entry rounded-full",
  msg: "bg-jb-msg rounded-md",
  flow: "bg-jb-flow rounded-[5px] rotate-45", // losango laranja (splits)
  wait: "bg-jb-flow rounded-full",
  ein: "bg-jb-ein rounded-md",
  upd: "bg-jb-upd rounded-md",
  exit: "bg-jb-exit rounded-md",
};

export function NoJb({ data, selected }: NodeProps<NoJbFlow>) {
  const losango = data.categoria === "flow";
  return (
    <div className="w-[104px] text-center">
      <Handle
        type="target"
        position={Position.Left}
        className="!h-1.5 !w-1.5 !border-0 !bg-line2"
      />
      <div
        className={`mx-auto grid place-items-center text-white shadow-tile ${COR_TILE[data.categoria]} ${
          losango ? "mt-1 h-7 w-7" : "h-9 w-9"
        } ${data.erro ? "ring-2 ring-crit ring-offset-2" : selected ? "ring-2 ring-blue ring-offset-2" : ""}`}
      >
        <span
          className={
            losango ? "-rotate-45 text-[10px] font-extrabold leading-none" : "text-[14px] leading-none"
          }
        >
          {data.icone}
        </span>
      </div>
      <div className={`text-[10.5px] font-bold leading-tight text-steel ${losango ? "mt-1.5" : "mt-1"}`}>
        {data.rotulo}
      </div>
      {data.volumetria && (
        <div className="text-[9.5px] leading-tight text-faint">{data.volumetria}</div>
      )}
      <Handle
        type="source"
        position={Position.Right}
        className="!h-1.5 !w-1.5 !border-0 !bg-line2"
      />
    </div>
  );
}
