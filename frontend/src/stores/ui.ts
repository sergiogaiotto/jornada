/**
 * Estado de UI do shell (zustand): rail colapsável, slot do painel direito contextual
 * (casa do copiloto — SDD §12), OS corrente para o rail e paleta ⌘K.
 */
import type { ReactNode } from "react";
import { create } from "zustand";

interface UiState {
  railColapsado: boolean;
  alternarRail: () => void;

  /** conteúdo do painel direito contextual — cada tela publica o seu (slot) */
  painel: ReactNode;
  setPainel: (n: ReactNode) => void;

  /** OS em foco (rota /os/:id/*) — o rail aponta os itens de produção para ela */
  osAtualId: string | null;
  setOsAtualId: (id: string | null) => void;

  cmdkAberto: boolean;
  setCmdkAberto: (aberto: boolean) => void;
}

export const useUi = create<UiState>((set) => ({
  railColapsado: false,
  alternarRail: () => set((s) => ({ railColapsado: !s.railColapsado })),

  painel: null,
  setPainel: (n) => set({ painel: n }),

  osAtualId: null,
  setOsAtualId: (id) => set({ osAtualId: id }),

  cmdkAberto: false,
  setCmdkAberto: (aberto) => set({ cmdkAberto: aberto }),
}));
