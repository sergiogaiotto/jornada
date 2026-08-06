/**
 * Administração de USUÁRIOS (emenda E04/G01) — só para o papel `admin`.
 *
 * Não há camada de e-mail no projeto (SMTP_URL existe no config e não tem consumidor),
 * então não existe convite por link: o admin cria a conta com uma SENHA PROVISÓRIA que
 * aparece UMA ÚNICA VEZ nesta tela e a entrega pelo canal dele. Quem recebe é obrigado
 * a trocá-la no 1º acesso (`senha_expirada`).
 *
 * QUEM GERA A SENHA É O CLIENTE: o contrato de `POST /auth/usuarios` e de
 * `.../resetar-senha` RECEBE `senha_provisoria` e devolve `UsuarioOut` — sem eco do
 * segredo. Isso é bom (a senha não trafega de volta nem entra em log de resposta) e
 * exige rigor aqui: a geração usa `crypto.getRandomValues`, nunca `Math.random`, que
 * não é criptográfico e produziria senhas previsíveis a partir do estado do PRNG.
 *
 * Nada de senha provisória em log, em URL ou em cache de query: ela vive só no estado
 * local desta tela e some no primeiro reload — por isso o aviso explícito de "copie
 * agora" e o botão de copiar com fallback (a app roda em HTTP puro hoje, e a
 * `navigator.clipboard` só existe em contexto seguro).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { get, post } from "../lib/api";
import { eAdmin, useSessao, type UsuarioOut } from "../lib/sessao";

/** Papéis do RBAC (§8-M0) — lista FECHADA servida por `GET /auth/papeis`. */
const PAPEIS_FALLBACK: string[] = [
  "solicitante",
  "analista",
  "lider",
  "aprovador",
  "dpo",
  "admin",
];

const CHAVE_LISTA = ["auth", "usuarios"] as const;

/**
 * Senha provisória gerada no cliente (o backend não gera — ver o cabeçalho).
 *
 * 20 caracteres de um alfabeto sem ambiguidade visual (nada de O/0, l/1/I): esta senha
 * será DITADA ou colada num chat, e um caractere lido errado vira um chamado de suporte.
 * Amostragem por rejeição para não enviesar a distribuição com o módulo (`% n` favorece
 * os primeiros símbolos quando 256 não é múltiplo do alfabeto). Passa na política do
 * servidor por construção: 20 > 12, sem espaços, sem repetição única.
 */
function gerarSenhaProvisoria(tamanho = 20): string {
  const alfabeto = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789-_";
  const limite = 256 - (256 % alfabeto.length);
  let senha = "";
  const buffer = new Uint8Array(1);
  while (senha.length < tamanho) {
    crypto.getRandomValues(buffer);
    if (buffer[0] < limite) senha += alfabeto[buffer[0] % alfabeto.length];
  }
  return senha;
}

/**
 * Copia para a área de transferência. Em HTTP puro (hoje) `navigator.clipboard` não
 * existe: cai no seletor + execCommand. Se nem isso funcionar, o valor continua na tela
 * em um campo selecionável — a senha nunca depende do botão para chegar ao admin.
 */
