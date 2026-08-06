/**
 * Estado de SESSÃO da SPA (frente de autenticação — emenda E04).
 *
 * A credencial NÃO mora aqui: ela é um id opaco em cookie httpOnly que o JS não
 * enxerga. Esta store guarda só o que a UI precisa exibir e decidir (quem é, papéis,
 * tenant, se a senha está expirada) e é sempre um ESPELHO do que `/auth/eu` devolveu —
 * nada é persistido em localStorage de propósito: estado de identidade em storage que o
 * XSS lê e escreve foi exatamente o buraco que esta frente fecha.
 *
 * Contrato REAL do backend (emenda G01 — `backend/api/v1/autenticacao.py`; confira o
 * relatório da frente: divergiu do combinado em três pontos e o cliente seguiu o código):
 *   POST /auth/login {email, senha}                   → 200 EuOut + Set-Cookie (exige X-Tenant)
 *   POST /auth/logout                                 → 204 (idempotente)
 *   GET  /auth/eu                                     → 200 EuOut | 401
 *   POST /auth/trocar-senha {senha_atual, senha_nova} → 200 EuOut (não 204) + cookie rotacionado
 *   GET  /auth/papeis                                 → lista fechada de papéis
 *   /auth/usuarios*                                   → administração (só admin)
 */
import { create } from "zustand";

import { ApiError, aoPerderSessao, aoSenhaExpirada, definirSessaoAtiva, get, post } from "./api";

/** `EuOut` do backend — corpo de `/auth/login`, `/auth/eu` e `/auth/trocar-senha`. */
export interface SessaoOut {
  id: string;
  tenant_id: string;
  email: string;
  nome: string;
  papeis: string[];
  senha_expirada: boolean;
}

/** `UsuarioOut` — `EuOut` + trilha operacional (`GET /auth/usuarios`). */
export interface UsuarioOut extends SessaoOut {
  ativo: boolean;
  criado_em: string | null;
  criado_por: string | null;
  ultimo_acesso: string | null;
  bloqueado_ate: string | null;
}

type EstadoAuth = "desconhecida" | "verificando" | "autenticada" | "anonima";

interface StoreSessao {
  estado: EstadoAuth;
  sessao: SessaoOut | null;

  /** consulta `/auth/eu` uma vez no boot (e após login/logout) */
  verificar: () => Promise<void>;
  entrar: (email: string, senha: string) => Promise<SessaoOut>;
  sair: () => Promise<void>;
  trocarSenha: (senhaAtual: string, senhaNova: string) => Promise<void>;
}

export const useSessao = create<StoreSessao>((set, get_) => ({
  estado: "desconhecida",
  sessao: null,

  verificar: async () => {
    if (get_().estado === "verificando") return;
    set({ estado: "verificando" });
    try {
      const sessao = await get<SessaoOut>("/auth/eu");
      set({ estado: "autenticada", sessao });
    } catch (erro) {
      // 401 = anônimo (caminho normal do primeiro acesso). Qualquer outra falha
      // (rede, 500) também cai em anônimo: sem prova de identidade a SPA NÃO pode
      // presumir sessão — a tela de login informa o erro.
      set({ estado: "anonima", sessao: null });
      if (!(erro instanceof ApiError) || erro.status !== 401) throw erro;
    }
  },

  entrar: async (email, senha) => {
    const sessao = await post<SessaoOut>("/auth/login", { email, senha });
    set({ estado: "autenticada", sessao });
    return sessao;
  },

  sair: async () => {
    try {
      await post<void>("/auth/logout");
    } finally {
      // Falhou o logout no servidor? A sessão local cai do mesmo jeito: o usuário
      // pediu para sair e não pode continuar vendo dado de cliente na tela.
      set({ estado: "anonima", sessao: null });
    }
  },

  trocarSenha: async (senhaAtual, senhaNova) => {
    // O backend devolve o EuOut novo (e rotaciona o cookie): o estado sai da RESPOSTA,
    // sem "chutar" `senha_expirada: false` e sem um GET /auth/eu extra.
    const sessao = await post<SessaoOut>("/auth/trocar-senha", {
      senha_atual: senhaAtual,
      senha_nova: senhaNova,
    });
    set({ estado: "autenticada", sessao });
  },
}));

/** `admin` é o papel que abre a administração de usuários (§8-M0). */
export function eAdmin(sessao: SessaoOut | null): boolean {
  return sessao?.papeis.includes("admin") ?? false;
}

/** Rótulo curto do papel principal para o cabeçalho. */
export function papelPrincipal(sessao: SessaoOut | null): string {
  return sessao?.papeis[0] ?? "—";
}

/** Iniciais para o avatar (mesmo lugar do "SG" fixo que existia no mock). */
export function iniciais(nome: string): string {
  const partes = nome.trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "?";
  const primeira = partes[0][0] ?? "";
  const ultima = partes.length > 1 ? (partes[partes.length - 1][0] ?? "") : "";
  return (primeira + ultima).toUpperCase();
}

// ---------------------------------------------------------------- fiação (E04)

// O client de API não tem hooks: espelha-se a sessão nele a cada mudança para que
// `X-Tenant` e o bloco `solicitante` saiam do SERVIDOR, não do localStorage.
useSessao.subscribe((s) => {
  definirSessaoAtiva(
    s.sessao ? { nome: s.sessao.nome, papeis: s.sessao.papeis, tenant: s.sessao.tenant_id } : null,
  );
});

// 403 com `X-Erro-Codigo: senha_expirada` (app/auth.py) — SPA em cache que bateu numa
// rota comum antes de perguntar quem é. Marca o estado e deixa a guarda levar à troca,
// em vez de mostrar um "acesso negado" enigmático no meio da tela.
aoSenhaExpirada(() => {
  const { sessao } = useSessao.getState();
  if (sessao && !sessao.senha_expirada) {
    useSessao.setState({ sessao: { ...sessao, senha_expirada: true } });
  }
});

// 401 em qualquer rota autenticada derruba a sessão local; a guarda de rota vê o
// estado "anonima" e manda para o login preservando o destino. Sem redirect imperativo
// aqui: é a guarda que sabe de onde o usuário veio.
aoPerderSessao(() => {
  if (useSessao.getState().estado === "anonima") return;
  useSessao.setState({ estado: "anonima", sessao: null });
});
