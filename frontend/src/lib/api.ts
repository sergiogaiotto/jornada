/**
 * Client de API tipado — convenções do SDD §8:
 * prefixo `/api/v1` (proxy Vite → localhost:8000) · auth Bearer (dev: token estático
 * `dev-<papel>`) · header `X-Tenant` obrigatório · erros RFC-7807 (problem+json) ·
 * mutações aceitam `Idempotency-Key`.
 */
import type { Problem } from "./types";

const BASE = "/api/v1";

// Dev: papel com escrita (analista|lider) — configurável sem rebuild via localStorage.
const TOKEN_PADRAO = "dev-analista";
const TENANT_PADRAO = "torre-movel";

export function devToken(): string {
  return localStorage.getItem("jornada.token") ?? TOKEN_PADRAO;
}

export function tenant(): string {
  return localStorage.getItem("jornada.tenant") ?? TENANT_PADRAO;
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

export async function api<T>(path: string, opcoes: Opcoes = {}): Promise<T> {
  const { method = "GET", body, idempotencyKey, signal } = opcoes;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${devToken()}`,
    "X-Tenant": tenant(),
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  });

  if (!res.ok) throw new ApiError(await problemDe(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const get = <T>(path: string, signal?: AbortSignal) => api<T>(path, { signal });

export const post = <T>(path: string, body?: unknown, idempotencyKey?: string) =>
  api<T>(path, { method: "POST", body, idempotencyKey });

export const patch = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: "PATCH", body });

export const put = <T>(path: string, body?: unknown) => api<T>(path, { method: "PUT", body });

/** Mensagem apresentável de qualquer erro (ApiError → detail RFC-7807). */
export function mensagemDeErro(erro: unknown): string {
  if (erro instanceof ApiError) return erro.message;
  if (erro instanceof Error) return erro.message;
  return String(erro);
}