async function copiar(texto: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(texto);
      return true;
    }
  } catch {
    /* segue para o fallback */
  }
  try {
    const area = document.createElement("textarea");
    area.value = texto;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

/** Senha provisória recém-emitida — vive só aqui, some no reload. */
interface Emitida {
  usuario: string;
  senha: string;
}

function CaixaSenhaProvisoria({ dados, aoFechar }: { dados: Emitida; aoFechar: () => void }) {
  const [copiado, setCopiado] = useState<boolean | null>(null);

  return (
    <div className="mb-3 rounded-lg border border-warn-line bg-warn-bg px-4 py-3">
      <div className="text-[12.5px] text-ink">
        <b>Senha provisória de {dados.usuario}</b> — aparece <b>uma única vez</b>.
        Entregue pessoalmente; o usuário será obrigado a trocá-la no primeiro acesso.
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          readOnly
          value={dados.senha}
          onFocus={(e) => e.currentTarget.select()}
          aria-label="Senha provisória"
          className="min-w-[240px] flex-1 rounded-md border border-line bg-white px-3 py-2 font-mono text-[13px] outline-none"
        />
        <button
          type="button"
          className="mbtn !py-2"
          onClick={() => {
            void copiar(dados.senha).then(setCopiado);
          }}
        >
          {copiado === true ? "Copiado ✓" : "Copiar"}
        </button>
        <button type="button" className="mbtn-gh !py-2" onClick={aoFechar}>
          Já anotei — esconder
        </button>
      </div>
      {copiado === false && (
        <div className="mt-1 text-[11px] text-crit">
          O navegador bloqueou a cópia automática (app em HTTP). Selecione o texto acima e
          copie manualmente.
        </div>
      )}
    </div>
  );
}

export function Usuarios() {
  const sessao = useSessao((s) => s.sessao);
  const queryClient = useQueryClient();

  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [papeis, setPapeis] = useState<string[]>(["analista"]);
  const [provisoria, setProvisoria] = useState<Emitida | null>(null);

  const admin = eAdmin(sessao);

  const lista = useQuery({
    queryKey: CHAVE_LISTA,
    queryFn: ({ signal }) => get<UsuarioOut[]>("/auth/usuarios", signal),
    enabled: admin,
  });

  // Lista fechada de papéis vinda do servidor (§8-M0): duplicar a lista no front é
  // como ela sai de sincronia. O fallback cobre backend antigo, não substitui.
  const papeisDisponiveis = useQuery({
    queryKey: ["auth", "papeis"],
    queryFn: ({ signal }) => get<string[]>("/auth/papeis", signal),
    enabled: admin,
  });

  const invalidar = () => queryClient.invalidateQueries({ queryKey: CHAVE_LISTA });

  const criar = useMutation({
    mutationFn: async () => {
      const senha = gerarSenhaProvisoria();
      const criado = await post<UsuarioOut>("/auth/usuarios", {
        nome: nome.trim(),
        email: email.trim(),
        papeis,
        senha_provisoria: senha,
      });
      return { usuario: criado.nome, senha };
    },
    onSuccess: (emitida) => {
      setProvisoria(emitida);
      setNome("");
      setEmail("");
      setPapeis(["analista"]);
      void invalidar();
    },
  });

  const desativar = useMutation({
    mutationFn: (usuario: UsuarioOut) =>
      post<UsuarioOut>(`/auth/usuarios/${usuario.id}/desativar`),
    onSuccess: () => void invalidar(),
  });

  const resetar = useMutation({
    mutationFn: async (usuario: UsuarioOut) => {
      const senha = gerarSenhaProvisoria();
      await post<UsuarioOut>(`/auth/usuarios/${usuario.id}/resetar-senha`, {
        senha_provisoria: senha,
      });
      return { usuario: usuario.nome, senha };
    },
    onSuccess: (emitida) => {
      setProvisoria(emitida);
      void invalidar();
    },
  });

  if (!admin) {
    return (
      <>
        <TituloTela titulo="Usuários" subtitulo="Administração de acesso" />
        <EstadoVazio>
          Esta tela é restrita ao papel <b>admin</b>. Seu acesso atual:{" "}
          {sessao?.papeis.join(", ") ?? "—"}.
        </EstadoVazio>
      </>
    );
  }

  function submeterCriacao(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    if (nome.trim().length === 0 || email.trim().length === 0 || papeis.length === 0) return;
    criar.mutate();
  }

  const usuarios = lista.data ?? [];

  return (
    <>
      <TituloTela
        titulo="Usuários"
        subtitulo={`Acesso à plataforma · tenant ${sessao?.tenant_id ?? "—"} · senha provisória entregue pelo admin (não há e-mail)`}
      />

      {provisoria && (
        <CaixaSenhaProvisoria dados={provisoria} aoFechar={() => setProvisoria(null)} />
      )}

      {lista.error != null && <BannerErro erro={lista.error} contexto="Lista de usuários" />}
      {criar.error != null && <BannerErro erro={criar.error} contexto="Criar usuário" />}
      {desativar.error != null && <BannerErro erro={desativar.error} contexto="Desativar" />}
      {resetar.error != null && <BannerErro erro={resetar.error} contexto="Resetar senha" />}

      {/* ------------------------------------------------------- criação */}
      <form onSubmit={submeterCriacao} className="mcard mb-4">
        <div className="mb-2 text-[10px] font-bold uppercase tracking-[.1em] text-faint">
          Novo usuário
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label htmlFor="novo-nome" className="flex-1 text-[11px] font-bold text-slatex">
            Nome
            <input
              id="novo-nome"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              required
              className="mt-1 w-full rounded-md border border-line px-3 py-2 text-[13px] font-normal outline-none focus:border-blue"
            />
          </label>
          <label htmlFor="novo-email" className="flex-1 text-[11px] font-bold text-slatex">
            E-mail ou login
            {/* Mesmo motivo do campo da tela de login: `type="email"` + `required` faz o
                navegador barrar a submissão de qualquer identificador sem `@`, e o
                backend aceita um DE PROPÓSITO (`normalizar_email` — o root do projeto é
                `sergio.gaiotto`). Com o campo tipado como e-mail o admin não consegue
                criar uma segunda conta no formato que o próprio sistema usa. */}
            <input
              id="novo-email"
              type="text"
              inputMode="email"
              autoComplete="off"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              maxLength={320}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="mt-1 w-full rounded-md border border-line px-3 py-2 text-[13px] font-normal outline-none focus:border-blue"
            />
          </label>
          <button type="submit" className="mbtn !py-2" disabled={criar.isPending}>
            {criar.isPending ? "Criando…" : "Criar com senha provisória"}
          </button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11.5px]">
          <span className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
            Papéis
          </span>
          {(papeisDisponiveis.data ?? PAPEIS_FALLBACK).map((papel) => {
            const marcado = papeis.includes(papel);
            return (
              <label key={papel} className="flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={marcado}
                  onChange={() =>
                    setPapeis((atuais) =>
                      marcado ? atuais.filter((p) => p !== papel) : [...atuais, papel],
                    )
                  }
                />
                {papel}
              </label>
            );
          })}
          {papeis.length === 0 && (
            <span className="text-[11px] text-crit">Escolha ao menos um papel.</span>
          )}
        </div>
      </form>

      {/* --------------------------------------------------------- lista */}
      {lista.isLoading && <div className="text-[13px] text-muted">Carregando usuários…</div>}
      {!lista.isLoading && usuarios.length === 0 && lista.error == null && (
        <EstadoVazio>Nenhum usuário além do seu — crie o primeiro acima.</EstadoVazio>
      )}

      {usuarios.length > 0 && (
        <div className="mcard overflow-x-auto !px-0 !py-0">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-line text-left text-[10px] uppercase tracking-[.08em] text-faint">
                <th className="px-4 py-2">Nome</th>
                <th className="px-4 py-2">E-mail</th>
                <th className="px-4 py-2">Papéis</th>
                <th className="px-4 py-2">Situação</th>
                <th className="px-4 py-2">Último acesso</th>
                <th className="px-4 py-2">Ações</th>
              </tr>
            </thead>
            <tbody>
              {usuarios.map((u) => {
                const eu = u.email === sessao?.email;
                return (
                  <tr key={u.id} className="border-b border-linesoft last:border-0">
                    <td className="px-4 py-2 font-semibold text-ink2">
                      {u.nome}
                      {eu && <span className="ml-1 text-[11px] text-faint">(você)</span>}
                    </td>
                    <td className="px-4 py-2 text-slatex">{u.email}</td>
                    <td className="px-4 py-2">
                      <span className="flex flex-wrap gap-1">
                        {u.papeis.map((p) => (
                          <span key={p} className={p === "admin" ? "mchip-v" : "mchip-n"}>
                            {p}
                          </span>
                        ))}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      <span className="flex flex-wrap gap-1">
                        <span className={u.ativo ? "mchip-g" : "mchip-r"}>
                          {u.ativo ? "ativo" : "desativado"}
                        </span>
                        {u.senha_expirada && <span className="mchip-w">senha provisória</span>}
                        {/* Bloqueio por tentativas (G01): o reset de senha destrava. */}
                        {u.bloqueado_ate && new Date(u.bloqueado_ate) > new Date() && (
                          <span className="mchip-r">
                            bloqueado até{" "}
                            {new Date(u.bloqueado_ate).toLocaleTimeString("pt-BR", {
                              hour: "2-digit",
                              minute: "2-digit",
                            })}
                          </span>
                        )}
                      </span>
                    </td>
                    <td className="px-4 py-2 tabular-nums text-slatex">
                      {u.ultimo_acesso
                        ? new Date(u.ultimo_acesso).toLocaleString("pt-BR")
                        : "nunca entrou"}
                    </td>
                    <td className="px-4 py-2">
                      <span className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          className="mbtn-gh"
                          disabled={resetar.isPending}
                          title="Emite nova senha provisória, revoga as sessões e destrava bloqueio por tentativas"
                          onClick={() => resetar.mutate(u)}
                        >
                          Resetar senha
                        </button>
                        {/* Desativar a si mesmo tranca o admin para fora da própria
                            administração — o servidor também deve recusar. Não há
                            REATIVAR no contrato G01: uma vez desativado, só por banco
                            (está no relatório da frente como pendência). */}
                        <button
                          type="button"
                          className="mbtn-rd"
                          disabled={desativar.isPending || eu || !u.ativo}
                          title={
                            eu
                              ? "Você não pode desativar a própria conta"
                              : !u.ativo
                                ? "Já desativado — não há rota de reativação no backend"
                                : "Desativa e revoga as sessões desta pessoa"
                          }
                          onClick={() => desativar.mutate(u)}
                        >
                          Desativar
                        </button>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
