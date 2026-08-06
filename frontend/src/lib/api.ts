/**
 * Client de API tipado — convenções do SDD §8:
 * prefixo `/api/v1` (proxy Vite → localhost:8000) · sessão por COOKIE httpOnly
 * (`credentials: "include"`) · header `X-Tenant` derivado da SESSÃO · erros RFC-7807
 * (problem+json) · mutações aceitam `Idempotency-Key`.
 *
 * Emenda E04 (frente de autenticação): não existe mais `Authorization: Bearer
 * dev-<papel>` montado no cliente. O token de dev vinha do localStorage, então o
 * NAVEGADOR escolhia papel e tenant — qualquer um digitava `localStorage.setItem
 * ("jornada.token","dev-admin")` e virava admin de outro tenant. A credencial agora é
 * um id opaco de sessão em cookie httpOnly, que JS não lê nem escreve, revogável no
 * servidor. O `X-Tenant` continua sendo enviado (o middleware de `app/main.py` ainda o
 * exige em /api/v1/*), mas com o valor que o SERVIDOR devolveu em `/auth/eu` — asserção
 * redundante conferida contra o portador, nunca mais uma escolha do cliente.
 */
import type { Problem } from "./types";

const BASE = "/api/v1";

/** Sessão ativa espelhada para código FORA do React (este client não tem hooks). */
interface SessaoEspelho {
  nome: string;
  papeis: string[];
  tenant: string;
}

/**
 * Espelho da sessão mantido por `lib/sessao.ts` (que assina a store e chama
 * `definirSessaoAtiva`). A dependência é de MÃO ÚNICA — `sessao.ts` importa `api.ts`,
 * nunca o contrário — para não criar ciclo de módulos (TDZ no boot da SPA).
 */
let sessaoAtiva: SessaoEspelho | null = null;
let aoPerder: (() => void) | null = null;
let aoExpirar: (() => void) | null = null;

/**
 * Tenant usado ENQUANTO não há sessão. O `POST /auth/login` exige `X-Tenant` (o e-mail
 * é único POR tenant, então o tenant faz parte da chave de busca — G01), e nesse
 * instante o servidor ainda não disse nada sobre o usuário. É um NAMESPACE de busca,
 * não uma autorização: quem não tem credencial válida no tenant anunciado leva 401
 * igual, e depois do login o tenant passa a vir do servidor. Configurável no build
 * (`VITE_TENANT`) para instalações fora da torre-movel.
 */
const TENANT_ANTES_DO_LOGIN: string =
  (import.meta.env.VITE_TENANT as string | undefined) ?? "torre-movel";

export function definirSessaoAtiva(sessao: SessaoEspelho | null): void {
  sessaoAtiva = sessao;
}

/**
 * Registra o observador de "sessão caiu" (401 em rota autenticada). Quem redireciona é
 * o React (guarda de rota), não este módulo: navegação imperativa daqui perderia o
 * `location` de origem e brigaria com o router.
 */
export function aoPerderSessao(callback: () => void): void {
  aoPerder = callback;
}

/** Registra o observador de "senha provisória" (403 + `X-Erro-Codigo: senha_expirada`). */
export function aoSenhaExpirada(callback: () => void): void {
  aoExpirar = callback;
}

/** Tenant do usuário logado (do servidor) — `null` antes do login. */
export function tenantDaSessao(): string | null {
  return sessaoAtiva?.tenant ?? null;
}

/**
 * Cabeçalhos de escopo para toda chamada, inclusive as cruas (downloads que não passam
 * por `api()`). Com sessão: o tenant que o SERVIDOR devolveu — asserção redundante que
 * o middleware confere contra o portador (403 se divergir, §8). Sem sessão: o namespace
 * de login, porque o header é obrigatório em /api/v1/* e o backend não isentou /auth/*.
 */
export function cabecalhosDaSessao(): Record<string, string> {
  return { "X-Tenant": tenantDaSessao() ?? TENANT_ANTES_DO_LOGIN };
}

/**
 * Bloco `solicitante` do pedido (§4.1) para o usuário logado — agora vem da SESSÃO
 * autenticada. Sem sessão o pedido não é criado: atribuir um pedido a um nome
 * inventado sujaria a trilha por pessoa (requisito de PII real, não luxo).
 */
export function solicitanteAtual(): Record<string, unknown> {
  if (!sessaoAtiva) {
    throw new Error("Sessão expirada — entre novamente para registrar o pedido.");
  }
  return {
    nome: sessaoAtiva.nome,
    area: sessaoAtiva.papeis[0] ?? "solicitante",
    origem: "app",
  };
}

export class ApiError extends Error {
  readonly problem: Problem;

