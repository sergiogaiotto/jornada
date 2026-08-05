/** Hooks compartilhados: queries de OS (TanStack Query) e slot do painel contextual. */
import { useQuery } from "@tanstack/react-query";
import {
  useEffect,
  useRef,
  type DependencyList,
  type ReactNode,
  type RefObject,
} from "react";

import { get } from "./api";
import type {
  BriefingOut,
  OsOut,
  PedidoOut,
  PedidoResumo,
  SaudeOut,
  WorkflowOut,
} from "./types";
import { useUi } from "../stores/ui";

export function useOsLista() {
  return useQuery({
    queryKey: ["os"],
    queryFn: ({ signal }) => get<OsOut[]>("/os?limit=100", signal),
  });
}

export function useOs(id: string | null | undefined) {
  return useQuery({
    queryKey: ["os", id],
    queryFn: ({ signal }) => get<OsOut>(`/os/${id}`, signal),
    enabled: Boolean(id),
  });
}

export function useSaude(id: string | null | undefined) {
  return useQuery({
    queryKey: ["os", id, "saude"],
    queryFn: ({ signal }) => get<SaudeOut>(`/os/${id}/saude`, signal),
    enabled: Boolean(id),
  });
}

export function useBriefing(id: string | null | undefined) {
  return useQuery({
    queryKey: ["os", id, "briefing"],
    queryFn: ({ signal }) => get<BriefingOut>(`/os/${id}/briefing`, signal),
    enabled: Boolean(id),
  });
}

/** Fila de pedidos do tenant (GET /pedidos — arquivados fora por padrão, §8-M3). */
export function usePedidos() {
  return useQuery({
    queryKey: ["pedidos"],
    queryFn: ({ signal }) => get<PedidoResumo[]>("/pedidos", signal),
  });
}

/** Detalhe completo de um pedido (GET /pedidos/{id} — arquivado segue legível). */
export function usePedido(id: string | null | undefined) {
  return useQuery({
    queryKey: ["pedidos", id],
    queryFn: ({ signal }) => get<PedidoOut>(`/pedidos/${id}`, signal),
    enabled: Boolean(id),
  });
}

export function useWorkflow(id: string | null | undefined) {
  return useQuery({
    queryKey: ["os", id, "workflow"],
    queryFn: ({ signal }) => get<WorkflowOut>(`/os/${id}/workflow`, signal),
    enabled: Boolean(id),
  });
}

/**
 * Fecha um dropdown/popover com clique-fora ou Esc (padrão do DropdownGuia).
 * Retorna o ref a ser colocado no contêiner raiz (botão + painel); enquanto
 * `aberto`, clique fora do contêiner ou tecla Escape chamam `fechar`.
 */
export function useFecharForaEsc(
  aberto: boolean,
  fechar: () => void,
): RefObject<HTMLDivElement> {
  const raiz = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!aberto) return;
    const clique = (e: MouseEvent) => {
      if (raiz.current && !raiz.current.contains(e.target as Node)) fechar();
    };
    const tecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") fechar();
    };
    document.addEventListener("mousedown", clique);
    document.addEventListener("keydown", tecla);
    return () => {
      document.removeEventListener("mousedown", clique);
      document.removeEventListener("keydown", tecla);
    };
  }, [aberto, fechar]);
  return raiz;
}

/**
 * Publica conteúdo no painel direito contextual do shell (slot — SDD §12: o painel
 * é a casa do copiloto). Limpa ao desmontar a tela.
 */
export function usePainelContextual(no: ReactNode, deps: DependencyList) {
  const setPainel = useUi((s) => s.setPainel);
  useEffect(() => {
    setPainel(no);
    return () => setPainel(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}
