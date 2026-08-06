/**
 * T6 · Estúdio Criativo (mock T6 / SDD §8-M6): matriz canal × variante nascida do Key
 * Visual master (DCO); cada célula é um preview no device do canal com aprovação POR
 * CÉLULA (A3 — só humano analista+ aprova, nunca o agente); editar o KV master marca as
 * derivadas `adaptado_revisar` (A2); validadores por canal (SMS≤160, template Meta).
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { BadgeViaAi } from "../components/ai/BadgeViaAi";
import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { get, patch, post, put } from "../lib/api";
import { usePainelContextual } from "../lib/hooks";
import type {
  CanalCriativo,
  CelulaOut,
  CriativoOut,
  GerarCriativosOut,
  KvMasterOut,
  KvPadraoOut,
} from "../lib/types";
import { useProducao } from "../stores/producao";

const ORDEM_CANAIS: CanalCriativo[] = ["email", "push", "sms", "whatsapp"];
const CANAL_ROTULO: Record<CanalCriativo, string> = {
  email: "E-mail (âncora)",
  push: "Push Minha Claro",
  sms: "SMS",
  whatsapp: "WhatsApp (express)",
};
const LIMITE_CANAL: Partial<Record<CanalCriativo, number>> = { sms: 160, push: 120 };

/**
 * KV de partida enquanto o servidor não responde. O default REAL vem de
 * `GET /os/{id}/criativos/kv-padrao`, derivado do briefing da OS (§8-M6, achado A8):
 * copy fixa de uma campanha aqui vazava para OS de outro tema.
 */
const KV_PLACEHOLDER: Record<string, string> = {
  headline: "(defina o Key Visual)",
  oferta: "(defina a oferta)",
  cta: "(defina o CTA)",
  tom: "(defina o tom de marca)",
};

function ChipEstado({ estado }: { estado: CelulaOut["estado"] }) {
  if (estado === "aprovado") return <span className="mchip-g">aprovado</span>;
  if (estado === "revisar") return <span className="mchip-w">revisar</span>;
  if (estado === "adaptado_revisar")
    return <span className="mchip-w">adaptado — revisar</span>;
  return <span className="mchip-b">gerado</span>;
}