  constructor(problem: Problem) {
    super(problem.detail ?? problem.title ?? "Erro de API");
    this.name = "ApiError";
    this.problem = problem;
  }

  get status(): number {
    return this.problem.status ?? 0;
  }

  /** Modo degradado do hub LLM (§10.6): 503 com `modo: "degraded"` — UI oferece modo manual. */
  get degradado(): boolean {
    return this.status === 503 && this.problem["modo"] === "degraded";
  }
}

interface Opcoes {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  /** chave de idempotência para mutações (§8) */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

async function problemDe(res: Response): Promise<Problem> {
  try {
    const corpo = (await res.json()) as Problem | { detail?: string };
    if (typeof corpo === "object" && corpo !== null) {
      const p = corpo as Problem;
      return { status: res.status, title: res.statusText, ...p };
    }
  } catch {
    /* corpo não-JSON — cai no problem sintético */
  }
  return { status: res.status, title: res.statusText, detail: `HTTP ${res.status}` };
}

/**
 * Rotas em que 401 é RESPOSTA DE NEGÓCIO, não sessão caída: "senha errada" no login e
 * "senha atual não confere" na troca. Derrubar a sessão num erro de digitação expulsaria
 * o usuário do meio do fluxo — quem chama estas trata o próprio 401. Note que
 * `/auth/usuarios*` NÃO está aqui: lá 401 é sessão morta como em qualquer outra rota.
 */
const ROTAS_SEM_QUEDA: readonly string[] = [
  "/auth/login",
  "/auth/logout",
  "/auth/eu",
  "/auth/trocar-senha",
];

/** Sinal legível por máquina do guard de senha provisória (`app/auth.py`). */
const CABECALHO_CODIGO_ERRO = "X-Erro-Codigo";
const CODIGO_SENHA_EXPIRADA = "senha_expirada";

/**
 * 401 em rota autenticada = sessão inexistente/expirada/revogada → avisa a guarda.
 * 403 com `X-Erro-Codigo: senha_expirada` = credencial VÁLIDA com senha provisória →
 * a guarda leva à troca em vez de exibir um "acesso negado" sem explicação.
 */
function notificarPeloStatus(path: string, res: Response): void {
  if (res.status === 401 && !ROTAS_SEM_QUEDA.includes(path)) aoPerder?.();
  if (res.status === 403 && res.headers.get(CABECALHO_CODIGO_ERRO) === CODIGO_SENHA_EXPIRADA) {
    aoExpirar?.();
  }
}

export async function api<T>(path: string, opcoes: Opcoes = {}): Promise<T> {
  const { method = "GET", body, idempotencyKey, signal } = opcoes;
  const headers: Record<string, string> = { ...cabecalhosDaSessao() };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    // cookie de sessão httpOnly: explícito mesmo sendo mesma-origem, para o dia em que
    // a SPA for servida de outro host que a API.
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (!res.ok) {
    notificarPeloStatus(path, res);
    throw new ApiError(await problemDe(res));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const get = <T>(path: string, signal?: AbortSignal) => api<T>(path, { signal });

export const post = <T>(path: string, body?: unknown, idempotencyKey?: string) =>
  api<T>(path, { method: "POST", body, idempotencyKey });

export const patch = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "PATCH", body });

export const put = <T>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body });

/**
 * Download autenticado (Content-Disposition — ex.: `GET /jornadas/{id}/export`):
 * o cookie de sessão + X-Tenant impedem um <a href> simples; baixa o blob e dispara o
 * save. Devolve o nome do arquivo (do header) e o tamanho em bytes para o toast.
 */
export async function baixar(path: string): Promise<{ filename: string; bytes: number }> {
  const res = await fetch(`${BASE}${path}`, {
    headers: cabecalhosDaSessao(),
    credentials: "include",
  });
  if (!res.ok) {
    notificarPeloStatus(path, res);
    throw new ApiError(await problemDe(res));
  }
  const blob = await res.blob();
  const disposicao = res.headers.get("Content-Disposition") ?? "";
  const filename = /filename="?([^";]+)"?/.exec(disposicao)?.[1] ?? "export";
  const url = URL.createObjectURL(blob);
  const ancora = document.createElement("a");
  ancora.href = url;
  ancora.download = filename;
  document.body.appendChild(ancora);
  ancora.click();
  ancora.remove();
  URL.revokeObjectURL(url);
  return { filename, bytes: blob.size };
}

/** Mensagem apresentável de qualquer erro (ApiError → detail RFC-7807). */
export function mensagemDeErro(erro: unknown): string {
  if (erro instanceof ApiError) return erro.message;
  if (erro instanceof Error) return erro.message;
  return String(erro);
}
