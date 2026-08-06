/** Paleta ⌘K (SDD §12: "teclas ⌘K busca") — navega para OSs e telas; e cria
 * a "+ Nova Campanha" (pedido rascunho → Sala de Ideação em modo pedido, §8-M3). */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { post, solicitanteAtual } from "../../lib/api";
import { useOsLista } from "../../lib/hooks";
import type { PedidoOut } from "../../lib/types";
import { useUi } from "../../stores/ui";

interface Alvo {
  rotulo: string;
  /** rota a navegar — ausente quando o alvo é uma ação */
  href?: string;
  /** ação especial (ex.: nova campanha) executada no lugar da navegação */
  acao?: () => void;
}

export function CmdK() {
  const aberto = useUi((s) => s.cmdkAberto);
  const setAberto = useUi((s) => s.setCmdkAberto);
  const [busca, setBusca] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: oss } = useOsLista();

  const novaCampanha = () => {
    void post<PedidoOut>("/pedidos", { solicitante: solicitanteAtual(), conteudo: {} }).then(
      (pedido) => {
        void queryClient.invalidateQueries({ queryKey: ["pedidos"], exact: true });
        navigate(`/pedidos/${pedido.id}`);
      },
    );
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setAberto(true);
      }
      if (e.key === "Escape") setAberto(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [setAberto]);

  const alvos = useMemo<Alvo[]>(() => {
    const fixos: Alvo[] = [
      { rotulo: "+ Nova Campanha — criar pedido e abrir a Sala de Ideação", acao: novaCampanha },
      { rotulo: "Cockpit — portfólio", href: "/" },
      { rotulo: "Ateliê de Agentes", href: "/atelie" },
      { rotulo: "IA Responsável — o que a IA pode ver, guardar e decidir", href: "/ia-responsavel" },
    ];
    const deOs = (oss ?? []).flatMap((os) => [
      { rotulo: `${os.codigo} · ${os.nome} — Briefing`, href: `/os/${os.id}/briefing` },
      { rotulo: `${os.codigo} · ${os.nome} — Esteira`, href: `/os/${os.id}/workflow` },
      { rotulo: `${os.codigo} · ${os.nome} — War Room`, href: `/os/${os.id}/warroom` },
    ]);
    return [...fixos, ...deOs];
  }, [oss]);

  const filtrados = useMemo(() => {
    const q = busca.trim().toLowerCase();
    if (!q) return alvos.slice(0, 12);
    return alvos.filter((a) => a.rotulo.toLowerCase().includes(q)).slice(0, 12);
  }, [alvos, busca]);

  if (!aberto) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/30 pt-24"
      onClick={() => setAberto(false)}
    >
      <div
        className="w-[520px] max-w-[92vw] overflow-hidden rounded-xl border border-line bg-white shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          autoFocus
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && filtrados[0]) {
              const alvo = filtrados[0];
              if (alvo.href) navigate(alvo.href);
              else alvo.acao?.();
              setAberto(false);
              setBusca("");
            }
          }}
          placeholder="Buscar OS ou tela… (Enter abre o primeiro resultado)"
          className="w-full border-b border-line px-4 py-3 text-[14px] outline-none placeholder:text-ghost"
        />
        <ul className="max-h-72 overflow-y-auto py-1">
          {filtrados.map((a) => (
            <li key={(a.href ?? "acao") + a.rotulo}>
              <button
                type="button"
                className="block w-full px-4 py-2 text-left text-[13px] text-steel hover:bg-blue-soft"
                onClick={() => {
                  if (a.href) navigate(a.href);
                  else a.acao?.();
                  setAberto(false);
                  setBusca("");
                }}
              >
                {a.rotulo}
              </button>
            </li>
          ))}
          {filtrados.length === 0 && (
            <li className="px-4 py-3 text-[13px] text-muted">Nada encontrado.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