/** Coerção defensiva: o agente pode devolver campo não-string — nunca quebrar a UI. */
function textoDe(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

/** Preview da célula no "device" do canal (gramática do mock T6). */
function PreviewCelula({ celula }: { celula: CelulaOut }) {
  const c = celula.conteudo;
  const texto = textoDe(c.mensagem);
  const assunto = textoDe(c.assunto) || textoDe(c.titulo);
  const cta = textoDe(c.cta);
  const template =
    c.template && typeof c.template === "object"
      ? Object.values(c.template as Record<string, unknown>).map(textoDe).join(" · ")
      : textoDe(c.template);
  const limite = LIMITE_CANAL[celula.canal];

  if (celula.canal === "email") {
    const corBarra =
      celula.variante === "A"
        ? "bg-gradient-to-r from-[#E23B2E] to-[#B02318]"
        : "bg-gradient-to-r from-[#2B59C9] to-[#1B3D96]";
    return (
      <div className="rounded-md border border-line bg-[#EEF2F7] p-2">
        <div className={`mb-1.5 h-5 rounded ${corBarra}`} />
        <b className="block text-[12px] leading-snug">{assunto || "—"}</b>
        <div className="text-[11px] leading-snug text-slatex">{texto}</div>
        {cta && <div className="mt-1 font-mono text-[10.5px] text-blue">{cta}</div>}
      </div>
    );
  }
  if (celula.canal === "whatsapp") {
    return (
      <div className="rounded-lg rounded-bl-sm border border-[#BFE3CC] bg-[#E7F6EC] p-2 text-[11.5px] leading-snug">
        {assunto && <b className="block">{assunto}</b>}
        {texto}
        {cta && <b className="mt-1 block">[{cta}] [Agora não]</b>}
        {template && <span className="mchip-b mt-1">template Meta: {template}</span>}
      </div>
    );
  }
  // sms / push: texto puro + contador de caracteres
  return (
    <div className="text-[11.5px] leading-snug">
      {assunto && <b className="block">{assunto}</b>}
      <span className="text-steel">“{texto}”</span>{" "}
      {limite !== undefined && (
        <span className={texto.length <= limite ? "mchip-g" : "mchip-r"}>
          {texto.length}/{limite}c
        </span>
      )}
    </div>
  );
}

export function Criativo() {
  const { id } = useParams<{ id: string }>();
  const osId = id ?? "";

  const criativo = useProducao((s) => s.criativos[osId]);
  const setCriativo = useProducao((s) => s.setCriativo);

  // Default DERIVADO do briefing desta OS (determinístico, via_ai:false — A8).
  const kvPadrao = useQuery({
    queryKey: ["os", osId, "criativos", "kv-padrao"],
    queryFn: ({ signal }) => get<KvPadraoOut>(`/os/${osId}/criativos/kv-padrao`, signal),
    enabled: Boolean(osId),
  });

  // Edição fica presa à OS que a originou (trocar de OS não carrega KV da anterior).
  const [edicao, setEdicao] = useState<{ os: string; kv: Record<string, string> } | null>(null);
  const [kvAberto, setKvAberto] = useState(false);
  const [avisos, setAvisos] = useState<string[]>([]);

  // Precedência: edição do usuário > KV que gerou a matriz > default do briefing.
  const kvEditado = edicao?.os === osId ? edicao.kv : null;
  const kvDaMatriz = criativo
    ? Object.fromEntries(Object.entries(criativo.kv_master).map(([k, v]) => [k, textoDe(v)]))
    : null;
  const kv: Record<string, string> =
    kvEditado ?? kvDaMatriz ?? kvPadrao.data?.kv_master ?? KV_PLACEHOLDER;
  const setKv = (campo: string, valor: string) =>
    setEdicao({ os: osId, kv: { ...kv, [campo]: valor } });

  const gerar = useMutation({
    mutationFn: (instrucoes?: string) =>
      post<GerarCriativosOut>(`/os/${osId}/criativos/gerar`, {
        kv_master: kv,
        instrucoes: instrucoes ?? null,
      }),
    onSuccess: (saida) => {
      setCriativo(osId, saida.criativo);
      setAvisos(saida.avisos);
    },
  });

  const decidirCelula = useMutation({
    mutationFn: (payload: {
      canal: CanalCriativo;
      variante: string;
      acao: "aprovar" | "revisar";
    }) => patch<CriativoOut>(`/criativos/${criativo?.id}/celula`, payload),
    onSuccess: (c) => setCriativo(osId, c),
  });

  const editarKv = useMutation({
    mutationFn: () => put<KvMasterOut>(`/criativos/${criativo?.id}/kv-master`, { kv_master: kv }),
    onSuccess: (saida) => {
      setCriativo(osId, saida.criativo);
      setAvisos(saida.avisos);
      setKvAberto(false);
    },
  });

  const variantes = [...new Set((criativo?.celulas ?? []).map((c) => c.variante))].sort();
  const celula = (canal: CanalCriativo, variante: string) =>
    criativo?.celulas.find((c) => c.canal === canal && c.variante === variante);

  const aprovadas = criativo?.celulas.filter((c) => c.estado === "aprovado").length ?? 0;

  usePainelContextual(
    <>
      <div className="ctx-title">CLARO Visual + Copy</div>
      <div className="mfield">
        <span className="min-w-0">
          <span className="block text-[12px] font-bold">Benchmark RAG</span>
          <span className="block text-[11.5px] leading-relaxed text-slatex">
            Top-5 criativos de franquia: headlines com “sem sustos” batem CTR +2,1pp.
          </span>
        </span>
      </div>
      <div className="ctx-title">Compliance de linguagem</div>
      <div className="mfield">
        <span className="min-w-0 text-[11.5px] leading-relaxed text-slatex">
          {avisos.length > 0 ? (
            avisos.map((a, i) => (
              <span key={i} className="block text-warn">
                ⚠ {a}
              </span>
            ))
          ) : (
            <>
              ✓ Sem promessa proibida · ✓ claim bate com o Catálogo · ✓ opt-out presente em
              SMS/WhatsApp
            </>
          )}
        </span>
        <span className="mchip-g">Guard</span>
      </div>
      <div className="ctx-title">Ações</div>
      <Copiloto
        titulo="Copy"
        acao="Regenerar com ajuste"
        onAcao={() =>
          gerar.mutate("Regenerar a variante B com tom mais direto; público sensível a preço; oferta = mesmo valor.")
        }
      >
        Regenerar a variante B com tom mais direto? Premissas:{" "}
        <span className="mchip bg-claro-dark text-claro-rose">público sensível a preço</span>{" "}
        <span className="mchip bg-claro-dark text-claro-rose">oferta = mesmo valor</span>
      </Copiloto>
      <div className="mt-3 border-t border-linesoft pt-2 text-[10.5px] text-faint">
        A3 (§8-M6): nenhuma célula vai a “aprovado” via agente — só usuário analista+.
      </div>
    </>,
    [avisos, gerar.isPending],
  );

  return (
    <div>
      <TituloTela
        titulo="Estúdio Criativo"
        subtitulo={
          <>
            Key Visual master → adaptações por canal · aprovação célula a célula{" "}
            {criativo && (
              <span className="mchip-b">
                {aprovadas}/{criativo.celulas.length} aprovadas
              </span>
            )}
          </>
        }
      />

      {gerar.error != null && <BannerErro erro={gerar.error} contexto="Geração (Visual/Copy)" />}
      {decidirCelula.error != null && (
        <BannerErro erro={decidirCelula.error} contexto="Decisão da célula" />
      )}
      {editarKv.error != null && <BannerErro erro={editarKv.error} contexto="KV master" />}
      {kvPadrao.error != null && (
        <BannerErro erro={kvPadrao.error} contexto="KV de partida (briefing da OS)" />
      )}

      {/* ------------------------------------------------------- KV master */}
      <div className="mcard mb-3">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
            Key Visual master{" "}
            {criativo && (
              <BadgeViaAi rastro={{ agente: "visual · copy · content", skill: "v2.7" }} />
            )}
          </div>
          <div className="flex gap-1.5">
            <button
              type="button"
              className="mbtn-gh !px-2.5 !py-1 !text-[11px]"
              onClick={() => setKvAberto((a) => !a)}
            >
              {kvAberto ? "Fechar edição" : "Editar KV master"}
            </button>
            <button
              type="button"
              className="mbtn !px-2.5 !py-1 !text-[11px]"
              disabled={gerar.isPending}
              onClick={() => gerar.mutate(undefined)}
            >
              {gerar.isPending
                ? "Gerando matriz…"
                : criativo
                  ? "Regenerar matriz"
                  : "Gerar matriz (Visual/Copy)"}
            </button>
          </div>
        </div>

        {!kvAberto ? (
          <>
            <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11.5px]">
              {Object.entries(kv).map(([campo, valor]) => (
                <span key={campo} className="mchip-n">
                  <b>{campo}:</b> {valor}
                </span>
              ))}
            </div>
            {!kvEditado && !criativo && kvPadrao.data && (
              <div className="mt-1 text-[11px] text-slatex">
                {kvPadrao.data.suficiente ? (
                  <>
                    Partida derivada do briefing desta OS ({kvPadrao.data.derivado_de.join(" · ")})
                    — edite antes de gerar.
                  </>
                ) : (
                  <span className="text-warn">
                    Briefing sem objetivo/oferta — preencha o Key Visual (ou volte ao briefing);
                    o Estúdio não inventa copy de outra campanha.
                  </span>
                )}
              </div>
            )}
          </>
        ) : (
          <div className="mt-2 grid gap-1.5">
            {Object.entries(kv).map(([campo, valor]) => (
              <label key={campo} className="flex items-center gap-2 text-[12px]">
                <span className="w-20 flex-none font-bold text-steel">{campo}</span>
                <input
                  value={valor}
                  onChange={(e) => setKv(campo, e.target.value)}
                  className="min-w-0 flex-1 rounded-md border border-line2 px-2.5 py-1.5 text-[12.5px] outline-none focus:border-blue"
                />
              </label>
            ))}
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="mbtn !px-2.5 !py-1 !text-[11px]"
                disabled={editarKv.isPending || !criativo}
                title={criativo ? undefined : "Gere a matriz primeiro"}
                onClick={() => editarKv.mutate()}
              >
                {editarKv.isPending ? "Propagando…" : "Salvar KV (propaga adaptações)"}
              </button>
              <span className="text-[11px] text-warn">
                A2: editar o KV marca TODAS as células derivadas “adaptado — revisar”
                (aprovações caem).
              </span>
            </div>
          </div>
        )}
      </div>

      {!criativo && (
        <EstadoVazio>
          Sem matriz ainda — o pipeline Visual → Copy → Content gera a primeira versão de
          tudo a partir do KV master. Nada publica sem aprovação humana célula a célula.
        </EstadoVazio>
      )}

      {/* ----------------------------------------------- matriz canal×variante */}
      {criativo && (
        <div className="mcard overflow-x-auto p-0">
          <table className="w-full border-collapse text-[12.5px]">
            <thead>
              <tr className="border-b border-line text-left text-[10px] uppercase tracking-[.06em] text-faint">
                <th className="px-4 py-2">Canal</th>
                {variantes.map((v) => (
                  <th key={v} className="px-3 py-2">
                    Variante {v}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ORDEM_CANAIS.filter((canal) =>
                criativo.celulas.some((c) => c.canal === canal),
              ).map((canal) => (
                <tr key={canal} className="border-b border-linesoft align-top last:border-0">
                  <td className="px-4 py-2.5 font-bold">{CANAL_ROTULO[canal]}</td>
                  {variantes.map((variante) => {
                    const c = celula(canal, variante);
                    if (!c)
                      return (
                        <td key={variante} className="px-3 py-2.5 text-muted">
                          — (variante única no canal)
                        </td>
                      );
                    return (
                      <td key={variante} className="min-w-[220px] px-3 py-2.5">
                        <PreviewCelula celula={c} />
                        <div className="mt-1.5 flex items-center gap-1.5">
                          <ChipEstado estado={c.estado} />
                          <button
                            type="button"
                            className="mbtn-gd !px-2 !py-0.5 !text-[10.5px]"
                            disabled={decidirCelula.isPending || c.estado === "aprovado"}
                            onClick={() =>
                              decidirCelula.mutate({ canal, variante, acao: "aprovar" })
                            }
                          >
                            Aprovar
                          </button>
                          <button
                            type="button"
                            className="mbtn-gh !px-2 !py-0.5 !text-[10.5px]"
                            disabled={decidirCelula.isPending || c.estado === "revisar"}
                            onClick={() =>
                              decidirCelula.mutate({ canal, variante, acao: "revisar" })
                            }
                          >
                            Revisar
                          </button>
                        </div>
                        {c.observacao && (
                          <div className="mt-1 text-[11px] text-slatex">{c.observacao}</div>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
