/**
 * Guarda de rota (emenda E04): nada da aplicação renderiza sem sessão autenticada.
 *
 * Três regras, nesta ordem:
 *  1. estado desconhecido → consulta `/auth/eu` uma vez e segura a tela (spinner);
 *  2. anônimo → `/login` com o destino preservado em `state.de` (o 401 pode chegar no
 *     meio da navegação: quem estava em /os/x/twin volta para /os/x/twin depois de
 *     entrar, não para a home);
 *  3. `senha_expirada` → prende em `/trocar-senha`. Senha provisória é credencial de
 *     uso único: enquanto não trocar, o usuário não vê dado de cliente (PII real).
 */
import { useEffect } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useSessao } from "../../lib/sessao";

export const ROTA_TROCA_SENHA = "/trocar-senha";

/**
 * Peneira do destino guardado em `state.de` — sempre um caminho INTERNO ou `/`.
 *
 * `de` nasce de `location.pathname + search`, e pathname NÃO é sinônimo de caminho
 * interno: a URL `http://app//evil.com/x` tem pathname `//evil.com/x`, que é uma URL
 * PROTOCOLO-RELATIVA. O react-router a resolve para `http://evil.com/x` e manda no
 * `history.replaceState` — quem barra é o navegador (SecurityError de origem cruzada),
 * não a aplicação. O saldo observado em auditoria era pior que um erro: o login dava
 * 200, o cookie era gravado, e o `<Navigate>` estourava a árvore inteira no
 * ErrorBoundary — um link `http://app//qualquer-coisa` derrubava a tela de quem
 * acabara de entrar. Defender-se por conta própria é barato; depender do navegador não.
 *
 * `/\` também é recusado porque navegadores normalizam `\` para `/` ao resolver a URL,
 * e `/\evil.com` vira `//evil.com` depois da normalização.
 */
export function caminhoInternoSeguro(de: unknown): string {
  if (typeof de !== "string") return "/";
  if (!de.startsWith("/") || de.startsWith("//") || de.startsWith("/\\")) return "/";
  try {
    // Prova final: resolvido contra a origem atual, tem que CONTINUAR na origem atual.
    // Também normaliza a forma e descarta o fragmento (que não volta no state).
    const url = new URL(de, window.location.origin);
    return url.origin === window.location.origin ? `${url.pathname}${url.search}` : "/";
  } catch {
    return "/";
  }
}

export function ExigirSessao() {
  const local = useLocation();
  const estado = useSessao((s) => s.estado);
  const sessao = useSessao((s) => s.sessao);
  const verificar = useSessao((s) => s.verificar);

  useEffect(() => {
    if (estado === "desconhecida") void verificar().catch(() => undefined);
  }, [estado, verificar]);

  // Tela de espera SÓ no primeiro reconhecimento (ainda não há sessão em mãos). Quando
  // já existe sessão e o app só está RECONFERINDO (ex.: depois de trocar a senha),
  // manter os filhos montados é obrigatório: trocar por um spinner desmontaria a tela
  // ativa e apagaria o estado dela — foi o que aconteceu com a mensagem de sucesso da
  // troca de senha, que sumia junto com o formulário.
  if (sessao === null && (estado === "desconhecida" || estado === "verificando")) {
    return (
      <div className="grid h-screen place-items-center text-[13px] text-muted">
        Verificando sessão…
      </div>
    );
  }

  if (estado === "anonima" || sessao === null) {
    // Peneirado JÁ NA ORIGEM: o destino que entra no state nunca é uma URL externa
    // disfarçada de caminho (ver `caminhoInternoSeguro`). O consumidor peneira de novo.
    const de = caminhoInternoSeguro(`${local.pathname}${local.search}`);
    return <Navigate to="/login" replace state={{ de }} />;
  }

  if (sessao.senha_expirada && local.pathname !== ROTA_TROCA_SENHA) {
    return <Navigate to={ROTA_TROCA_SENHA} replace />;
  }

  return <Outlet />;
}
