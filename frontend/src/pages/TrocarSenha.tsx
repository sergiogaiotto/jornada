/**
 * Tela de TROCA DE SENHA (emenda E04) — standalone, sem shell.
 *
 * Dois usos:
 *  · troca OBRIGATÓRIA no 1º acesso (`senha_expirada`): a senha provisória foi ditada
 *    por um admin, então ela é de uso único — enquanto não trocar, a guarda prende o
 *    usuário aqui e ele não vê PII de cliente;
 *  · troca voluntária a partir do menu do cabeçalho.
 *
 * A validação local é um ATALHO de usabilidade (erra rápido, sem round-trip); a
 * autoridade sobre a política é o servidor — o problem+json dele é exibido como veio.
 */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { BannerErro } from "../components/ui/basics";
import { ApiError } from "../lib/api";
import { useSessao } from "../lib/sessao";

/**
 * Espelho da política do servidor (`domain/identidade/senha.py: validar_politica`),
 * visível ANTES de digitar — regra que só aparece como erro depois do submit é
 * pegadinha. Note o que NÃO está aqui: exigência de maiúscula/símbolo. O backend
 * dispensa de propósito ("composição forçada empurra para `Senha@2026` e não compra
 * entropia"); repetir a exigência na tela seria mentir sobre o que será aceito.
 */
export const TAMANHO_MINIMO_SENHA = 12;
const TAMANHO_MAXIMO_SENHA = 128;

const REGRAS: string[] = [
  `De ${TAMANHO_MINIMO_SENHA} a ${TAMANHO_MAXIMO_SENHA} caracteres`,
  "Sem espaço no começo nem no fim",
  "Não pode ser igual ao seu e-mail ou ao identificador de login",
  "Não pode ser um único caractere repetido",
  // Exigência desta TELA, não do servidor: repetir a senha provisória deixaria de pé
  // uma credencial que o admin digitou e conhece — o oposto do motivo da troca.
  "Diferente da senha atual",
];

