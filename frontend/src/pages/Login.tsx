/**
 * Tela de LOGIN (emenda E04) — página standalone, sem shell: quem não tem sessão não
 * vê rail, topbar nem nada da operação.
 *
 * Usuários LOCAIS com senha (não há camada de e-mail no projeto — sem "esqueci minha
 * senha" por link; o reset é feito por um admin em /usuarios). Regras da tela:
 *  · a mensagem de erro de credencial é GENÉRICA — dizer "e-mail não cadastrado" vira
 *    oráculo de enumeração de usuários (e, aqui, de quem trabalha na conta do cliente);
 *  · Enter submete (é um <form> de verdade, não um punhado de inputs com onClick);
 *  · foco inicial no e-mail;
 *  · o cache do TanStack Query é zerado no sucesso: dado do usuário anterior não pode
 *    sobreviver a uma troca de identidade na mesma aba.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { BannerErro } from "../components/ui/basics";
import { caminhoInternoSeguro } from "../components/shell/ExigirSessao";
import { ApiError } from "../lib/api";
import { useSessao } from "../lib/sessao";

interface EstadoDeOrigem {
  de?: string;
}

export function Login() {
  const local = useLocation();
  const navegar = useNavigate();
  const queryClient = useQueryClient();

  const estado = useSessao((s) => s.estado);
  const sessao = useSessao((s) => s.sessao);
  const verificar = useSessao((s) => s.verificar);
  const entrar = useSessao((s) => s.entrar);

  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<unknown>(null);
  const [enviando, setEnviando] = useState(false);

  // O destino é peneirado no CONSUMO, não só na origem: `location.state` sobrevive ao
  // histórico (voltar/avançar, restauração de aba) e nada garante que quem o gravou foi
  // a guarda desta versão do código. Destino inválido não é erro de tela — é `/`.
  const destino = caminhoInternoSeguro((local.state as EstadoDeOrigem | null)?.de);

  useEffect(() => {
    if (estado === "desconhecida") void verificar().catch(() => undefined);
  }, [estado, verificar]);

  if (estado === "desconhecida" || estado === "verificando") {
    return (
      <div className="grid h-screen place-items-center text-[13px] text-muted">
        Verificando sessão…
      </div>
    );
  }

  // Já autenticado (voltou para /login pelo histórico): a guarda cuida do resto —
  // inclusive de desviar para a troca obrigatória quando a senha está expirada.
  if (estado === "autenticada" && sessao !== null) {
    return <Navigate to={sessao.senha_expirada ? "/trocar-senha" : destino} replace />;
  }

  async function submeter(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      const nova = await entrar(email.trim(), senha);
      queryClient.clear();
      setSenha("");
      navegar(nova.senha_expirada ? "/trocar-senha" : destino, { replace: true });
    } catch (e) {
      setErro(e);
    } finally {
      setEnviando(false);
    }
  }

  // 401 vira uma frase só: o backend responde `CredencialInvalida` idêntico para
  // inexistente / senha errada / conta inativa / bloqueada (G01), e a UI não desfaz
  // isso. 403 NÃO entra aqui de propósito — lá é divergência de X-Tenant, um erro de
  // configuração que precisa aparecer inteiro em vez de virar "senha inválida".
  const credencialInvalida = erro instanceof ApiError && erro.status === 401;
  // 429 NÃO vem da aplicação e não pode passar a vir: o bloqueio por tentativas do G01
  // responde 401 igual a todo o resto, justamente para não confirmar que a conta existe
  // ("bloqueada" é resposta só para quem acertou o e-mail). Esta faixa cobre um 429 de
  // proxy/gateway na frente da API, que é sobre o IP e não sobre a conta. Quem for
  // implementar rate limit NA API: mantenha 401 por credencial: um 429 por usuário
  // reabriria o oráculo de enumeração que a mensagem única fecha.
  const excessoDeTentativas = erro instanceof ApiError && erro.status === 429;

  return (
    <div className="grid min-h-screen place-items-center bg-page px-4">
      <div className="w-full max-w-[380px]">
        <div className="mb-4 flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-[3px] bg-claro" />
          <span className="text-[17px] font-extrabold tracking-[-.01em] text-ink2">Jornada</span>
          <span className="text-[12px] text-muted">Digital Twin do Journey Builder</span>
        </div>

        <form onSubmit={submeter} className="mcard !px-5 !py-5 shadow-card">
          <h1 className="text-[15px] font-bold text-ink2">Entrar</h1>
          <p className="mb-3 text-[12px] text-muted">
            Acesso com usuário e senha da plataforma. Não há autoatendimento de senha —
            peça a um administrador.
          </p>

          {credencialInvalida && (
            <div
              role="alert"
              className="mb-3 rounded-lg border border-crit/40 bg-crit-soft px-3 py-2 text-[12.5px] text-crit"
            >
              E-mail ou senha inválidos.
            </div>
          )}
          {excessoDeTentativas && (
            <div
              role="alert"
              className="mb-3 rounded-lg border border-warn-line bg-warn-bg px-3 py-2 text-[12.5px] text-warn"
            >
              Muitas tentativas seguidas. Aguarde alguns instantes e tente de novo.
            </div>
          )}
          {/* Qualquer outra falha (rede, 500, 400 de contrato) aparece inteira — erro
              engolido em silêncio já foi achado do UAT #5. */}
          {erro != null && !credencialInvalida && !excessoDeTentativas && (
            <BannerErro erro={erro} contexto="Login" />
          )}

          <label htmlFor="login-email" className="block text-[11px] font-bold text-slatex">
            E-mail ou login
          </label>
          {/* NÃO é `type="email"`. O campo é o LOGIN, não um endereço de envio: o
              backend normaliza com `normalizar_email` (strip + minúsculas) e aceita
              identificador SEM `@` de propósito — o root do projeto é `sergio.gaiotto`.
              Com `type="email"` + `required` o navegador barra a submissão na validação
              de restrição ("missing an '@'") ANTES de qualquer fetch: o POST /auth/login
              nunca sai, a tela não mostra erro nenhum, e a única conta de bootstrap do
              sistema fica trancada para fora da própria aplicação (observado em
              auditoria: clique em Entrar → zero requisições). `inputMode="email"` mantém
              o teclado certo no celular; `autoCapitalize`/`autoCorrect` off porque o
              teclado móvel capitaliza a primeira letra de um `type="text"`. */}
          <input
            id="login-email"
            type="text"
            inputMode="email"
            name="email"
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            maxLength={320}
            autoFocus
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={enviando}
            className="mb-3 mt-1 w-full rounded-md border border-line px-3 py-2 text-[13px] outline-none focus:border-blue disabled:bg-linesoft"
          />

          <label htmlFor="login-senha" className="block text-[11px] font-bold text-slatex">
            Senha
          </label>
          <input
            id="login-senha"
            type="password"
            name="senha"
            autoComplete="current-password"
            // Teto do contrato (`LoginEntrada.senha`, max_length=128). Sem ele, a senha
            // de 200 caracteres de um gerenciador vira um 422 de validação de payload
            // cuja mensagem ("Erro de validação do payload/parâmetros") não diz à pessoa
            // o que fazer — e ela conclui que a senha está errada.
            maxLength={128}
            required
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            disabled={enviando}
            className="mb-4 mt-1 w-full rounded-md border border-line px-3 py-2 text-[13px] outline-none focus:border-blue disabled:bg-linesoft"
          />

          <button type="submit" className="mbtn w-full justify-center !py-2" disabled={enviando}>
            {enviando ? "Entrando…" : "Entrar"}
          </button>
        </form>

        <div className="mt-3 text-center text-[11px] text-ghost">
          Sessão por cookie httpOnly, revogável no servidor · acessos registrados na trilha
        </div>
      </div>
    </div>
  );
}
