/**
 * Estado do Guia Interativo (zustand — referência visual: plataforma Maestro):
 * modo ativo (tour | modulos | ajuda), passo corrente do tour e dropdown do Topbar.
 * O Tour consome o modo "tour"; os painéis "modulos"/"ajuda" consomem os demais.
 */
import { create } from "zustand";

import type { ChaveGuia } from "./conteudo";

export type ModoGuia = "tour" | "modulos" | "ajuda" | null;

/** Turno do chat "IA, me ajude com esta página" — só na memória da SPA (não persistido). */
export interface MensagemChat {
  papel: "usuario" | "ia";
  texto: string;
  /** bolha de indisponibilidade (503 degraded §10.6) — não entra no histórico enviado */
  degradado?: boolean;
}

interface GuiaState {
  /** modo ativo do guia — null = nenhum painel/overlay aberto */
  modo: ModoGuia;
  /** passo corrente do tour (0-based; o contador exibido é passo+1) */
  passo: number;
  /** dropdown "Guia Interativo" do Topbar aberto */
  dropdownAberto: boolean;
  /** página pinada na Ajuda (aberta pelo Guia dos Módulos/chips); null = segue a rota atual */
  paginaAjuda: ChaveGuia | null;
  /** chat contextual de IA — aberto pelo botão "IA, me ajude" do rodapé da Ajuda */
  chatAberto: boolean;
  /** histórico do chat POR PÁGINA — vive só nesta sessão da SPA (aviso no rodapé do chat) */
  historicoChat: Partial<Record<ChaveGuia, MensagemChat[]>>;

  /** abre um modo do guia (fecha o dropdown e zera o passo do tour); `pagina` pina a Ajuda */
  abrir: (modo: Exclude<ModoGuia, null>, pagina?: ChaveGuia) => void;
  fechar: () => void;
  irParaPasso: (passo: number) => void;
  setDropdownAberto: (aberto: boolean) => void;
  setPaginaAjuda: (pagina: ChaveGuia | null) => void;
  abrirChat: () => void;
  fecharChat: () => void;
  pushMensagemChat: (pagina: ChaveGuia, mensagem: MensagemChat) => void;
}

export const useGuia = create<GuiaState>((set) => ({
  modo: null,
  passo: 0,
  dropdownAberto: false,
  paginaAjuda: null,
  chatAberto: false,
  historicoChat: {},

  abrir: (modo, pagina) =>
    set({ modo, passo: 0, dropdownAberto: false, paginaAjuda: pagina ?? null }),
  fechar: () => set({ modo: null, passo: 0, paginaAjuda: null }),
  irParaPasso: (passo) => set({ passo }),
  setDropdownAberto: (aberto) => set({ dropdownAberto: aberto }),
  setPaginaAjuda: (pagina) => set({ paginaAjuda: pagina }),
  abrirChat: () => set({ chatAberto: true }),
  fecharChat: () => set({ chatAberto: false }),
  pushMensagemChat: (pagina, mensagem) =>
    set((s) => ({
      historicoChat: {
        ...s.historicoChat,
        [pagina]: [...(s.historicoChat[pagina] ?? []), mensagem],
      },
    })),
}));
