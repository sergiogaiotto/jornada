/**
 * T2 · Sala de Ideação — briefing assistido (mock T2): conversa livre à esquerda com o
 * Consultor de Campanhas (POST /pedidos + /pedidos/{id}/mensagem), briefing da OS de forma dinâmica
 *  à direita (inferido em âmbar → confirmado em verde via PATCH), medidor de
 * completude do pedido e prévia/diff Aplicar/Rejeitar (contrato de UX da IA).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { Copiloto } from "../components/ai/Copiloto";
import { BadgeViaAi } from "../components/ai/BadgeViaAi";
import { PreviaDiff, type ItemDiff } from "../components/ai/PreviaDiff";
import { BannerErro, BarraProgresso, EstadoVazio, TituloTela } from "../components/ui/basics";
import { patch, post } from "../lib/api";
import { useBriefing, useOs, usePainelContextual } from "../lib/hooks";
import {
  campoBriefing,
  valorLegivel,
  type BriefingOut,
  type MensagemOut,
  type PedidoOut,
} from "../lib/types";

interface Fala {
  autor: "voce" | "consultor";
  texto: string;
}

export function Ideacao() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: os } = useOs(id);
  const { data: briefing, error: erroBriefing } = useBriefing(id);

  const [falas, setFalas] = useState<Fala[]>([]);
  const [texto, setTexto] = useState("");
  const [completude, setCompletude] = useState<number | null>(null);
  const [faltantes, setFaltantes] = useState<string[]>([]);
  const [previa, setPrevia] = useState<ItemDiff[] | null>(null);
  const pedidoRef = useRef<PedidoOut | null>(null);

  const campos = useMemo(() => Object.entries(briefing?.briefing ?? {}), [briefing]);
  const confirmados = campos.filter(([, entrada]) => !campoBriefing(entrada).inferido).length;

  const enviar = useMutation({
    mutationFn: async (mensagem: string): Promise<MensagemOut> => {
      if (!pedidoRef.current) {
        pedidoRef.current = await post<PedidoOut>("/pedidos", {
          solicitante: { nome: "Dev Analista", area: "negocio", os_ref: os?.codigo ?? null },
          conteudo: {},
        });
      }
      return post<MensagemOut>(`/pedidos/${pedidoRef.current.id}/mensagem`, { mensagem });
    },
    onSuccess: (saida) => {
      setFalas((f) => [...f, { autor: "consultor", texto: saida.resposta }]);
      setCompletude(saida.completude);
      setFaltantes(saida.faltantes);
      // Contrato de UX da IA: inferências viram PRÉVIA/diff — nunca aplicadas direto.
      const inferidos: ItemDiff[] = Object.entries(saida.conteudo)
        .map(([campo, entrada]) => ({ campo, e: campoBriefing(entrada) }))
        .filter(({ e }) => e.inferido)
        .map(({ campo, e }) => {
          const atual = briefing?.briefing?.[campo];
          return {
            rotulo: campo,
            antes: atual !== undefined ? valorLegivel(campoBriefing(atual).valor) : undefined,
            depois: valorLegivel(e.valor),
          };
        });
      if (inferidos.length > 0) setPrevia(inferidos);
    },
  });

  const confirmarCampo = useMutation({
    mutationFn: ({ campo, valor }: { campo: string; valor?: unknown }) =>
      patch<BriefingOut>(
        `/os/${id}/briefing/${campo}`,
        valor === undefined ? {} : { valor },
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["os", id, "briefing"] });
    },
  });

  const onEnviar = () => {
    const mensagem = texto.trim();
    if (!mensagem || enviar.isPending) return;
    setFalas((f) => [...f, { autor: "voce", texto: mensagem }]);
    setTexto("");
    enviar.mutate(mensagem);
  };

  usePainelContextual(
    <>
      <div className="ctx-title">Memória institucional</div>
      <div className="mfield">
        <span>
          <span className="block text-[12px] font-bold">Precedentes (RAG)</span>
          <span className="block text-[11.5px] text-slatex">
            O consultor cita campanhas com resultado real ao inferir campos.
          </span>
        </span>
      </div>
      <div className="ctx-title">Medidor de completude</div>
      <div className="mfield block">
        <span className="flex w-full items-center justify-between text-[12px] font-bold">
          Pedido{" "}
          <span className="tabular-nums">
            {completude !== null ? `${completude.toFixed(0)}%` : "—"}
          </span>
        </span>
        <span className="block w-full">
          <BarraProgresso pct={completude ?? 0} tom={completude === 100 ? "good" : "blue"} />
        </span>
        {faltantes.length > 0 && (
          <span className="block text-[11.5px] text-warn">
            falta: {faltantes.join(" · ")}
          </span>
        )}
      </div>
      <div className="ctx-title">Estimativa</div>
      <div className="mfield">
        <span>
          <span className="block text-[12px] font-bold">T-shirt sugerido</span>
          <span className="block text-[11.5px] text-slatex">
            {os?.tshirt ?? "—"} · SLA projetado por t-shirt
          </span>
        </span>
        <BadgeViaAi rastro={{ agente: "consultor", skill: "consultor" }} />
      </div>
      <Copiloto titulo="Consultor de Campanhas">
        Converse à esquerda — o briefing se estrutura sozinho. Campos inferidos ficam em
        âmbar até um humano confirmar (QA da Fase 1).
      </Copiloto>
    </>,
    [completude, faltantes, os],
  );

  return (
    <div>
      <TituloTela
        titulo="Sala de Ideação"
        subtitulo={
          <>
            Converse — o briefing se estrutura sozinho. <b>{confirmados}</b> de{" "}
            <b>{campos.length}</b> campos confirmados.
          </>
        }
      />
      {erroBriefing != null && <BannerErro erro={erroBriefing} contexto="Briefing" />}
      {enviar.error != null && <BannerErro erro={enviar.error} contexto="Consultor" />}
      {confirmarCampo.error != null && (
        <BannerErro erro={confirmarCampo.error} contexto="Confirmação de campo" />
      )}

      <div className="grid gap-3 lg:grid-cols-[1.1fr_1fr]">
        {/* Conversa */}
        <div className="mcard flex min-h-[420px] flex-col">
          <div className="mb-2 text-[10px] font-bold uppercase tracking-[.06em] text-faint">
            Conversa
          </div>
          <div className="flex-1 space-y-2 overflow-y-auto pr-1">
            {falas.length === 0 && (
              <EstadoVazio>
                Descreva a ideia da campanha — ex.: “clientes pós-pago estourando a
                franquia todo mês; quero ofertar upgrade de plano”.
              </EstadoVazio>
            )}
            {falas.map((fala, i) =>
              fala.autor === "voce" ? (
                <div key={i} className="rounded-lg bg-[#F2F5F9] p-3 text-[13px] text-steel">
                  <b>Você:</b> {fala.texto}
                </div>
              ) : (
                <Copiloto key={i} titulo="Copiloto · Consultor">
                  {fala.texto}
                </Copiloto>
              ),
            )}
            {enviar.isPending && (
              <div className="text-[12px] text-muted">Consultor pensando…</div>
            )}
            {previa && (
              <PreviaDiff
                titulo="campos inferidos pelo consultor"
                itens={previa}
                premissas={faltantes.map((f) => `falta ${f}`)}
                rastro={{ agente: "consultor", skill: "consultor@dev" }}
                rotuloAplicar="Aplicar ao briefing"
                onAplicar={async () => {
                  const existentes = new Set(Object.keys(briefing?.briefing ?? {}));
                  for (const item of previa) {
                    if (existentes.has(item.rotulo)) {
                      await confirmarCampo.mutateAsync({
                        campo: item.rotulo,
                        valor: item.depois,
                      });
                    }
                  }
                  setPrevia(null);
                }}
                onRejeitar={() => setPrevia(null)}
              />
            )}
          </div>
          <div className="mt-3 flex gap-2">
            <input
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onEnviar()}
              placeholder="Digite ou cole o e-mail do negócio…"
              className="min-w-0 flex-1 rounded-md border border-line px-3 py-2 text-[13px] outline-none focus:border-blue"
            />
            <button
              type="button"
              className="mbtn"
              onClick={onEnviar}
              disabled={enviar.isPending || texto.trim() === ""}
            >
              Enviar
            </button>
          </div>
        </div>

        {/* Briefing dinâmico */}
        <div className="mcard">
          <div className="mb-2 text-[10px] font-bold uppercase tracking-[.06em] text-faint">
            Briefing estruturado · dinâmico
          </div>
          {campos.length === 0 && (
            <EstadoVazio>Briefing vazio — os campos aparecem conforme a conversa.</EstadoVazio>
          )}
          {campos.map(([campo, entrada]) => {
            const e = campoBriefing(entrada);
            return (
              <div key={campo} className="mfield">
                <span className="min-w-0">
                  <span className="block text-[12.5px] font-bold">{campo}</span>
                  <span className="block break-words text-[11.5px] leading-snug text-slatex">
                    {valorLegivel(e.valor)}
                  </span>
                </span>
                {e.inferido ? (
                  <span className="flex flex-none items-center gap-1.5">
                    <span className="mchip-w">inferido</span>
                    <button
                      type="button"
                      className="mbtn-gh !px-2 !py-0.5 !text-[11px]"
                      title="Confirmação humana: inferido → confirmado"
                      onClick={() => confirmarCampo.mutate({ campo })}
                      disabled={confirmarCampo.isPending}
                    >
                      Confirmar
                    </button>
                  </span>
                ) : (
                  <span className="mchip-g flex-none">confirmado</span>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
