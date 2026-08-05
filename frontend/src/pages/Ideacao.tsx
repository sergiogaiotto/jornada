/**
 * T2 · Sala de Ideação — a MESMA sala em dois modos (SDD §8-M3):
 * - modo "os" (/os/:id/briefing): conversa com o Consultor + briefing dinâmico da OS
 *   com prévia/diff Aplicar/Rejeitar (contrato de UX da IA); medidor conectado.
 * - modo "pedido" (/pedidos/:id — nasce do "+ Nova Campanha"): conversa à esquerda;
 *   à direita os 5 campos obrigatórios com estado (vazio · inferido âmbar ·
 *   confirmado verde) e EDIÇÃO INLINE (clicar → editar → PATCH /pedidos/{id}/campos)
 *   — quem prefere formulário a conversa, preenche direto. Completude 100% →
 *   CTA "Converter em OS" (nome + t-shirt) → navega à OS nova.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Copiloto } from "../components/ai/Copiloto";
import { BadgeViaAi } from "../components/ai/BadgeViaAi";
import { PreviaDiff, type ItemDiff } from "../components/ai/PreviaDiff";
import { BannerErro, BarraProgresso, EstadoVazio, TituloTela } from "../components/ui/basics";
import { patch, post } from "../lib/api";
import { useBriefing, useOs, usePedido, usePainelContextual } from "../lib/hooks";
import {
  CAMPOS_PEDIDO,
  campoBriefing,
  valorLegivel,
  type BriefingOut,
  type MensagemOut,
  type OsOut,
  type PedidoOut,
  type Tshirt,
} from "../lib/types";

interface Fala {
  autor: "voce" | "consultor";
  texto: string;
}

/** Valor "presente" para fins de completude (espelho de completude.py §8-M3). */
function presente(valor: unknown): boolean {
  if (valor === null || valor === undefined) return false;
  if (typeof valor === "string") return valor.trim() !== "";
  if (Array.isArray(valor)) return valor.length > 0;
  return true;
}

export function Ideacao({ modo = "os" }: { modo?: "os" | "pedido" }) {
  const { id } = useParams<{ id: string }>();
  if (modo === "pedido") return <SalaPedido id={id ?? ""} />;
  return <SalaOs id={id ?? ""} />;
}

/* ================================================================== modo PEDIDO */

