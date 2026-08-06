/**
 * T10 · Portal de Aprovação — página STANDALONE do link mágico (/aprovacao/:token,
 * SEM shell — SDD §12). Snapshot imutável: resumo executivo, waterfall, criativos,
 * replay do Previsto e hash visível; decisão única (Aprovar / Aprovar com ressalvas /
 * Reprovar) — ressalvas viram pendências automáticas. Sem painel direito e sem ações de
 * IA: foco total na decisão.
 *
 * Emenda E03 (§10.5) — standalone deixou de significar ANÔNIMO. O token era a
 * credencial, e ele volta em claro para quem EMITE o link: na prática o criador ficava
 * com o poder de decidir pelo aprovador. Agora o token é só o PONTEIRO para o pacote e a
 * identidade vem da sessão:
 *
 * · a rota vive sob `<ExigirSessao>` (App.tsx/E04), que manda para `/login` guardando o
 *   destino — o deep link continua funcionando: entra, e cai de volta no pacote;
 * · a página mostra QUEM está decidindo, com o e-mail que o SERVIDOR reconheceu na
 *   sessão (`sessao` no payload), não um palpite do cliente;
 * · quem não é o destinatário lê o pacote (é o time da campanha) mas não vê botão de
 *   decisão: o servidor responderia 403, e oferecer o botão seria mentir para o usuário.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";

import { BannerErro } from "../components/ui/basics";
import { ApiError, get, post } from "../lib/api";
import { fmtBRL, fmtCompacto, fmtInt, rotuloFonte } from "../lib/format";
import type {
  AprovacaoPayloadOut,
  DecisaoAprovacao,
  DecisaoOut,
} from "../lib/types";

/**
 * Bloco `sessao` acrescentado ao payload pela emenda E03 — quem o servidor reconheceu
 * nesta requisição e se essa pessoa é a designada no link. Tipado AQUI (e opcional)
 * porque `lib/types.ts` é o espelho do contrato e pertence a outra frente: opcional
 * também é o comportamento correto contra um backend antigo — sem o bloco, a página
 * degrada para "só o destinatário aparece", nunca para "libera o botão".
 */
type PaginaAprovacao = AprovacaoPayloadOut & {
  sessao?: { email: string; nome: string | null; pode_decidir: boolean };
};

const CANAL_ROTULO: Record<string, string> = {
  email: "E-mail",
  sms: "SMS",
  push: "Push",
  whatsapp: "WhatsApp",
};

function KpiClaro({
  rotulo,
  valor,
  detalhe,
  tom = "ink",
}: {
  rotulo: string;
  valor: string;
  detalhe: string;
  tom?: "ink" | "good" | "blue";
}) {
  const cor = { ink: "text-ink2", good: "text-good", blue: "text-blue" }[tom];
  return (
    <div className="min-w-[130px] flex-1 rounded-lg border border-line bg-surface2 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-[.06em] text-faint">{rotulo}</div>
      <div className={`text-[20px] font-extrabold tracking-[-.02em] tabular-nums ${cor}`}>
        {valor}
      </div>
      <div className="text-[11px] text-muted">{detalhe}</div>
    </div>
  );
}

