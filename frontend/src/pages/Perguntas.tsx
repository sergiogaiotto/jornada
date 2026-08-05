/**
 * T14 · Pergunte aos Dados (mock T14 / SDD §8-M10 parte 3, §7.2 insight):
 * NL → consulta NOMEADA `vw_metricas_*` da camada semântica VERSIONADA — nunca SQL
 * livre; a resposta SEMPRE anexa a consulta executada (inspecionável). Fora do
 * escopo (ex.: pedido de CPF) ⇒ recusa padrão SEM executar nada (A4). Toda pergunta
 * grava `invocacao` (via_ai — LGPD Art. 20).
 */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { BadgeViaAi } from "../components/ai/BadgeViaAi";
import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { post } from "../lib/api";
import { usePainelContextual } from "../lib/hooks";
import type { PerguntaOut } from "../lib/types";

interface Troca {
  pergunta: string;
  resposta: PerguntaOut;
}

const SUGESTOES = [
  "Qual o ROAS até agora contra o previsto?",
  "Qual o custo por pedido no WhatsApp?",
  "Atingimos as metas do briefing?",
  "Qual o lift vs holdout — já é significativo?",
];

/** Demonstra a recusa determinística (A4): PII nunca vira consulta. */
const SUGESTAO_RECUSA = "Qual o CPF do cliente que mais comprou?";

function Resultado({ valor }: { valor: unknown }) {
  if (valor === null || valor === undefined) return <i>—</i>;
  if (typeof valor === "number")
    return <b className="tabular-nums">{valor.toLocaleString("pt-BR")}</b>;
  if (typeof valor === "string" || typeof valor === "boolean") return <b>{String(valor)}</b>;
  return (
    <pre className="mt-0.5 max-h-40 overflow-auto rounded-md bg-surface2 p-2 font-mono text-[10.5px] leading-relaxed">
      {JSON.stringify(valor, null, 2)}
    </pre>
  );
}

function CartaoResposta({ troca }: { troca: Troca }) {
  const [verQuery, setVerQuery] = useState(false);
  const r = troca.resposta;
  const consulta = r.consulta_executada;

  return (
    <div className="grid gap-1.5">
      <div className="mcard ml-auto max-w-[85%] bg-blue-soft">
        <span className="text-[12.5px]">
          <b>Você:</b> {troca.pergunta}
        </span>
      </div>
      <div className={`mcard max-w-[92%] ${r.recusado ? "border-warn-line bg-warn-bg" : ""}`}>
        <div className="text-[12.5px] leading-relaxed">
          <b>Insight:</b> {r.resposta}
        </div>
        {r.recusado && (
          <div className="mt-1.5 text-[11.5px] text-warn">
            <span className="mchip-w mr-1.5">recusa padrão (A4)</span>
            {r.motivo_recusa} — nenhuma consulta foi executada.
          </div>
        )}
        {consulta && (
          <>
            <div className="mt-2 grid gap-1 text-[12px]">
              {Object.entries(consulta.resultado).map(([chave, valor]) => (
                <div key={chave} className="flex items-baseline justify-between gap-3">
                  <span className="text-slatex">{chave.split("_").join(" ")}</span>
                  <span className="text-right">
                    <Resultado valor={valor} />
                  </span>
                </div>
              ))}
            </div>
            {verQuery && (
              <div className="mt-2 rounded-md border border-linesoft bg-surface2 p-2">
                <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                  Consulta executada — {consulta.nome}@{consulta.versao} (métrica{" "}
                  {consulta.metrica})
                </div>
                <pre className="mt-1 overflow-x-auto font-mono text-[10.5px] leading-relaxed text-steel">
                  {consulta.sql}
                </pre>
                {Object.keys(consulta.parametros).length > 0 && (
                  <div className="mt-1 text-[11px] text-muted">
                    parâmetros: {JSON.stringify(consulta.parametros)}
                  </div>
                )}
              </div>
            )}
          </>
        )}
        <div className="mt-2 flex items-center gap-2">
          {consulta && (
            <button
              type="button"
              className="mbtn-gh !px-2.5 !py-1 !text-[11px]"
              onClick={() => setVerQuery((v) => !v)}
            >
              {verQuery ? "Ocultar query" : "Ver query executada"}
            </button>
          )}
          <span className="mchip-n">
            camada semântica v{String(r.camada_semantica["versao"] ?? "—")}
          </span>
          <span className="flex-1" />
          <BadgeViaAi
            rastro={{
              agente: "insight",
              skill: consulta
                ? `${consulta.nome}@${consulta.versao}`
                : "recusa determinística (sem LLM)",
              evidencias: consulta ? [`${consulta.nome}@${consulta.versao}`] : [],
              humano: "leitura assistida — sem aceite necessário",
            }}
          />
        </div>
      </div>
    </div>
  );
}