function SalaPedido({ id }: { id: string }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: pedido, error: erroPedido } = usePedido(id);

  const [falas, setFalas] = useState<Fala[]>([]);
  const [texto, setTexto] = useState("");
  const [editando, setEditando] = useState<string | null>(null);
  const [rascunho, setRascunho] = useState("");
  const [nomeOs, setNomeOs] = useState("");
  const [tshirt, setTshirt] = useState<Tshirt>("M");
  const refsCampos = useRef<Record<string, HTMLDivElement | null>>({});
  const refEdicao = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (editando) refEdicao.current?.focus();
  }, [editando]);

  // Convertido/arquivado não editam (§8-M3 CRUD: convertido edita no briefing da OS).
  const editavel = pedido?.estado === "rascunho" || pedido?.estado === "completo";

  const confirmados = CAMPOS_PEDIDO.filter(({ campo }) => {
    const entrada = pedido?.conteudo?.[campo];
    if (entrada === undefined) return false;
    const e = campoBriefing(entrada);
    return presente(e.valor) && !e.inferido;
  }).length;

  const enviar = useMutation({
    mutationFn: (mensagem: string) => post<MensagemOut>(`/pedidos/${id}/mensagem`, { mensagem }),
    onSuccess: (saida) => {
      setFalas((f) => [...f, { autor: "consultor", texto: saida.resposta }]);
      // Inferências já entram no pedido (inferido:true) — recarrega o detalhe.
      void queryClient.invalidateQueries({ queryKey: ["pedidos", id] });
      void queryClient.invalidateQueries({ queryKey: ["pedidos"], exact: true });
    },
  });

  const salvarCampo = useMutation({
    mutationFn: ({ campo, valor }: { campo: string; valor: unknown }) =>
      patch<PedidoOut>(`/pedidos/${id}/campos`, { [campo]: valor }),
    onSuccess: (novo) => {
      queryClient.setQueryData(["pedidos", id], novo);
      void queryClient.invalidateQueries({ queryKey: ["pedidos"], exact: true });
      setEditando(null);
    },
  });

  const converter = useMutation({
    mutationFn: () =>
      post<OsOut>(`/pedidos/${id}/converter`, {
        nome: nomeOs.trim() === "" ? null : nomeOs.trim(),
        tshirt,
      }),
    onSuccess: (os) => {
      void queryClient.invalidateQueries({ queryKey: ["os"], exact: true });
      void queryClient.invalidateQueries({ queryKey: ["pedidos"] });
      navigate(`/os/${os.id}/briefing`);
    },
  });

  const onEnviar = () => {
    const mensagem = texto.trim();
    if (!mensagem || enviar.isPending || !editavel) return;
    setFalas((f) => [...f, { autor: "voce", texto: mensagem }]);
    setTexto("");
    enviar.mutate(mensagem);
  };

  /** Chip de faltante / clique no campo → foca a edição inline daquele campo. */
  const focarCampo = (campo: string) => {
    if (!editavel) return;
    const e = campoBriefing(pedido?.conteudo?.[campo]);
    setRascunho(presente(e.valor) ? valorLegivel(e.valor) : "");
    setEditando(campo);
    refsCampos.current[campo]?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const salvarEdicao = (campo: string) => {
    const valor = rascunho.trim();
    if (valor === "" || salvarCampo.isPending) return;
    salvarCampo.mutate({ campo, valor });
  };

  const objetivo = campoBriefing(pedido?.conteudo?.["objetivo"]);
  const completa = pedido?.estado === "completo" && pedido.completude === 100;

  usePainelContextual(
    <>
      <div className="ctx-title">Medidor de completude</div>
      <div className="mfield block">
        <span className="flex w-full items-center justify-between text-[12px] font-bold">
          Pedido{" "}
          <span className="tabular-nums">
            {pedido ? `${pedido.completude.toFixed(0)}%` : "—"}
          </span>
        </span>
        <span className="block w-full">
          <BarraProgresso
            pct={pedido?.completude ?? 0}
            tom={pedido?.completude === 100 ? "good" : "blue"}
          />
        </span>
        {pedido && pedido.faltantes.length > 0 && (
          <span className="mt-1 flex w-full flex-wrap gap-1">
            {pedido.faltantes.map((campo) => (
              <button
                key={campo}
                type="button"
                className="mchip-w cursor-pointer hover:opacity-80"
                title={`Falta ${campo} — clique para preencher`}
                onClick={() => focarCampo(campo)}
              >
                falta {campo}
              </button>
            ))}
          </span>
        )}
        {pedido?.completude === 100 && (
          <span className="mt-1 block text-[11.5px] text-good">
            100% — pronto para converter em OS.
          </span>
        )}
      </div>
      <div className="ctx-title">Pedido</div>
      <div className="mfield">
        <span>
          <span className="block text-[12px] font-bold">
            {String(pedido?.solicitante?.["nome"] ?? "—")}
          </span>
          <span className="block text-[11.5px] text-slatex">
            solicitante · estado {pedido?.estado ?? "—"}
          </span>
        </span>
        <ChipEstadoPedido estado={pedido?.estado} />
      </div>
      <div className="ctx-title">Memória institucional</div>
      <div className="mfield">
        <span>
          <span className="block text-[12px] font-bold">Precedentes (RAG)</span>
          <span className="block text-[11.5px] text-slatex">
            O consultor cita campanhas com resultado real ao inferir campos.
          </span>
        </span>
        <BadgeViaAi rastro={{ agente: "consultor", skill: "consultor" }} />
      </div>
      <Copiloto titulo="Consultor de Campanhas">
        Converse à esquerda OU preencha os campos direto à direita — os dois caminhos
        valem. Inferido (âmbar) vira confirmado (verde) com um toque humano.
      </Copiloto>
    </>,
    [pedido, editavel],
  );

  return (
    <div>
      <TituloTela
        titulo="Sala de Ideação · Nova Campanha"
        subtitulo={
          <>
            Converse com o Consultor ou preencha os campos direto. <b>{confirmados}</b> de{" "}
            <b>{CAMPOS_PEDIDO.length}</b> campos confirmados.
          </>
        }
      />
      {erroPedido != null && <BannerErro erro={erroPedido} contexto="Pedido" />}
      {enviar.error != null && <BannerErro erro={enviar.error} contexto="Consultor" />}
      {salvarCampo.error != null && (
        <BannerErro erro={salvarCampo.error} contexto="Edição de campo" />
      )}
      {converter.error != null && <BannerErro erro={converter.error} contexto="Converter em OS" />}

      {pedido?.estado === "convertido" && (
        <div className="mb-3 flex items-center justify-between rounded-lg border border-line bg-blue-soft px-4 py-3 text-[13px] text-ink">
          <span>
            <b>Pedido convertido em OS</b> — a edição continua no briefing da OS; o pedido
            fica como rastro de governança (não se edita nem se arquiva).
          </span>
          {pedido.os_id && (
            <Link to={`/os/${pedido.os_id}/briefing`} className="mbtn flex-none">
              Abrir OS →
            </Link>
          )}
        </div>
      )}
      {pedido?.estado === "arquivado" && (
        <div className="mb-3 rounded-lg border border-line bg-linesoft px-4 py-3 text-[13px] text-ink">
          <b>Pedido arquivado (soft)</b> — segue legível, mas sem conversa, edição ou
          conversão. Ele saiu da fila do Cockpit.
        </div>
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
                franquia todo mês; quero ofertar upgrade de plano”. Ou preencha os campos
                à direita, se preferir formulário.
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
          </div>
          <div className="mt-3 flex gap-2">
            <input
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onEnviar()}
              placeholder={
                editavel
                  ? "Digite ou cole o e-mail do negócio…"
                  : "Pedido convertido/arquivado — conversa encerrada."
              }
              disabled={!editavel}
              className="min-w-0 flex-1 rounded-md border border-line px-3 py-2 text-[13px] outline-none focus:border-blue disabled:bg-linesoft"
            />
            <button
              type="button"
              className="mbtn"
              onClick={onEnviar}
              disabled={enviar.isPending || texto.trim() === "" || !editavel}
            >
              Enviar
            </button>
          </div>
        </div>

        {/* Os 5 campos — estado + edição inline */}
        <div className="mcard">
          <div className="mb-2 flex items-center justify-between text-[10px] font-bold uppercase tracking-[.06em] text-faint">
            <span>Briefing do pedido · 5 campos</span>
            <span className="tabular-nums normal-case">
              {pedido ? `${pedido.completude.toFixed(0)}%` : "—"}
            </span>
          </div>
          <BarraProgresso
            pct={pedido?.completude ?? 0}
            tom={pedido?.completude === 100 ? "good" : "blue"}
          />
          <div className="mt-2">
            {CAMPOS_PEDIDO.map(({ campo, rotulo, dica }) => {
              const entrada = pedido?.conteudo?.[campo];
              const e = campoBriefing(entrada);
              const temValor = entrada !== undefined && presente(e.valor);
              const emEdicao = editando === campo;
              return (
                <div
                  key={campo}
                  ref={(el) => {
                    refsCampos.current[campo] = el;
                  }}
                  className={`mfield ${temValor ? "" : "border-dashed"}`}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block text-[12.5px] font-bold">{rotulo}</span>
                    {emEdicao ? (
                      <span className="mt-1 flex items-center gap-2">
                        <input
                          ref={refEdicao}
                          value={rascunho}
                          onChange={(ev) => setRascunho(ev.target.value)}
                          onKeyDown={(ev) => {
                            if (ev.key === "Enter") salvarEdicao(campo);
                            if (ev.key === "Escape") setEditando(null);
                          }}
                          placeholder={dica}
                          className="min-w-0 flex-1 rounded-md border border-blue px-2 py-1 text-[12.5px] outline-none"
                        />
                        <button
                          type="button"
                          className="mbtn !px-2 !py-1 !text-[11px]"
                          onClick={() => salvarEdicao(campo)}
                          disabled={salvarCampo.isPending || rascunho.trim() === ""}
                        >
                          Salvar
                        </button>
                        <button
                          type="button"
                          className="mbtn-gh !px-2 !py-1 !text-[11px]"
                          onClick={() => setEditando(null)}
                        >
                          Cancelar
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className={`block w-full break-words text-left text-[11.5px] leading-snug ${
                          temValor ? "text-slatex" : "italic text-ghost"
                        } ${editavel ? "cursor-text hover:text-blue" : "cursor-default"}`}
                        title={editavel ? "Clique para editar" : undefined}
                        onClick={() => focarCampo(campo)}
                        disabled={!editavel}
                      >
                        {temValor ? valorLegivel(e.valor) : dica}
                      </button>
                    )}
                  </span>
                  {!emEdicao && (
                    <span className="flex flex-none items-center gap-1.5">
                      {!temValor && <span className="mchip-n">vazio</span>}
                      {temValor && e.inferido && (
                        <>
                          <span className="mchip-w">inferido</span>
                          <button
                            type="button"
                            className="mbtn-gh !px-2 !py-0.5 !text-[11px]"
                            title="Confirmação humana: inferido → confirmado"
                            onClick={() => salvarCampo.mutate({ campo, valor: e.valor })}
                            disabled={salvarCampo.isPending || !editavel}
                          >
                            Confirmar
                          </button>
                        </>
                      )}
                      {temValor && !e.inferido && <span className="mchip-g">confirmado</span>}
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          {/* CTA Converter em OS — só com completude 100 (A2: senão o backend nega com 409) */}
          {completa && editavel && (
            <div className="mt-3 rounded-lg border border-good bg-good-soft p-3">
              <div className="mb-2 text-[12.5px] font-bold text-good">
                Completude 100% — converter em OS
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  value={nomeOs}
                  onChange={(ev) => setNomeOs(ev.target.value)}
                  placeholder={
                    presente(objetivo.valor)
                      ? `Nome da OS (vazio = "${valorLegivel(objetivo.valor).slice(0, 40)}…")`
                      : "Nome da OS"
                  }
                  className="min-w-0 flex-1 rounded-md border border-line px-3 py-2 text-[13px] outline-none focus:border-blue"
                />
                <select
                  value={tshirt}
                  onChange={(ev) => setTshirt(ev.target.value as Tshirt)}
                  title="T-shirt size da OS"
                  className="rounded-md border border-line bg-white px-2 py-2 text-[13px] outline-none"
                >
                  {(["P", "M", "G", "GG"] as const).map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="mbtn-gd"
                  onClick={() => converter.mutate()}
                  disabled={converter.isPending}
                >
                  {converter.isPending ? "Convertendo…" : "Converter em OS →"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ChipEstadoPedido({ estado }: { estado?: string }) {
  if (estado === "completo") return <span className="mchip-g">completo</span>;
  if (estado === "convertido") return <span className="mchip-b">convertido</span>;
  if (estado === "arquivado") return <span className="mchip-n">arquivado</span>;
  if (estado === "rascunho") return <span className="mchip-n">rascunho</span>;
  return <span className="mchip-n">—</span>;
}

/* ===================================================================== modo OS */

function SalaOs({ id }: { id: string }) {
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

  // Medidor CONECTADO: sem conversa ainda, deriva do próprio briefing da OS
  // (os 5 campos obrigatórios §8-M3); com conversa, prevalece o cálculo do backend.
  const faltantesDerivados = useMemo(
    () =>
      briefing
        ? CAMPOS_PEDIDO.filter(({ campo }) => {
            const entrada = briefing.briefing?.[campo];
            return entrada === undefined || !presente(campoBriefing(entrada).valor);
          }).map(({ campo }) => campo)
        : [],
    [briefing],
  );
  const completudeVisivel = completude ?? (briefing ? (5 - faltantesDerivados.length) * 20 : null);
  const faltantesVisiveis = completude !== null ? faltantes : faltantesDerivados;

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
          Briefing{" "}
          <span className="tabular-nums">
            {completudeVisivel !== null ? `${completudeVisivel.toFixed(0)}%` : "—"}
          </span>
        </span>
        <span className="block w-full">
          <BarraProgresso
            pct={completudeVisivel ?? 0}
            tom={completudeVisivel === 100 ? "good" : "blue"}
          />
        </span>
        {faltantesVisiveis.length > 0 && (
          <span className="block text-[11.5px] text-warn">
            falta: {faltantesVisiveis.join(" · ")}
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
    [completudeVisivel, faltantesVisiveis, os],
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
