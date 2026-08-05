/** Hooks compartilhados: queries de OS (TanStack Query) e slot do painel contextual. */
import { useQuery } from "@tanstack/react-query";
import { useEffect, type DependencyList, type ReactNode } from "react";

import { get } from "./api";
import type { BriefingOut, OsOut, SaudeOut, WorkflowOut } from "./types";
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

export function useWorkflow(id: string | null | undefined) {
  return useQuery({
    queryKey: ["os", id, "workflow"],
    queryFn: ({ signal }) => get<WorkflowOut>(`/os/${id}/workflow`, signal),
    enabled: Boolean(id),
  });
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