export function Perguntas() {
  const { id } = useParams<{ id: string }>();
  const osId = id ?? "";

  const [pergunta, setPergunta] = useState("");
  const [trocas, setTrocas] = useState<Troca[]>([]);

  const perguntar = useMutation({
    mutationFn: (texto: string) =>
      post<PerguntaOut>(`/os/${osId}/perguntar`, { pergunta: texto }).then(
        (resposta) => ({ pergunta: texto, resposta }) as Troca,
      ),
    onSuccess: (troca) => {
      setTrocas((t) => [...t, troca]);
      setPergunta("");
    },
  });

  const enviar = (texto: string) => {
    const limpo = texto.trim();
    if (limpo && !perguntar.isPending) perguntar.mutate(limpo);
  };

  usePainelContextual(
    <>
      <div className="ctx-title">Contexto da resposta</div>
      <div className="mfield">
        <span className="text-[12px]">
          Consultas NOMEADAS da camada semântica versionada — o agente compõe,{" "}
          <b>nunca inventa fórmula</b>; a query executada é sempre inspecionável (§7.2)
        </span>
      </div>
      <div className="mfield">
        <span className="text-[12px]">
          <b>vw_metricas_roas</b> · <b>vw_metricas_lift</b> ·{" "}
          <b>vw_metricas_custo_por_pedido</b> · <b>vw_metricas_atingimento_meta</b>
        </span>
      </div>

      <div className="ctx-title">Escopo (A4)</div>
      <div className="mfield">
        <span className="text-[12px]">
          Pedido de dado individual/PII ⇒ <b>recusa padrão sem executar nada</b> — a
          pré-guarda é determinística, nem chama o LLM (§10.2)
        </span>
      </div>

      <div className="ctx-title">Sugestões</div>
      <Copiloto titulo="Insight">
        Experimente: “{SUGESTOES[0]}” · “{SUGESTOES[2]}” — ou teste a guarda de escopo
        com “{SUGESTAO_RECUSA}”.
      </Copiloto>
    </>,
    [osId],
  );

  return (
    <div>
      <TituloTela
        titulo={
          <>
            Pergunte aos Dados <span className="mchip-b align-middle">NL → consulta nomeada</span>
          </>
        }
        subtitulo="Respostas a partir dos números desta jornada — custo, receita, ROAS, lift, metas — sempre com a query anexada"
      />

      {perguntar.error != null && (
        <BannerErro erro={perguntar.error} contexto="Pergunte aos Dados" />
      )}

      <div className="mcard mb-3">
        <div className="flex flex-wrap gap-1.5">
          {[...SUGESTOES, SUGESTAO_RECUSA].map((s) => (
            <button
              key={s}
              type="button"
              className={`rounded-full border px-2.5 py-0.5 text-[11px] font-semibold transition-colors ${
                s === SUGESTAO_RECUSA
                  ? "border-warn-line text-warn hover:bg-warn-bg"
                  : "border-line2 text-slatex hover:bg-surface2"
              }`}
              disabled={perguntar.isPending}
              onClick={() => enviar(s)}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3">
        {trocas.length === 0 && !perguntar.isPending && (
          <EstadoVazio>
            Faça uma pergunta em linguagem natural — a resposta compara sempre com o{" "}
            <b>Previsto congelado</b> (§1.1.2) e mostra a consulta executada. Sem previsto
            congelado, o backend responde 409 (mesma régua do{" "}
            <Link to={`/os/${osId}/monitor`} className="font-semibold text-blue underline">
              monitor T13
            </Link>
            ).
          </EstadoVazio>
        )}
        {trocas.map((troca, i) => (
          <CartaoResposta key={i} troca={troca} />
        ))}
        {perguntar.isPending && (
          <div className="mcard max-w-[92%] text-[12.5px] text-muted">
            <b>Insight:</b> compondo a consulta nomeada…
          </div>
        )}
      </div>

      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          enviar(pergunta);
        }}
      >
        <input
          value={pergunta}
          onChange={(e) => setPergunta(e.target.value)}
          placeholder="ex.: qual canal deu mais conversão por real gasto?"
          className="flex-1 rounded-md border border-line2 px-3 py-2 text-[13px] outline-none focus:border-blue"
        />
        <button type="submit" className="mbtn" disabled={perguntar.isPending || !pergunta.trim()}>
          {perguntar.isPending ? "Perguntando…" : "Perguntar"}
        </button>
      </form>
    </div>
  );
}
