/**
 * Chat "IA, me ajude com esta página" (padrão visual do print 4 — Maestro):
 * header gradiente "IA, ME AJUDE! · Página: {titulo}", empty-state com 4 chips de
 * sugestão, bolhas usuário/IA, input+Enviar e rodapé "histórico desta sessão (não
 * persistido)". Backend: POST /ajuda/perguntar (§8-M-Guia) — o CONTEXTO enviado é o
 * conteúdo do guia da página (fonte única em conteudo.ts, ≤ 8k chars); hub fora ⇒
 * 503 degraded (§10.6) vira bolha amigável apontando o guia estático.
 */
import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { ApiError, post } from "../lib/api";
import {
  type ChaveGuia,
  CONTEUDO_GUIA,
  type ConteudoPagina,
  chaveDaRota,
} from "./conteudo";
import { type MensagemChat, useGuia } from "./store";

const SUGESTOES = [
  "Como uso esta tela no fluxo da campanha?",
  "Quais erros comuns aqui?",
  "Mostre um passo a passo nesta tela.",
  "O que preciso ter pronto antes desta etapa?",
];

/** Contrato §8-M-Guia (resposta). */
interface RespostaAjuda {
  resposta: string;
  pagina: string;
  via_ai: boolean;
  invocacao_id: string;
}

const LIMITE_CONTEXTO = 8000; // contrato §8-M-Guia: o back valida ≤ 8k chars

/** Serializa o conteúdo do guia da página como CONTEXTO do agente (fonte única). */
function contextoDaPagina(pagina: ConteudoPagina): string {
  const linhas = [
    `Página: ${pagina.titulo} — ${pagina.descricao}`,
    `O que é: ${pagina.oQueE.join(" ")}`,
    `Fundamentos: ${pagina.fundamentos.map((f) => `${f.termo}: ${f.definicao}`).join(" · ")}`,
    `Campos da tela: ${pagina.campos.map((c) => `${c.campo}: ${c.significado}`).join(" · ")}`,
    `Casos de uso: ${pagina.casosDeUso.join(" · ")}`,
    `Exemplo prático (OS-2026-0457): ${pagina.exemplo.map((p, i) => `${i + 1}. ${p}`).join(" ")}`,
    `Pegadinhas: ${pagina.pegadinhas.join(" · ")}`,
  ];
  return linhas.join("\n").slice(0, LIMITE_CONTEXTO);
}

export function ChatAjuda() {
  const chatAberto = useGuia((s) => s.chatAberto);
  if (!chatAberto) return null;
  return <ChatAberto />;
}

