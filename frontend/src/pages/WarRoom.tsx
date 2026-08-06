/**
 * T4 · War Room de Decisão — o GO formal (mock T4): threads ANCORADAS em campos do
 * briefing (POST /os/{id}/threads), quadro de pendências (GET/POST /os/{id}/pendencias ·
 * resolver) e o painel do GO (POST /os/{id}/go) — 409 RFC-7807 lista pendências e
 * campos não decididos; sucesso congela SLAs+versões em `os.frozen` e gera o .docx.
 *
 * B01 (UAT #2): o quadro de pendências hidrata de `GET /os/{id}/pendencias` — o que
 * bloqueia o GO não pode depender da sessão do navegador. As threads seguem da sessão
 * (não há leitura de `os_thread` no contrato) e o texto da tela diz isso sem disfarce.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { ApiError, post } from "../lib/api";
import { useBriefing, useOs, usePainelContextual, usePendencias } from "../lib/hooks";
import type { GoOut, PendenciaOut, ThreadOut } from "../lib/types";

interface BloqueioGo {
  detalhe: string;
  pendencias: { numero: number; titulo: string; severidade: string | null }[];
  camposNaoDecididos: string[];
}

export function WarRoom() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: os } = useOs(id);
  const { data: briefing } = useBriefing(id);
  // B01: pendências vêm do servidor (sobrevivem a reload/restart), não da sessão
  const { data: pendenciasDaOs, error: erroPendencias } = usePendencias(id);
  const pendencias = useMemo(() => pendenciasDaOs ?? [], [pendenciasDaOs]);
  const abertas = useMemo(
    () => pendencias.filter((p) => p.status === "aberta"),
    [pendencias],
  );

  const [threads, setThreads] = useState<ThreadOut[]>([]);
  const [bloqueio, setBloqueio] = useState<BloqueioGo | null>(null);
  const [goFeito, setGoFeito] = useState<GoOut | null>(null);

  const [campoThread, setCampoThread] = useState("");
  const [msgThread, setMsgThread] = useState("");
  const [tituloPendencia, setTituloPendencia] = useState("");

  const campos = useMemo(() => Object.keys(briefing?.briefing ?? {}), [briefing]);

  const criarThread = useMutation({
    mutationFn: () =>
      post<ThreadOut>(`/os/${id}/threads`, {
        campo: campoThread || campos[0],
        mensagem: msgThread,
      }),
    onSuccess: (t) => {
      setThreads((ts) => [t, ...ts]);
      setMsgThread("");
    },
  });

  /** Re-hidrata as leituras da OS (pendências e saúde derivada) após cada mutação. */
  const recarregar = () => void queryClient.invalidateQueries({ queryKey: ["os", id] });

  const abrirPendencia = useMutation({
    mutationFn: () =>
      post<PendenciaOut>(`/os/${id}/pendencias`, {
        titulo: tituloPendencia,
        tipo: "issue",
        severidade: "media",
        bloqueante: true,
      }),
    onSuccess: () => {
      setTituloPendencia("");
      recarregar();
    },
  });

  const resolverPendencia = useMutation({
    mutationFn: (pendenciaId: string) =>
      post<PendenciaOut>(`/pendencias/${pendenciaId}/resolver`),
    onSuccess: recarregar,
  });

  const executarGo = useMutation({
    mutationFn: () => post<GoOut>(`/os/${id}/go`),
    onSuccess: (saida) => {
      setGoFeito(saida);
      setBloqueio(null);
      void queryClient.invalidateQueries({ queryKey: ["os", id] });
    },
    onError: (erro) => {
      if (erro instanceof ApiError && erro.status === 409) {
        const p = erro.problem;
        setBloqueio({
          detalhe: p.detail ?? "GO bloqueado",
          pendencias: Array.isArray(p["pendencias"])
            ? (p["pendencias"] as BloqueioGo["pendencias"])
            : [],
          camposNaoDecididos: Array.isArray(p["campos_nao_decididos"])
            ? (p["campos_nao_decididos"] as string[])
            : [],
        });
      }
    },
  });

  usePainelContextual(
    <>
      <div className="ctx-title">Copiloto — ata dinâmica</div>
      <Copiloto titulo="Resumo da discussão">
        <b>Threads nesta sessão:</b> {threads.length} · <b>Pendências da OS:</b>{" "}
        {abertas.length} aberta(s) de {pendencias.length}.
        {bloqueio && (
          <>
            {" "}
            O GO está <b>bloqueado</b> — resolva as pendências listadas no painel central.
          </>
        )}
        {goFeito && (
          <>
            {" "}
            GO publicado: escopo, SLAs e versões <b>congelados</b>.
          </>
        )}
      </Copiloto>
      <div className="ctx-title">Congela no GO</div>
      <div className="mfield">
        <span className="text-[11.5px] text-slatex">
          {goFeito?.os.frozen
            ? JSON.stringify(goFeito.os.frozen)
            : os?.frozen
              ? JSON.stringify(os.frozen)
              : "Versões publicadas de agentes + política + tarifário + SLAs por t-shirt (os.frozen)."}
        </span>
      </div>
      {goFeito && (
        <>
          <div className="ctx-title">Documento do QA</div>
          <div className="mfield">
            <span>
              <span className="block text-[12px] font-bold">
                {goFeito.documento.nome_arquivo}
              </span>
              <span className="block break-all text-[11px] text-slatex">
                {(goFeito.documento.tamanho_bytes / 1024).toFixed(1)} KB · sha256{" "}
                {goFeito.documento.hash.slice(0, 12)}…
              </span>
            </span>
            <span className="mchip-g">gerado</span>
          </div>
        </>
      )}
    </>,
    [threads.length, pendencias, abertas, bloqueio, goFeito, os],
  );

  return (
    <div>
      <TituloTela
        titulo="War Room"
        subtitulo={
          <>
            {threads.length} thread(s) na sessão · {abertas.length} pendência(s) aberta(s)
            de {pendencias.length} · decisão de GO {goFeito ? "tomada" : "pendente"}
          </>
        }
      />
      {erroPendencias != null && <BannerErro erro={erroPendencias} contexto="Pendências" />}
      {criarThread.error != null && <BannerErro erro={criarThread.error} contexto="Thread" />}
      {abrirPendencia.error != null && (
        <BannerErro erro={abrirPendencia.error} contexto="Pendência" />
      )}
      {executarGo.error != null && !bloqueio && (
        <BannerErro erro={executarGo.error} contexto="GO" />
      )}

      <div className="grid gap-3 lg:grid-cols-[1.2fr_1fr]">
        {/* Threads ancoradas + pendências */}
        <div className="grid content-start gap-3">
          <div className="mcard">
            <div className="mb-2 text-[10px] font-bold uppercase tracking-[.06em] text-faint">
              Threads ancoradas
            </div>
            <div className="mb-2 flex gap-2">
              <select
                value={campoThread || campos[0] || ""}
                onChange={(e) => setCampoThread(e.target.value)}
                className="rounded-md border border-line px-2 py-1.5 text-[12px] outline-none focus:border-blue"
              >
                {campos.map((c) => (
                  <option key={c} value={c}>
                    no campo {c}
                  </option>
                ))}
              </select>
              <input
                value={msgThread}
                onChange={(e) => setMsgThread(e.target.value)}
                onKeyDown={(e) =>
                  e.key === "Enter" && msgThread.trim() && criarThread.mutate()
                }
                placeholder="Comentário ancorado no campo…"
                className="min-w-0 flex-1 rounded-md border border-line px-3 py-1.5 text-[12px] outline-none focus:border-blue"
              />
              <button
                type="button"
                className="mbtn !py-1.5"
                disabled={criarThread.isPending || !msgThread.trim() || campos.length === 0}
                onClick={() => criarThread.mutate()}
              >
                Abrir
              </button>
            </div>
            {threads.length === 0 && (
              <EstadoVazio>
                Threads são ancoradas em campos do briefing — âncora inválida → 404.
              </EstadoVazio>
            )}
            {threads.map((t) => (
              <div key={t.id} className="mfield">
                <span className="min-w-0">
                  <span className="block text-[12.5px] font-bold">
                    {t.titulo ?? t.mensagens[0]?.texto.slice(0, 60)}{" "}
                    <span className="mchip-b">no campo {t.campo}</span>
                  </span>
                  {t.mensagens.map((m, i) => (
                    <span key={i} className="block text-[11.5px] text-slatex">
                      <b>{m.autor}:</b> {m.texto}
                    </span>
                  ))}
                </span>
                <span className={t.status === "aberta" ? "mchip-w" : "mchip-g"}>
                  {t.status}
                </span>
              </div>
            ))}
          </div>

          <div className="mcard">
            <div className="mb-2 text-[10px] font-bold uppercase tracking-[.06em] text-faint">
              Pendências (bloqueiam o GO)
            </div>
            <div className="mb-2 flex gap-2">
              <input
                value={tituloPendencia}
                onChange={(e) => setTituloPendencia(e.target.value)}
                onKeyDown={(e) =>
                  e.key === "Enter" && tituloPendencia.trim() && abrirPendencia.mutate()
                }
                placeholder="Título da pendência bloqueante…"
                className="min-w-0 flex-1 rounded-md border border-line px-3 py-1.5 text-[12px] outline-none focus:border-blue"
              />
              <button
                type="button"
                className="mbtn-rd !py-1.5"
                disabled={abrirPendencia.isPending || !tituloPendencia.trim()}
                onClick={() => abrirPendencia.mutate()}
              >
                Abrir pendência
              </button>
            </div>
            {pendencias.length === 0 && (
              <EstadoVazio>
                Nenhuma pendência nesta OS — o portão do GO só barra por campo não decidido.
              </EstadoVazio>
            )}
            {pendencias.map((p) => (
              <div key={p.id} className="mfield">
                <span>
                  <span className="block text-[12.5px] font-bold">
                    #{p.numero} · {p.titulo}
                  </span>
                  <span className="block text-[11.5px] text-slatex">
                    {p.severidade ?? "—"} · {p.bloqueante ? "bloqueante" : "não bloqueante"}
                  </span>
                </span>
                {p.status === "aberta" ? (
                  <button
                    type="button"
                    className="mbtn-gh !px-2.5 !py-1 !text-[11px]"
                    disabled={resolverPendencia.isPending}
                    onClick={() => resolverPendencia.mutate(p.id)}
                  >
                    Resolver
                  </button>
                ) : (
                  <span className="mchip-g">{p.status}</span>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Painel do GO */}
        <div className="mcard content-start">
          <div className="mb-2 text-[10px] font-bold uppercase tracking-[.06em] text-faint">
            Painel do GO
          </div>
          <div className="mfield">
            <span>
              <span className="block text-[12.5px] font-bold">T-shirt size</span>
              <span className="block text-[11.5px] text-slatex">
                <b>{os?.tshirt ?? "—"}</b> — SLAs por fase congelados ao publicar
              </span>
            </span>
          </div>
          <div className="mfield">
            <span>
              <span className="block text-[12.5px] font-bold">SLA por fase (a congelar)</span>
              <span className="block text-[11.5px] text-slatex">
                Criada · Avaliada · Configurada — aprovação do cliente <b>fora do relógio</b>
              </span>
            </span>
          </div>
          <div className="mfield">
            <span>
              <span className="block text-[12.5px] font-bold">Congela também</span>
              <span className="block text-[11.5px] text-slatex">
                versões publicadas de agentes · política vigente (os.frozen — §8-M4-A2)
              </span>
            </span>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              className={goFeito ? "mbtn-gd" : "mbtn"}
              disabled={executarGo.isPending || Boolean(goFeito)}
              onClick={() => executarGo.mutate()}
            >
              {goFeito ? "GO publicado ✓" : "Publicar template (GO)"}
            </button>
            {os && <span className="mchip-n">fase atual: {goFeito?.os.fase ?? os.fase}</span>}
          </div>
          {bloqueio && (
            <div className="mt-3 rounded-lg border border-warn-line bg-warn-bg p-3 text-[12px]">
              <b className="text-warn">⚠ Bloqueado:</b> {bloqueio.detalhe}
              {bloqueio.pendencias.length > 0 && (
                <ul className="mt-1 list-inside list-disc text-slatex">
                  {bloqueio.pendencias.map((p) => (
                    <li key={p.numero}>
                      Pendência #{p.numero} · {p.titulo} ({p.severidade ?? "—"})
                    </li>
                  ))}
                </ul>
              )}
              {bloqueio.camposNaoDecididos.length > 0 && (
                <div className="mt-1 text-slatex">
                  Campos não decididos: {bloqueio.camposNaoDecididos.join(" · ")}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