export function TrocarSenha() {
  const navegar = useNavigate();
  const sessao = useSessao((s) => s.sessao);
  const trocarSenha = useSessao((s) => s.trocarSenha);

  const [atual, setAtual] = useState("");
  const [nova, setNova] = useState("");
  const [confirmacao, setConfirmacao] = useState("");
  const [erro, setErro] = useState<unknown>(null);
  const [enviando, setEnviando] = useState(false);
  const [pronto, setPronto] = useState(false);

  const obrigatoria = sessao?.senha_expirada ?? false;

  // extra `erros` do problem+json 422 (SenhaFraca) — lista de violações da política
  const violacoes =
    erro instanceof ApiError && Array.isArray(erro.problem["erros"])
      ? (erro.problem["erros"] as string[])
      : [];

  const curta = nova.length > 0 && nova.length < TAMANHO_MINIMO_SENHA;
  const igualAtual = nova.length > 0 && nova === atual;
  const naoConfere = confirmacao.length > 0 && confirmacao !== nova;
  const podeEnviar =
    !enviando &&
    atual.length > 0 &&
    nova.length >= TAMANHO_MINIMO_SENHA &&
    nova !== atual &&
    confirmacao === nova;

  async function submeter(evento: FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    if (!podeEnviar) return;
    setErro(null);
    setEnviando(true);
    try {
      await trocarSenha(atual, nova);
      setAtual("");
      setNova("");
      setConfirmacao("");
      setPronto(true);
    } catch (e) {
      setErro(e);
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center bg-page px-4">
      <div className="w-full max-w-[420px]">
        <div className="mb-4 flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-[3px] bg-claro" />
          <span className="text-[17px] font-extrabold tracking-[-.01em] text-ink2">Jornada</span>
        </div>

        <form onSubmit={submeter} className="mcard !px-5 !py-5 shadow-card">
          <h1 className="text-[15px] font-bold text-ink2">Trocar senha</h1>
          <div className="mb-3 text-[12px] text-muted">
            {sessao?.email ?? "sua conta"}
          </div>

          {obrigatoria && !pronto && (
            <div className="mb-3 rounded-lg border border-warn-line bg-warn-bg px-3 py-2 text-[12.5px] text-ink">
              <b>Troca obrigatória:</b> sua senha foi definida por um administrador e vale
              apenas para este primeiro acesso. Defina uma senha sua para continuar.
            </div>
          )}

          {pronto && (
            <div
              role="status"
              className="mb-3 rounded-lg border border-good/40 bg-good-soft px-3 py-2 text-[12.5px] text-good"
            >
              Senha alterada. As suas outras sessões foram <b>encerradas</b> (se a senha
              antiga vazou, ela não abre mais nada) — esta aqui segue valendo, com
              identificador novo.
            </div>
          )}

          {erro != null && <BannerErro erro={erro} contexto="Troca de senha" />}
          {/* 422 `SenhaFraca` traz TODAS as violações de uma vez (extra `erros` do
              problem+json) — mostrar as quatro juntas evita o pingue-pongue de corrigir
              uma por submit. */}
          {violacoes.length > 0 && (
            <ul className="mb-3 list-inside list-disc rounded-lg border border-crit/40 bg-crit-soft px-3 py-2 text-[12px] text-crit">
              {violacoes.map((v) => (
                <li key={v}>{v}</li>
              ))}
            </ul>
          )}

          <div className="mb-3 rounded-md bg-surface2 px-3 py-2 text-[11.5px] text-slatex">
            <b className="text-[10px] uppercase tracking-[.08em] text-faint">Regras da senha</b>
            <ul className="mt-1 list-inside list-disc">
              {REGRAS.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>

          <label htmlFor="senha-atual" className="block text-[11px] font-bold text-slatex">
            Senha atual
          </label>
          <input
            id="senha-atual"
            type="password"
            autoComplete="current-password"
            // Teto do contrato (`TrocaSenha`, max_length=128 nos dois campos): passar
            // disso não vira o 422 `SenhaFraca` com a lista de violações, e sim o 422
            // genérico de validação de payload — a pessoa lê "Erro de validação do
            // payload/parâmetros" e não tem como adivinhar que o problema é o tamanho.
            maxLength={TAMANHO_MAXIMO_SENHA}
            autoFocus
            required
            value={atual}
            onChange={(e) => setAtual(e.target.value)}
            disabled={enviando}
            className="mb-3 mt-1 w-full rounded-md border border-line px-3 py-2 text-[13px] outline-none focus:border-blue disabled:bg-linesoft"
          />

          <label htmlFor="senha-nova" className="block text-[11px] font-bold text-slatex">
            Nova senha
          </label>
          <input
            id="senha-nova"
            type="password"
            autoComplete="new-password"
            maxLength={TAMANHO_MAXIMO_SENHA}
            required
            value={nova}
            onChange={(e) => setNova(e.target.value)}
            disabled={enviando}
            className={`mt-1 w-full rounded-md border px-3 py-2 text-[13px] outline-none focus:border-blue disabled:bg-linesoft ${
              curta || igualAtual ? "border-crit" : "border-line"
            }`}
          />
          <div className="mb-3 mt-1 min-h-[15px] text-[11px] text-crit">
            {curta && `Faltam ${TAMANHO_MINIMO_SENHA - nova.length} caractere(s).`}
            {igualAtual && "A nova senha precisa ser diferente da atual."}
          </div>

          <label htmlFor="senha-confirma" className="block text-[11px] font-bold text-slatex">
            Confirmar nova senha
          </label>
          <input
            id="senha-confirma"
            type="password"
            autoComplete="new-password"
            maxLength={TAMANHO_MAXIMO_SENHA}
            required
            value={confirmacao}
            onChange={(e) => setConfirmacao(e.target.value)}
            disabled={enviando}
            className={`mt-1 w-full rounded-md border px-3 py-2 text-[13px] outline-none focus:border-blue disabled:bg-linesoft ${
              naoConfere ? "border-crit" : "border-line"
            }`}
          />
          <div className="mb-4 mt-1 min-h-[15px] text-[11px] text-crit">
            {naoConfere && "As senhas não conferem."}
          </div>

          <div className="flex items-center gap-2">
            <button type="submit" className="mbtn !py-2" disabled={!podeEnviar}>
              {enviando ? "Salvando…" : "Salvar nova senha"}
            </button>
            {/* Sem saída enquanto a troca é obrigatória (a guarda também barra). */}
            {(!obrigatoria || pronto) && (
              <button
                type="button"
                className="mbtn-gh !py-2"
                onClick={() => navegar("/", { replace: true })}
              >
                {pronto ? "Ir para o Cockpit" : "Voltar"}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