export function Aprovacao() {
  const { token } = useParams<{ token: string }>();

  const [decisaoEscolhida, setDecisaoEscolhida] = useState<DecisaoAprovacao | null>(null);
  const [ressalvas, setRessalvas] = useState("");
  const [replayAberto, setReplayAberto] = useState(false);
  const [resultado, setResultado] = useState<DecisaoOut | null>(null);

  const pagina = useQuery({
    queryKey: ["aprovacao", token],
    queryFn: ({ signal }) => get<PaginaAprovacao>(`/aprovacao/${token}`, signal),
    enabled: Boolean(token),
    retry: false,
  });

  const decidir = useMutation({
    mutationFn: (decisao: DecisaoAprovacao) =>
      post<DecisaoOut>(`/aprovacao/${token}/decidir`, {
        decisao,
        ressalvas:
          decisao === "aprovado_ressalvas"
            ? ressalvas
                .split("\n")
                .map((r) => r.trim())
                .filter(Boolean)
            : [],
        // A6 (§10.5): identidade NÃO viaja no corpo — o servidor usa o e-mail
        // congelado na emissão do link. Mandar aqui só serviria para tomar 409.
      }),
    onSuccess: setResultado,
  });

  const dados = pagina.data;
  const sessao = dados?.sessao ?? null;
  // Sem o bloco `sessao` (backend anterior ao E03) o botão NÃO aparece: a falha tem que
  // ser para o lado de não decidir. Com ele, quem manda é o servidor.
  const podeDecidir = sessao?.pode_decidir === true;
  const expirado = pagina.error instanceof ApiError && pagina.error.status === 410;
  const previsto = dados?.previsto ?? null;
  const waterfall = dados?.waterfall ?? [];
  const bruto = waterfall.length > 0 ? waterfall[0].restante + waterfall[0].corte : null;
  const liquido = waterfall.length > 0 ? waterfall[waterfall.length - 1].restante : null;
  const decisaoFinal = resultado?.decisao ?? dados?.decisao ?? null;
  const funil = Object.entries(previsto?.funil ?? {});
  const maxFunil = Math.max(1, ...funil.map(([, v]) => v.p50));

  return (
    <div className="min-h-screen bg-[#EDF1F6]">
      {/* topo claro — sem chrome vermelho: a tela é do PACOTE, não do app */}
      <div className="flex items-center gap-2 border-b border-line bg-white px-5 py-3">
        <span className="text-[15px] font-extrabold text-ink2">
          <span className="mr-1.5 inline-block h-2.5 w-2.5 rounded-[3px] bg-claro" />
          Jornada
        </span>
        <span className="text-[12px] text-muted">
          Aprovação segura · sessão autenticada · decisão única
        </span>
        <span className="flex-1" />
        {/* E03: quem o SERVIDOR reconheceu — a tela nunca afirma identidade por conta
            própria, e o usuário vê com que conta está prestes a decidir */}
        {sessao && (
          <span className="rounded-full bg-linesoft px-3 py-1 text-[11px] text-slatex">
            {sessao.nome ?? sessao.email}
          </span>
        )}
        {dados && (
          <span className="rounded-full bg-linesoft px-3 py-1 font-mono text-[11px] text-slatex">
            snapshot {dados.snapshot.hash.slice(0, 12)}…
          </span>
        )}
      </div>

      <div className="mx-auto max-w-[640px] px-4 py-6">
        {pagina.isLoading && (
          <div className="mcard py-8 text-center text-[13px] text-muted">
            Abrindo o pacote de aprovação…
          </div>
        )}

        {expirado && (
          <div className="mcard border-warn-line bg-warn-bg py-6 text-center">
            <div className="text-[15px] font-bold text-warn">Link mágico expirado</div>
            <div className="mt-1 text-[12.5px] text-muted">
              O link é de uso único e expira (§8-M8-A3) — solicite um novo ao time da
              campanha.
            </div>
          </div>
        )}
        {pagina.error != null && !expirado && (
          <BannerErro erro={pagina.error} contexto="Link de aprovação" />
        )}

        {dados && (
          <div className="mcard !px-5 !py-4 shadow-card">
            <h1 className="text-[17px] font-bold tracking-[-.01em] text-ink2">
              {dados.os.nome}
            </h1>
            <div className="text-[12px] text-muted">
              {dados.os.codigo} · pacote de aprovação · alçada <b>{dados.alcada}</b> ·
              expira {new Date(dados.expira_em).toLocaleString("pt-BR")}
            </div>

            {/* --------------------------------------------------- KPIs */}
            <div className="mt-3 flex flex-wrap gap-2">
              <KpiClaro
                rotulo="Público líquido"
                valor={liquido !== null ? fmtInt(liquido) : "—"}
                detalhe="pós 7 listas + opt-in"
              />
              <KpiClaro
                rotulo="Investimento"
                valor={fmtBRL(dados.resumo.custo.previsto_p50, 0)}
                detalhe={`alçada ${dados.alcada} ✓`}
              />
              <KpiClaro
                rotulo="ROAS previsto"
                valor={
                  previsto?.roas
                    ? `${previsto.roas.p50.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}x`
                    : "—"
                }
                detalhe={
                  previsto?.roas
                    ? `P10 ${previsto.roas.p10.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}x · P90 ${previsto.roas.p90.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}x`
                    : "previsto congelado"
                }
                tom="good"
              />
              <KpiClaro
                rotulo="Holdout"
                valor={
                  dados.resumo.experimento
                    ? `${dados.resumo.experimento.holdout_pct.toLocaleString("pt-BR")}%`
                    : "—"
                }
                detalhe={
                  dados.resumo.experimento
                    ? `MDE ${dados.resumo.experimento.mde_pp.toLocaleString("pt-BR")}pp · ${dados.resumo.experimento.janela_dias}d`
                    : "sem experimento"
                }
                tom="blue"
              />
            </div>

            {/* ------------------------------------------ replay do previsto */}
            <button
              type="button"
              onClick={() => setReplayAberto((a) => !a)}
              className="mt-3 flex w-full items-center gap-2.5 rounded-lg bg-claro px-3.5 py-2.5 text-left text-claro-pale transition-opacity hover:opacity-95"
            >
              <span className="text-[16px]">{replayAberto ? "▼" : "▶"}</span>
              <span className="text-[12px]">
                <b className="text-white">Replay da simulação</b> — o funil previsto
                congelado, nó a nó (P50 de {previsto?.runs ?? "—"} runs Monte Carlo)
              </span>
            </button>
            {replayAberto && previsto && (
              <div className="mt-2 grid gap-1.5 rounded-lg border border-linesoft bg-surface2 p-3">
                {funil.map(([noId, v]) => (
                  <div key={noId} className="text-[11.5px]">
                    <div className="flex items-baseline justify-between gap-2">
                      <span>
                        <span className="font-mono font-semibold">{noId}</span>{" "}
                        <span className="text-faint">{v.tipo}</span>
                      </span>
                      <b className="tabular-nums">{fmtCompacto(Math.round(v.p50))}</b>
                    </div>
                    <div className="mbar">
                      <i
                        className="bg-ch4"
                        style={{ width: `${Math.max(1, (100 * v.p50) / maxFunil)}%` }}
                      />
                    </div>
                  </div>
                ))}
                <div className="text-[11px] text-muted">
                  Conversões P50 <b>{fmtInt(Math.round(previsto.conversoes.p50))}</b> · lift
                  esperado{" "}
                  <b>
                    {previsto.lift_pp.p50 >= 0 ? "+" : ""}
                    {previsto.lift_pp.p50.toLocaleString("pt-BR", {
                      maximumFractionDigits: 1,
                    })}
                    pp
                  </b>{" "}
                  vs holdout · congelado em{" "}
                  {previsto.congelado_em
                    ? new Date(previsto.congelado_em).toLocaleString("pt-BR")
                    : "—"}
                </div>
              </div>
            )}

            {/* -------------------------------------------------- waterfall */}
            {waterfall.length > 0 && bruto !== null && (
              <div className="mt-3">
                <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                  Waterfall da audiência
                </div>
                <div className="mt-1 grid gap-1">
                  {waterfall.map((e) => (
                    <div key={e.etapa} className="text-[11.5px]">
                      <div className="flex items-baseline justify-between gap-2">
                        <span>
                          − {rotuloFonte(e.etapa)}{" "}
                          <span className="text-faint">−{fmtCompacto(e.corte)}</span>
                        </span>
                        <b className="tabular-nums">{fmtInt(e.restante)}</b>
                      </div>
                      <div className="mbar">
                        <i
                          className="bg-ch3"
                          style={{
                            width: `${Math.max(1, (100 * e.restante) / bruto)}%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ------------------------------------------ criativos + volume */}
            <div className="mt-3 flex flex-wrap gap-1.5 text-[11px]">
              <span className="mchip-n">política v{dados.resumo.politica_versao}</span>
              <span className="mchip-n">
                JGC v{dados.resumo.jgc.versao} ·{" "}
                <span className="font-mono">{dados.resumo.jgc.hash.slice(0, 8)}…</span>
              </span>
              {dados.resumo.experimento && <span className="mchip-n">experimento travado</span>}
              {Object.entries(dados.volume_abordagem ?? {}).map(([canal, v]) => (
                <span key={canal} className="mchip-b">
                  {CANAL_ROTULO[canal] ?? canal} {fmtCompacto(v.n)}
                </span>
              ))}
            </div>
            {dados.criativos.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                {dados.criativos.flatMap((c) =>
                  Object.entries(c.celulas).map(([celula, estado]) => (
                    <span
                      key={`${c.id}:${celula}`}
                      className={estado === "aprovado" ? "mchip-g" : "mchip-w"}
                    >
                      {celula} · {estado}
                    </span>
                  )),
                )}
              </div>
            )}

            {/* -------------------------------------------------- invalidada */}
            {dados.invalidada && (
              <div className="mt-3 rounded-lg border border-crit/40 bg-crit-soft px-3 py-2 text-[12px] text-crit">
                <b>Aprovação invalidada:</b> {dados.invalidada_motivo} (§8-M8-A4 — snapshot
                novo obrigatório)
              </div>
            )}

            {/* ---------------------------------------------------- decisão */}
            {decisaoFinal !== null ? (
              <div
                className={`mt-4 rounded-lg px-4 py-3 text-[13px] ${
                  decisaoFinal === "reprovado"
                    ? "bg-crit-soft text-crit"
                    : "bg-good-soft text-good"
                }`}
              >
                <b>
                  Decisão registrada:{" "}
                  {decisaoFinal === "aprovado"
                    ? "Aprovado"
                    : decisaoFinal === "aprovado_ressalvas"
                      ? "Aprovado com ressalvas"
                      : "Reprovado"}
                </b>
                {(resultado?.ressalvas ?? dados.ressalvas).length > 0 && (
                  <span className="mt-1 block text-[12px]">
                    {(resultado?.ressalvas ?? dados.ressalvas).map((r) => (
                      <span key={r.pendencia_numero} className="block">
                        • Pendência #{r.pendencia_numero}: {r.texto}
                      </span>
                    ))}
                  </span>
                )}
                <span className="mt-1 block text-[11px] opacity-80">
                  Link de uso único encerrado · IP, dispositivo e horário registrados ·
                  ressalvas viraram pendências bloqueantes automaticamente
                </span>
              </div>
            ) : (
              !dados.invalidada && !podeDecidir ? (
                /* E03 (§10.5): sessão que NÃO é a do destinatário lê o pacote e para aí.
                   O servidor responderia 403 — mostrar os botões seria convidar o usuário
                   a bater numa porta trancada. O e-mail do aprovador aparece aqui porque
                   quem chegou até este ponto é gente do tenant dono da campanha (o mesmo
                   público que já vê a trilha da OS), não um portador anônimo de token. */
                <div className="mt-4 rounded-lg border border-line bg-surface2 px-4 py-3 text-[12.5px] text-slatex">
                  <b>Esta decisão não é sua.</b> O pacote foi endereçado a{" "}
                  <b>{dados.aprovador_email ?? "outro aprovador"}</b> na emissão do link, e
                  quem decide é a sessão dessa pessoa — ter o link não dá direito de
                  aprovar (§10.5).
                  {sessao && (
                    <span className="mt-1 block text-[11px] text-ghost">
                      Você está autenticado como {sessao.email}. Para decidir, entre com a
                      conta do aprovador ou peça um link novo endereçado a você.
                    </span>
                  )}
                </div>
              ) : (
                !dados.invalidada && (
                <div className="mt-4">
                  {decidir.error != null && (
                    <BannerErro erro={decidir.error} contexto="Decisão" />
                  )}
                  {/* A6+E03 (§10.5): nada de digitar quem é você — o link já sabe QUEM
                      pode decidir, e a sessão prova que é você. */}
                  <div className="mb-2 rounded-md bg-surface2 px-3 py-2 text-[12px] text-slatex">
                    Decidindo como{" "}
                    <b>{sessao?.email ?? dados.aprovador_email ?? "aprovador deste link"}</b>{" "}
                    — sessão autenticada, conferida contra o destinatário carimbado na
                    emissão do link.
                  </div>
                  {decisaoEscolhida === "aprovado_ressalvas" && (
                    <textarea
                      value={ressalvas}
                      onChange={(e) => setRessalvas(e.target.value)}
                      rows={3}
                      placeholder="Uma ressalva por linha — cada uma vira uma pendência bloqueante na OS."
                      className="mb-2 w-full resize-y rounded-md border border-warn-line px-3 py-2 text-[12.5px] outline-none focus:border-warn"
                    />
                  )}
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="mbtn-gd !px-5"
                      disabled={decidir.isPending}
                      onClick={() => decidir.mutate("aprovado")}
                    >
                      Aprovar
                    </button>
                    <button
                      type="button"
                      className="mbtn !bg-warn !px-5"
                      disabled={
                        decidir.isPending ||
                        (decisaoEscolhida === "aprovado_ressalvas" &&
                          ressalvas.trim().length === 0)
                      }
                      onClick={() => {
                        if (decisaoEscolhida !== "aprovado_ressalvas") {
                          setDecisaoEscolhida("aprovado_ressalvas");
                        } else {
                          decidir.mutate("aprovado_ressalvas");
                        }
                      }}
                    >
                      {decisaoEscolhida === "aprovado_ressalvas"
                        ? "Confirmar com ressalvas"
                        : "Aprovar com ressalvas"}
                    </button>
                    <button
                      type="button"
                      className="mbtn-rd !px-5"
                      disabled={decidir.isPending}
                      onClick={() => decidir.mutate("reprovado")}
                    >
                      Reprovar
                    </button>
                  </div>
                  <div className="mt-2 text-[11px] text-ghost">
                    Decisão única · IP, dispositivo e horário são registrados · ressalvas
                    viram pendências automaticamente · o hash{" "}
                    <span className="font-mono">{dados.snapshot.hash.slice(0, 12)}…</span>{" "}
                    garante que o aprovado é exatamente o que será publicado
                  </div>
                </div>
                )
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}
