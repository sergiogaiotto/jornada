/**
 * T9 · QA de Governança (mock T9 / SDD §8-M8): os 4 QAs bloqueantes antes do
 * pacote ir ao cliente — Certificado LGPD (Guard determinístico), experimento
 * pré-registrado (poder/n mínimo, anti-peeking), custo & alçada (faixas da política;
 * variação >10% re-dispara) e Contact Governor (colisão/pressão). Fecha com o
 * snapshot imutável (hash composto) + link mágico (T10). Quem cria não aprova.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, TituloTela } from "../components/ui/basics";
import { get, post } from "../lib/api";
import { fmtBRL, fmtInt } from "../lib/format";
import { usePainelContextual } from "../lib/hooks";
import type {
  AlcadaOut,
  EstadoPortao,
  ExperimentoPreRegistradoOut,
  LinkMagicoOut,
  PortaoOut,
  PortoesOut,
  SnapshotOut,
} from "../lib/types";
import { useProducao } from "../stores/producao";

const CHIP: Record<EstadoPortao, string> = {
  verde: "mchip-g",
  vermelho: "mchip-r",
  pendente: "mchip-w",
};

const ESTADO_ROTULO: Record<EstadoPortao, string> = {
  verde: "verde",
  vermelho: "vermelho",
  pendente: "pendente",
};

function CardPortao({
  icone,
  titulo,
  portao,
  children,
}: {
  icone: string;
  titulo: string;
  portao: PortaoOut;
  children?: ReactNode;
}) {
  return (
    <div className="mcard min-w-[300px] flex-1">
      <div className="flex items-center justify-between gap-2 text-[12px] font-bold">
        <span>
          {icone} {titulo}
        </span>
        <span className={CHIP[portao.estado]}>{ESTADO_ROTULO[portao.estado]}</span>
      </div>
      {portao.motivo != null && (
        <div className="mt-1 text-[11.5px] text-warn">{String(portao.motivo)}</div>
      )}
      <div className="mt-1.5 text-[12px] text-slatex">{children}</div>
    </div>
  );
}

export function Portoes() {
  const { id } = useParams<{ id: string }>();
  const osId = id ?? "";
  const queryClient = useQueryClient();

  const snapshot = useProducao((s) => s.snapshots[osId]);
  const linkMagico = useProducao((s) => s.linksMagicos[osId]);
  const setSnapshot = useProducao((s) => s.setSnapshot);
  const setLinkMagico = useProducao((s) => s.setLinkMagico);

  const [mde, setMde] = useState(1.8);
  const [janela, setJanela] = useState(15);
  const [holdout, setHoldout] = useState(10);

  const portoesQ = useQuery({
    queryKey: ["os", osId, "portoes"],
    queryFn: ({ signal }) => get<PortoesOut>(`/os/${osId}/portoes`, signal),
    enabled: Boolean(osId),
  });

  const recarregar = () =>
    queryClient.invalidateQueries({ queryKey: ["os", osId, "portoes"] });

  const preRegistrar = useMutation({
    mutationFn: () =>
      post<ExperimentoPreRegistradoOut>("/experimentos", {
        os_id: osId,
        mde_pp: mde,
        janela_dias: janela,
        holdout_pct: holdout,
      }),
    onSuccess: recarregar,
  });

  const enviarAlcada = useMutation({
    mutationFn: () => post<AlcadaOut>(`/os/${osId}/custo/enviar-alcada`),
    onSuccess: recarregar,
  });

  const criarSnapshot = useMutation({
    mutationFn: () => post<SnapshotOut>("/snapshots", { os_id: osId }),
    onSuccess: (s) => {
      setSnapshot(osId, s);
      recarregar();
    },
  });

  const criarLink = useMutation({
    mutationFn: (snapshotId: string) =>
      post<LinkMagicoOut>(`/snapshots/${snapshotId}/link-magico`),
    onSuccess: (l) => {
      setLinkMagico(osId, l);
      recarregar();
    },
  });

  const dados = portoesQ.data;
  const portoes = dados?.portoes;
  const aprovacao = dados?.aprovacao;
  const verdes = portoes
    ? Object.values(portoes).filter((p) => p.estado === "verde").length
    : 0;

  usePainelContextual(
    <>
      <div className="ctx-title">Segregação de funções</div>
      <div className="mfield">
        <span className="text-[12px]">
          Criador (R) · aprovador interno (alçada) · aprovador final (cliente, link
          mágico) — <b>papéis distintos obrigatórios</b>, checados server-side (§10.5).
        </span>
      </div>

      <div className="ctx-title">Link mágico (T10)</div>
      {linkMagico ? (
        <div className="mfield block">
          <span className="block text-[11.5px] text-slatex">
            Alçada <b>{linkMagico.alcada}</b> · expira{" "}
            {new Date(linkMagico.expira_em).toLocaleString("pt-BR")}
          </span>
          <span className="mt-1 block break-all rounded-md bg-surface2 px-2 py-1 font-mono text-[10.5px] text-steel">
            {linkMagico.url}
          </span>
          <span className="mt-1 block text-[10.5px] text-faint">
            Token exibido UMA única vez (§8-M8-A3) — só o sha256 persiste no servidor.
          </span>
        </div>
      ) : (
        <div className="text-[12px] text-muted">
          Monte o snapshot e gere o link — o aprovador decide sem login.
        </div>
      )}

      <div className="ctx-title">Documento do QA</div>
      <Copiloto titulo="Doc">
        Documento executivo do QA: inputs, certificado, experimento, custo e
        prontidão — gerado a cada QA e arquivado no dossiê da OS (.docx).
      </Copiloto>
    </>,
    [linkMagico],
  );

  return (
    <div>
      <TituloTela
        titulo="QA de Governança"
        subtitulo={
          portoes
            ? `${verdes} de 4 verdes — QAs bloqueantes, não avisos (vermelho bloqueia a materialização)`
            : "Certificado LGPD · experimento · custo/alçada · Contact Governor"
        }
      />

      {portoesQ.error != null && <BannerErro erro={portoesQ.error} contexto="QA" />}
      {preRegistrar.error != null && (
        <BannerErro erro={preRegistrar.error} contexto="Pré-registro do experimento" />
      )}
      {enviarAlcada.error != null && (
        <BannerErro erro={enviarAlcada.error} contexto="Alçada de custo" />
      )}
      {criarSnapshot.error != null && (
        <BannerErro erro={criarSnapshot.error} contexto="Snapshot" />
      )}
      {criarLink.error != null && <BannerErro erro={criarLink.error} contexto="Link mágico" />}

      {portoesQ.isLoading && (
        <div className="mcard py-6 text-center text-[13px] text-muted">Carregando QAs…</div>
      )}

      {portoes && (
        <>
          <div className="mb-3 flex flex-wrap gap-3">
            {/* ------------------------------------------- certificado LGPD */}
            <CardPortao icone="🛡" titulo="Certificado de Elegibilidade" portao={portoes.certificado}>
              {portoes.certificado.estado === "verde" ? (
                <>
                  Líquido <b>{fmtInt(portoes.certificado["liquido"] as number)}</b> · hash{" "}
                  <span className="font-mono">
                    {String(portoes.certificado["hash"]).slice(0, 12)}…
                  </span>{" "}
                  · válido até{" "}
                  <b>
                    {portoes.certificado["valido_ate"]
                      ? new Date(String(portoes.certificado["valido_ate"])).toLocaleString(
                          "pt-BR",
                        )
                      : "—"}
                  </b>
                  <span className="mt-1 block text-good">
                    Veredito por código auditável (Guard) — LLM só explica ✓ · cláusula:
                    re-varredura last-mile no disparo
                  </span>
                </>
              ) : (
                <>
                  Emitido pelo Guard determinístico na{" "}
                  <Link
                    to={`/os/${osId}/audiencia`}
                    className="font-semibold text-blue underline"
                  >
                    Audiência (T5)
                  </Link>{" "}
                  — varredura das 7 listas + opt-in por canal.
                </>
              )}
            </CardPortao>

            {/* ---------------------------------------------- experimento */}
            <CardPortao icone="🧪" titulo="Experimento pré-registrado" portao={portoes.experimento}>
              {portoes.experimento.estado === "pendente" &&
              portoes.experimento["n_minimo"] == null ? (
                <div className="flex flex-wrap items-end gap-2">
                  {(
                    [
                      ["MDE (pp)", mde, setMde, 0.1],
                      ["Janela (dias)", janela, setJanela, 1],
                      ["Holdout %", holdout, setHoldout, 1],
                    ] as const
                  ).map(([rotulo, valor, setter, step]) => (
                    <label key={rotulo} className="text-[10.5px] font-semibold text-slatex">
                      {rotulo}
                      <input
                        type="number"
                        step={step}
                        value={valor}
                        onChange={(e) => setter(Number(e.target.value))}
                        className="mt-0.5 block w-20 rounded-md border border-line2 px-2 py-1 text-[12px] tabular-nums outline-none focus:border-blue"
                      />
                    </label>
                  ))}
                  <button
                    type="button"
                    className="mbtn !px-2.5 !py-1 !text-[11px]"
                    disabled={preRegistrar.isPending}
                    onClick={() => preRegistrar.mutate()}
                  >
                    {preRegistrar.isPending ? "Registrando…" : "Pré-registrar"}
                  </button>
                  <span className="block w-full text-[10.5px] text-faint">
                    n mínimo calculado no servidor (poder 0,80 · α 0,05) · nasce travado —
                    anti-peeking (M11 recusa apuração antes da janela)
                  </span>
                </div>
              ) : (
                <>
                  n mínimo <b>{fmtInt(portoes.experimento["n_minimo"] as number | null)}</b>
                  {portoes.experimento["n_disponivel"] != null && (
                    <>
                      {" "}
                      · disponível{" "}
                      <b>{fmtInt(portoes.experimento["n_disponivel"] as number)}</b>
                    </>
                  )}
                  {portoes.experimento["poder"] != null && (
                    <>
                      {" "}
                      · poder{" "}
                      <b>{((portoes.experimento["poder"] as number) * 100).toFixed(0)}%</b>
                    </>
                  )}
                  <span className="mt-1 block text-faint">
                    janela travada · métricas primárias registradas · anti-peeking ativo
                  </span>
                </>
              )}
            </CardPortao>
          </div>

          <div className="mb-3 flex flex-wrap gap-3">
            {/* -------------------------------------------- custo & alçada */}
            <CardPortao icone="💰" titulo="Custo & Alçada" portao={portoes.custo_alcada}>
              {portoes.custo_alcada["custo_previsto"] != null && (
                <>
                  Estimativa (P50 do Ensaio):{" "}
                  <b>{fmtBRL(portoes.custo_alcada["custo_previsto"] as number)}</b>
                  {portoes.custo_alcada["faixa"] != null && (
                    <>
                      {" "}
                      · faixa: até{" "}
                      {fmtBRL((portoes.custo_alcada["faixa"] as { ate: number }).ate, 0)} →{" "}
                      <b>{(portoes.custo_alcada["faixa"] as { papel: string }).papel}</b>
                    </>
                  )}
                  <span className="mt-1 block text-faint">
                    re-aprovação automática se variação &gt; 10% (§8-M8-A4) · burn-rate
                    monitorado pós-disparo (T12)
                  </span>
                </>
              )}
              {portoes.custo_alcada.estado === "pendente" &&
                portoes.custo_alcada["custo_previsto"] != null && (
                  <button
                    type="button"
                    className="mbtn mt-2 !px-2.5 !py-1 !text-[11px]"
                    disabled={enviarAlcada.isPending}
                    onClick={() => enviarAlcada.mutate()}
                  >
                    {enviarAlcada.isPending ? "Enviando…" : "Enviar à alçada"}
                  </button>
                )}
            </CardPortao>

            {/* ------------------------------------------ contact governor */}
            <CardPortao icone="🚦" titulo="Contact Governor" portao={portoes.governor}>
              {portoes.governor.estado === "verde" ? (
                <>
                  Sem colisão crítica — pressão de contato dentro do cap da política ·
                  quiet hours aplicadas no grafo · precedência: retenção &gt; regulatório
                  &gt; <b>upsell</b> &gt; pesquisa
                </>
              ) : (
                <>Veredito vem da pressão de contato da última simulação (T8).</>
              )}
              {Boolean(portoes.governor["stub"]) && (
                <span className="mchip-n ml-1">árbitro pleno no M10</span>
              )}
            </CardPortao>
          </div>

          {/* ------------------------------------------ aprovação (snapshot) */}
          {aprovacao && (
            <div className="mcard border-blue/30">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-[12px] font-bold">
                  📦 Aprovação do cliente (snapshot imutável){" "}
                  <span className={CHIP[aprovacao.estado]}>{ESTADO_ROTULO[aprovacao.estado]}</span>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="mbtn-gh !px-2.5 !py-1 !text-[11px]"
                    disabled={criarSnapshot.isPending}
                    title="Hash composto sha256 de JGC+SQL+criativos+política+custo+experimento (§4.1)"
                    onClick={() => criarSnapshot.mutate()}
                  >
                    {criarSnapshot.isPending ? "Montando…" : "Montar snapshot"}
                  </button>
                  <button
                    type="button"
                    className="mbtn !px-2.5 !py-1 !text-[11px]"
                    disabled={
                      criarLink.isPending ||
                      (snapshot?.id ?? aprovacao["snapshot_id"]) == null
                    }
                    onClick={() =>
                      criarLink.mutate(String(snapshot?.id ?? aprovacao["snapshot_id"]))
                    }
                  >
                    {criarLink.isPending ? "Gerando…" : "Gerar link mágico"}
                  </button>
                </div>
              </div>
              <div className="mt-1.5 text-[12px] text-slatex">
                {aprovacao["snapshot_hash"] != null && (
                  <>
                    snapshot{" "}
                    <span className="font-mono">
                      {String(aprovacao["snapshot_hash"]).slice(0, 12)}…
                    </span>{" "}
                    — o hash garante que o aprovado é exatamente o que será publicado ·{" "}
                  </>
                )}
                {aprovacao.motivo != null && <span>{String(aprovacao.motivo)}</span>}
                {aprovacao["decisao"] != null && (
                  <b> decisão: {String(aprovacao["decisao"])}</b>
                )}
              </div>
              {linkMagico && (
                <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md bg-surface2 px-3 py-2 text-[12px]">
                  <span className="mchip-b">link mágico</span>
                  <Link
                    to={`/aprovacao/${linkMagico.token}`}
                    className="break-all font-mono text-[11px] font-semibold text-blue underline"
                  >
                    /aprovacao/{linkMagico.token.slice(0, 18)}…
                  </Link>
                  <span className="text-[11px] text-faint">
                    uso único · expira {new Date(linkMagico.expira_em).toLocaleString("pt-BR")} ·
                    registra ip/device · SLA pausado com o cliente
                  </span>
                </div>
              )}
              <div className="mt-1.5 text-[11px] text-faint">
                Próxima fase:{" "}
                <Link to={`/os/${osId}/prevoo`} className="font-semibold text-blue underline">
                  Compilação & Pré-voo (T11)
                </Link>{" "}
                — apply em prod exige aprovação + certificado válido + pré-voo verde (§5.4.4).
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
