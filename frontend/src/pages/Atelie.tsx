/**
 * T16 · Ateliê de Agentes — governança da plataforma (mock T16 / SDD §8-M12, §7):
 * catálogo do roster organizado POR ETAPA do workflow, com versão publicada, SKILL
 * vinculada e score no harness; painel do agente com o system prompt VISÍVEL
 * (SKILL.md canônico §7.1), bases RAG autorizadas e ciclo draft → em_revisao →
 * publicada — harness VERDE (≥90 por dimensão) é o portão de release (A1). Publicar
 * NUNCA toca `os.frozen` (A2): campanha em voo segue com as versões congeladas no GO.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, EstadoVazio, TituloTela } from "../components/ui/basics";
import { get, post } from "../lib/api";
import { usePainelContextual } from "../lib/hooks";
import type { AgenteOut, DryRunOut, HarnessRunOut, SkillOut } from "../lib/types";

const ETAPA_ROTULO: Record<string, string> = {
  pedido: "Pedido",
  briefing: "Briefing",
  discovery: "Discovery",
  audiencia: "Audiência",
  criativos: "Criativos",
  jornada: "Jornada",
  twin: "Jornada",
  simulacao: "Ensaio",
  disparo: "Disparo",
  monitor: "Acompanhamento",
  monitoramento: "Acompanhamento",
  acompanhamento: "Acompanhamento",
  retro: "Acompanhamento",
  otimizacao: "Acompanhamento",
};

const CAMADA_CHIP: Record<string, string> = {
  maestro: "mchip-r",
  triagem: "mchip-w",
  especialista: "mchip-b",
};

function rotuloEtapa(etapa: string | null): string {
  if (!etapa) return "transversal";
  return ETAPA_ROTULO[etapa] ?? etapa;
}

function ChipHarness({ score, passou }: { score: number | null; passou?: boolean | null }) {
  if (score === null || score === undefined) return <span className="mchip-n">— sem run</span>;
  const ok = passou ?? score >= 90;
  return (
    <span className={ok ? "mchip-g" : "mchip-w"}>
      {score.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% {ok ? "✓" : "⚠"}
    </span>
  );
}

function UltimoRun({ run }: { run: HarnessRunOut }) {
  return (
    <div className="mfield block">
      <div className="flex items-center gap-2 text-[12px]">
        <ChipHarness score={run.score} passou={run.passou} />
        <span className="text-faint">
          {run.casos} caso(s) golden ·{" "}
          {run.created_at ? new Date(run.created_at).toLocaleString("pt-BR") : "—"}
        </span>
      </div>
      {run.score_por_dimensao && (
        <div className="mt-1 flex flex-wrap gap-1.5 text-[11px]">
          {Object.entries(run.score_por_dimensao).map(([dim, nota]) => (
            <span key={dim} className={nota >= 90 ? "mchip-g" : "mchip-r"}>
              {dim} {nota.toLocaleString("pt-BR", { maximumFractionDigits: 0 })}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function Atelie() {
  const queryClient = useQueryClient();
  const [etapaFiltro, setEtapaFiltro] = useState<string | null>(null);
  const [agenteSel, setAgenteSel] = useState<AgenteOut | null>(null);
  const [skillSelId, setSkillSelId] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState<DryRunOut | null>(null);

  const agentes = useQuery({
    queryKey: ["agentes"],
    queryFn: ({ signal }) => get<{ agentes: AgenteOut[] }>("/agentes", signal),
  });

  const skill = useQuery({
    queryKey: ["skills", skillSelId],
    queryFn: ({ signal }) => get<SkillOut>(`/skills/${skillSelId}`, signal),
    enabled: Boolean(skillSelId),
  });

  const invalidar = () => {
    void queryClient.invalidateQueries({ queryKey: ["agentes"] });
    void queryClient.invalidateQueries({ queryKey: ["skills", skillSelId] });
  };

  const rodarHarness = useMutation({
    mutationFn: (skillId: string) => post<HarnessRunOut>(`/skills/${skillId}/harness`),
    onSuccess: invalidar,
  });
  const enviarRevisao = useMutation({
    mutationFn: (skillId: string) => post<SkillOut>(`/skills/${skillId}/revisao`),
    onSuccess: invalidar,
  });
  const publicar = useMutation({
    mutationFn: (skillId: string) => post<SkillOut>(`/skills/${skillId}/publicar`),
    onSuccess: invalidar,
  });
  const rodarDryRun = useMutation({
    mutationFn: (skillId: string) =>
      post<DryRunOut>(`/skills/${skillId}/dry-run`, {
        entrada: { pedido: "campanha de upgrade 5G para pós-pago sem 5G" },
      }),
    onSuccess: setDryRun,
  });

  const lista = agentes.data?.agentes ?? [];
  const etapas = useMemo(
    () =>
      [...new Set(lista.map((a) => rotuloEtapa(a.etapa_workflow)))].sort((a, b) =>
        a.localeCompare(b, "pt-BR"),
      ),
    [lista],
  );
  const filtrados = etapaFiltro
    ? lista.filter((a) => rotuloEtapa(a.etapa_workflow) === etapaFiltro)
    : lista;

  const contagem = {
    especialistas: lista.filter((a) => a.camada === "especialista").length,
    triagens: lista.filter((a) => a.camada === "triagem").length,
    maestros: lista.filter((a) => a.camada === "maestro").length,
  };

  /** Corpo do SKILL.md sem o front-matter (o system prompt visível do mock T16). */
  const systemPrompt = useMemo(() => {
    const md = skill.data?.skill_md ?? "";
    const partes = md.split("---");
    return partes.length >= 3 ? partes.slice(2).join("---").trim() : md.trim();
  }, [skill.data?.skill_md]);

  usePainelContextual(
    <>
      <div className="ctx-title">Portão de release</div>
      <Copiloto titulo="Harness">
        Publicar skill exige harness <b>VERDE</b>: golden dataset (3 casos por
        agente-chave) julgado pelo judge 120b com rubrica fixa — score <b>≥ 90 por
        dimensão</b> (correção · evidência · compliance · formato), senão 409 (§8-M12-A1).
      </Copiloto>

      <div className="ctx-title">Congelamento (A2)</div>
      <div className="mfield">
        <span className="text-[12px]">
          Publicar skill nova <b>não toca OS em voo</b> — cada campanha congela as
          versões no GO (`os.frozen.agent_versions`) e segue com elas até o fim
        </span>
      </div>

      <div className="ctx-title">Guard</div>
      <div className="mfield">
        <span className="text-[12px]">
          O <b>guard</b> é determinístico (§7.2): código auditável, sem SKILL, sem LLM —
          elegibilidade de contato não se alucina
        </span>
      </div>

      <div className="ctx-title">RBAC</div>
      <div className="mfield">
        <span className="text-[12px]">
          Editar/harness/dry-run: analista+ · <b>publicar: líder</b> (portão de
          plataforma, segregação §10.5)
        </span>
      </div>
    </>,
    [],
  );

  return (
    <div>
      <TituloTela
        titulo={
          <>
            Ateliê de Agentes{" "}
            <span className="mchip-b align-middle">
              {contagem.especialistas} especialistas · {contagem.triagens} triagens ·{" "}
              {contagem.maestros || "1"} maestro
            </span>
          </>
        }
        subtitulo="Organizado por etapa do workflow · cada campanha congela as versões com que nasceu · refino no-code: editar → harness → publicar"
      />

      {agentes.error != null && <BannerErro erro={agentes.error} contexto="Roster" />}
      {rodarHarness.error != null && <BannerErro erro={rodarHarness.error} contexto="Harness" />}
      {enviarRevisao.error != null && (
        <BannerErro erro={enviarRevisao.error} contexto="Enviar para revisão" />
      )}
      {publicar.error != null && <BannerErro erro={publicar.error} contexto="Publicar skill" />}
      {rodarDryRun.error != null && <BannerErro erro={rodarDryRun.error} contexto="Dry-run" />}

      {/* ------------------------------------------------ filtro por etapa */}
      <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[11.5px]">
        <span className="font-bold uppercase tracking-[.06em] text-faint">Etapa:</span>
        <button
          type="button"
          className={etapaFiltro === null ? "mchip-b" : "mchip-n"}
          onClick={() => setEtapaFiltro(null)}
        >
          Todas
        </button>
        {etapas.map((etapa) => (
          <button
            key={etapa}
            type="button"
            className={etapaFiltro === etapa ? "mchip-b" : "mchip-n"}
            onClick={() => setEtapaFiltro(etapa === etapaFiltro ? null : etapa)}
          >
            {etapa}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-start gap-3">
        {/* --------------------------------------------------- catálogo */}
        <div className="mcard min-w-[380px] flex-[1.3] overflow-x-auto !p-0">
          {agentes.isLoading && (
            <div className="p-4 text-[12.5px] text-muted">Carregando roster…</div>
          )}
          {!agentes.isLoading && filtrados.length === 0 && (
            <div className="p-4">
              <EstadoVazio>Nenhum agente nesta etapa.</EstadoVazio>
            </div>
          )}
          {filtrados.length > 0 && (
            <table className="w-full text-left text-[12px]">
              <thead>
                <tr className="border-b border-line bg-surface2 text-[10px] uppercase tracking-[.06em] text-faint">
                  <th className="px-3 py-2">Agente</th>
                  <th className="px-3 py-2">Etapa</th>
                  <th className="px-3 py-2">Perfil</th>
                  <th className="px-3 py-2">Versão</th>
                  <th className="px-3 py-2">Harness</th>
                  <th className="px-3 py-2 text-right">Skills</th>
                </tr>
              </thead>
              <tbody>
                {filtrados.map((a) => {
                  const ultima = a.skills[a.skills.length - 1];
                  const selecionado = agenteSel?.id === a.id;
                  return (
                    <tr
                      key={a.id}
                      className={`cursor-pointer border-b border-linesoft transition-colors ${
                        selecionado ? "bg-blue-soft/60" : "hover:bg-surface2"
                      }`}
                      onClick={() => {
                        setAgenteSel(a);
                        setSkillSelId(a.skills[a.skills.length - 1]?.id ?? null);
                        setDryRun(null);
                      }}
                    >
                      <td className="px-3 py-2">
                        <b>{a.nome}</b>{" "}
                        <span className={CAMADA_CHIP[a.camada] ?? "mchip-n"}>{a.camada}</span>
                      </td>
                      <td className="px-3 py-2">
                        <span className="mchip-v">{rotuloEtapa(a.etapa_workflow)}</span>
                      </td>
                      <td className="px-3 py-2 font-mono text-[11px]">
                        {a.deterministico ? (
                          <span className="mchip-g">determinístico</span>
                        ) : (
                          (a.modelo_perfil ?? "—")
                        )}
                      </td>
                      <td className="px-3 py-2 font-mono text-[11px]">
                        {a.versao_publicada ? `v${a.versao_publicada}` : "—"}
                      </td>
                      <td className="px-3 py-2">
                        {a.deterministico ? (
                          <span className="mchip-g">100% (código)</span>
                        ) : (
                          <ChipHarness score={ultima?.harness_score ?? null} />
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">{a.skills.length}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* ----------------------------------------------- painel do agente */}
        <div className="min-w-[340px] flex-1">
          {!agenteSel && (
            <EstadoVazio>
              Selecione um agente do roster — o painel mostra a SKILL vinculada com o{" "}
              <b>system prompt visível</b>, bases RAG autorizadas e o histórico do harness.
            </EstadoVazio>
          )}
          {agenteSel && (
            <div className="mcard">
              <div className="flex items-center gap-2">
                <b className="text-[14px]">{agenteSel.nome}</b>
                {skill.data && <span className="mchip-n">v{skill.data.versao}</span>}
                {skill.data?.estado === "publicada" && <span className="mchip-g">publicada</span>}
                {skill.data?.estado === "em_revisao" && (
                  <span className="mchip-w">em revisão</span>
                )}
                {skill.data?.estado === "draft" && <span className="mchip-n">draft</span>}
              </div>

              {agenteSel.deterministico ? (
                <div className="mt-2 text-[12.5px] text-slatex">
                  <b>Não é LLM.</b> Guard determinístico (§7.2): valida as 7 listas de
                  exclusão e opt-in por canal em código auditável — o LLM no máximo{" "}
                  <i>explica</i> o veredito. Sem SKILL, sem harness, sem drift.
                </div>
              ) : (
                <>
                  <div className="mt-1.5 text-[12px] text-slatex">
                    Modelo: <b>{agenteSel.modelo_perfil ?? "—"}</b> (porta trocável §2.1) ·
                    etapa <b>{rotuloEtapa(agenteSel.etapa_workflow)}</b>
                    {skill.data && skill.data.bases_rag.length > 0 && (
                      <>
                        {" "}
                        · RAG:{" "}
                        {skill.data.bases_rag.map((base) => (
                          <span key={base} className="mchip-n mr-1">
                            {base.split("_").join(" ")}
                          </span>
                        ))}
                      </>
                    )}
                  </div>

                  {agenteSel.skills.length > 1 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {agenteSel.skills.map((s) => (
                        <button
                          key={s.id}
                          type="button"
                          className={s.id === skillSelId ? "mchip-b" : "mchip-n"}
                          onClick={() => setSkillSelId(s.id)}
                        >
                          v{s.versao} · {s.estado}
                        </button>
                      ))}
                    </div>
                  )}

                  <div className="ctx-title !mt-3">System prompt (visível — SKILL.md §7.1)</div>
                  {skill.isLoading ? (
                    <div className="text-[12px] text-muted">Carregando SKILL…</div>
                  ) : (
                    <pre className="max-h-44 overflow-auto rounded-lg bg-claro p-3 font-mono text-[11px] leading-relaxed text-claro-pale">
                      {systemPrompt || "— sem skill —"}
                    </pre>
                  )}

                  <div className="ctx-title !mt-3">Harness (portão de release — A1)</div>
                  {skill.data?.harness_runs.length ? (
                    <UltimoRun run={skill.data.harness_runs[skill.data.harness_runs.length - 1]} />
                  ) : (
                    <div className="text-[12px] text-muted">
                      Nenhum run — publicar exige harness verde sobre o texto ATUAL.
                    </div>
                  )}

                  <div className="mt-2 flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="mbtn !px-2.5 !py-1 !text-[11.5px]"
                      disabled={rodarHarness.isPending || !skillSelId}
                      title="Golden dataset + judge 120b (rubrica fixa §7.1) — 503 degraded com hub fora"
                      onClick={() => skillSelId && rodarHarness.mutate(skillSelId)}
                    >
                      {rodarHarness.isPending ? "Julgando…" : "▶ Rodar harness"}
                    </button>
                    {skill.data?.estado === "draft" && (
                      <button
                        type="button"
                        className="mbtn-gh !px-2.5 !py-1 !text-[11.5px]"
                        disabled={enviarRevisao.isPending || !skillSelId}
                        onClick={() => skillSelId && enviarRevisao.mutate(skillSelId)}
                      >
                        Enviar p/ revisão
                      </button>
                    )}
                    {skill.data?.estado === "em_revisao" && (
                      <button
                        type="button"
                        className="mbtn-gd !px-2.5 !py-1 !text-[11.5px]"
                        disabled={publicar.isPending || !skillSelId}
                        title="Exige harness verde + papel líder (RBAC §8-M0)"
                        onClick={() => skillSelId && publicar.mutate(skillSelId)}
                      >
                        Publicar
                      </button>
                    )}
                    <button
                      type="button"
                      className="mbtn-gh !px-2.5 !py-1 !text-[11.5px]"
                      disabled={rodarDryRun.isPending || !skillSelId}
                      title="Mesma entrada na versão publicada atual e na candidata — nada persiste"
                      onClick={() => skillSelId && rodarDryRun.mutate(skillSelId)}
                    >
                      {rodarDryRun.isPending ? "Comparando…" : "Dry-run lado a lado"}
                    </button>
                  </div>

                  {dryRun && (
                    <div className="mt-2 grid gap-1.5">
                      {dryRun.avisos.map((aviso, i) => (
                        <div key={i} className="text-[11.5px] text-warn">
                          {aviso}
                        </div>
                      ))}
                      <div className="flex flex-wrap gap-2">
                        {(["atual", "candidata"] as const).map((lado) => {
                          const resultado = dryRun[lado];
                          return (
                            <div key={lado} className="mfield block min-w-[45%] flex-1">
                              <div className="text-[10px] font-bold uppercase tracking-[.08em] text-faint">
                                {lado} {resultado ? `· v${resultado.versao}` : ""}
                              </div>
                              <div className="mt-0.5 max-h-28 overflow-auto text-[11.5px] text-slatex">
                                {resultado?.saida ?? "— sem versão publicada anterior —"}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