function ChatAberto() {
  const fecharChat = useGuia((s) => s.fecharChat);
  const paginaAjuda = useGuia((s) => s.paginaAjuda);
  const historicoChat = useGuia((s) => s.historicoChat);
  const pushMensagemChat = useGuia((s) => s.pushMensagemChat);
  const { pathname } = useLocation();

  const chave: ChaveGuia = paginaAjuda ?? chaveDaRota(pathname);
  const pagina = CONTEUDO_GUIA[chave];
  const mensagens = historicoChat[chave] ?? [];

  const [texto, setTexto] = useState("");
  const fimRef = useRef<HTMLDivElement>(null);

  // Esc fecha o chat; novas mensagens rolam para o fim
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") fecharChat();
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [fecharChat]);
  useEffect(() => {
    fimRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [mensagens.length]);

  const perguntar = useMutation({
    mutationFn: (pergunta: string) =>
      post<RespostaAjuda>("/ajuda/perguntar", {
        pagina: chave,
        pergunta,
        contexto: contextoDaPagina(pagina),
        // só os turnos reais (bolha degraded não é conversa) — contrato: ≤ 20
        historico: mensagens
          .filter((m) => !m.degradado)
          .slice(-20)
          .map((m) => ({ papel: m.papel, texto: m.texto })),
      }),
    onSuccess: (r) => pushMensagemChat(chave, { papel: "ia", texto: r.resposta }),
    onError: (erro) => {
      const degradado = erro instanceof ApiError && erro.degradado;
      pushMensagemChat(chave, {
        papel: "ia",
        degradado: true,
        texto: degradado
          ? "A IA está temporariamente indisponível (modo degradado). Enquanto isso, " +
            "as abas do guia desta página — O que é, Campos da tela, Exemplo prático, " +
            "Pegadinhas — cobrem o conteúdo completo. Tente de novo em instantes."
          : "Não consegui responder agora. Verifique a conexão e tente de novo — ou " +
            "consulte as abas do guia desta página.",
      });
    },
  });

  const enviar = (pergunta: string) => {
    const limpo = pergunta.trim();
    if (!limpo || perguntar.isPending) return;
    pushMensagemChat(chave, { papel: "usuario", texto: limpo });
    perguntar.mutate(limpo);
    setTexto("");
  };

  return (
    <div className="fixed inset-0 z-[80]">
      {/* backdrop — clique fecha */}
      <button
        type="button"
        aria-label="Fechar chat de ajuda"
        onClick={fecharChat}
        className="absolute inset-0 h-full w-full cursor-default bg-ink/30"
      />

      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`IA, me ajude — ${pagina.titulo}`}
        className="absolute right-0 top-0 flex h-full w-full max-w-[430px] flex-col bg-white shadow-card"
      >
        {/* header — padrão do print 4 */}
        <div className="flex items-start justify-between gap-3 bg-gradient-to-r from-claro-dark to-blue/80 px-5 pb-3.5 pt-4 text-white">
          <div className="min-w-0">
            <div className="text-[10px] font-bold uppercase tracking-[.14em] text-white/80">
              ✨ IA, me ajude!
            </div>
            <h2 className="mt-0.5 truncate text-[16px] font-semibold leading-tight">
              Página: {pagina.titulo}
            </h2>
          </div>
          <button
            type="button"
            onClick={fecharChat}
            aria-label="Fechar"
            className="grid h-7 w-7 flex-none place-items-center rounded-md text-[16px] text-white/80 hover:bg-white/15 hover:text-white"
          >
            ×
          </button>
        </div>

        {/* conversa */}
        <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-4 py-4">
          {mensagens.length === 0 && !perguntar.isPending && (
            <div className="rounded-lg border border-dashed border-line bg-surface2 px-4 py-5 text-center">
              <p className="text-[13px] font-semibold text-ink">
                Pergunte qualquer coisa sobre {pagina.titulo}.
              </p>
              <p className="mt-1 text-[12px] text-muted">Sugestões abaixo ↓</p>
            </div>
          )}

          {mensagens.map((m, i) => (
            <Bolha key={i} mensagem={m} />
          ))}

          {perguntar.isPending && (
            <div className="max-w-[88%] rounded-xl rounded-bl-sm border border-line bg-surface2 px-3 py-2 text-[12.5px] text-muted">
              <b className="text-claro-dark">IA:</b> escrevendo…
            </div>
          )}
          <div ref={fimRef} />
        </div>

        {/* sugestões */}
        <div className="border-t border-linesoft px-4 pb-2 pt-2.5">
          <div className="flex flex-wrap gap-1.5">
            {SUGESTOES.map((s) => (
              <button
                key={s}
                type="button"
                disabled={perguntar.isPending}
                onClick={() => enviar(s)}
                className="rounded-full border border-line bg-surface2 px-2.5 py-1 text-[11px] font-semibold text-steel transition-colors hover:border-claro hover:bg-claro-soft hover:text-claro-dark disabled:opacity-50"
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        {/* input + rodapé */}
        <div className="border-t border-line px-4 pb-3 pt-2.5">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              enviar(texto);
            }}
          >
            <input
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              placeholder={`Pergunte sobre ${pagina.titulo}…`}
              className="min-w-0 flex-1 rounded-md border border-line px-3 py-2 text-[13px] outline-none focus:border-claro"
            />
            <button
              type="submit"
              disabled={perguntar.isPending || !texto.trim()}
              className="rounded-md bg-claro px-3.5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {perguntar.isPending ? "Enviando…" : "Enviar"}
            </button>
          </form>
          <p className="mt-1.5 text-center text-[10.5px] text-muted">
            histórico desta sessão (não persistido) · respostas via_ai (agente ajuda, 20b)
          </p>
        </div>
      </aside>
    </div>
  );
}

function Bolha({ mensagem }: { mensagem: MensagemChat }) {
  if (mensagem.papel === "usuario") {
    return (
      <div className="ml-auto max-w-[88%] rounded-xl rounded-br-sm bg-blue-soft px-3 py-2 text-[12.5px] leading-relaxed text-ink">
        {mensagem.texto}
      </div>
    );
  }
  return (
    <div
      className={`max-w-[88%] rounded-xl rounded-bl-sm border px-3 py-2 text-[12.5px] leading-relaxed ${
        mensagem.degradado
          ? "border-warn-line bg-warn-bg text-warn"
          : "border-line bg-surface2 text-steel"
      }`}
    >
      <b className={mensagem.degradado ? "" : "text-claro-dark"}>IA:</b> {mensagem.texto}
    </div>
  );
}
