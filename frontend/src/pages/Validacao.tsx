/**
 * T3 · Validação de Prontidão — campo a campo (mock T3): cada campo do briefing é
 * checado automaticamente contra a fonte (POST /os/{id}/validacoes/{campo} → checagens
 * + evidência) com duas ações por campo: Validar ou Abrir pendência (bloqueante trava
 * o GO). Painel direito mostra a evidência da verificação selecionada.
 *
 * A9 (UAT): "Abrir pendência" NÃO dispara mais o POST em 1 clique cego — abre um
 * diálogo modal que coleta título (obrigatório, prefill citando o campo), descrição
 * (opcional) e severidade (default `media`) antes de enviar. Esc/clique-fora cancelam.
 *
 * B01 (UAT #2): a tela NÃO guarda mais o estado na sessão — hidrata no mount de
 * `GET /os/{id}/validacoes` e `GET /os/{id}/pendencias`. Antes, reload ou restart do
 * container zeravam a tela embora o dado estivesse no Postgres, e o usuário revalidava
 * às cegas. As mutações apenas invalidam as queries: o servidor é a fonte da verdade.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, BarraProgresso, EstadoVazio, TituloTela } from "../components/ui/basics";
import { post } from "../lib/api";
import {
  useBriefing,
  useFecharForaEsc,
  usePainelContextual,
  usePendencias,
  useValidacoes,
} from "../lib/hooks";
import {
  campoBriefing,
  valorLegivel,
  type PendenciaOut,
  type ValidacaoOut,
} from "../lib/types";

type Severidade = "baixa" | "media" | "alta";

/** Âncora da pendência no campo (`pendencia.origem` — §8-M4). */
const ORIGEM = (campo: string) => `validacao:${campo}`;

const CHIP_SEVERIDADE: Record<string, string> = {
  alta: "mchip-r",
  media: "mchip-w",
  baixa: "mchip-n",
};

/**
 * Espelho EXATO da regra do portão GO (`domain/validacao/regras.campo_decidido`):
 * campo decidido ⇔ última validação `ok` OU tratamento consciente (há pendência
 * ancorada no campo e nenhuma segue aberta). O contador da tela precisa contar o
 * mesmo que o backend recusa — senão promete um GO que o 409 nega (§1.3.5).
 */
function campoDecidido(
  validacao: ValidacaoOut | undefined,
  ancoradas: PendenciaOut[],
): boolean {
  if (validacao?.veredito === "ok") return true;
  return ancoradas.length > 0 && ancoradas.every((p) => p.status !== "aberta");
}

/** Quem/quando da decisão vigente (emenda B01) — sobrevive ao reload, então é exibível. */
function autoria(v: ValidacaoOut): string {
  const quando = v.atualizado_em ?? v.created_at;
  const carimbo = new Date(quando).toLocaleString("pt-BR");
  return v.por ? `${v.por} · ${carimbo}` : carimbo;
}

/** Payload do diálogo (A9) — vira o corpo do POST .../pendencia. */
interface DadosPendencia {
  campo: string;
  titulo: string;
  descricao: string;
  severidade: Severidade;
}

const SEVERIDADES: { valor: Severidade; rotulo: string }[] = [
  { valor: "baixa", rotulo: "Baixa" },
  { valor: "media", rotulo: "Média" },
  { valor: "alta", rotulo: "Alta" },
];

/** Título sugerido — cita o campo para a pendência nascer com contexto (A9). */
const tituloSugerido = (campo: string) => `Validar ${campo} com o dono do dado`;

/**
 * Diálogo modal de abertura de pendência (A9). Fecha com Esc ou clique fora do painel
 * via `useFecharForaEsc` (o ref vai no painel — o backdrop conta como "fora").
 * Remontado a cada campo (`key={campo}` no chamador) para o prefill acompanhar a linha.
 */
function DialogoPendencia({
  campo,
  enviando,
  onCancelar,
  onEnviar,
}: {
  campo: string;
  enviando: boolean;
  onCancelar: () => void;
  onEnviar: (dados: DadosPendencia) => void;
}) {
  const [titulo, setTitulo] = useState(() => tituloSugerido(campo));
  const [descricao, setDescricao] = useState("");
  const [severidade, setSeveridade] = useState<Severidade>("media");
  const painel = useFecharForaEsc(true, onCancelar);
  const valido = titulo.trim().length > 0;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-ink/40 p-4">
      <div
        ref={painel}
        role="dialog"
        aria-modal="true"
        aria-label={`Abrir pendência no campo ${campo}`}
        className="w-[min(520px,100%)] rounded-2xl border border-line bg-white p-5 shadow-card"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-[16px] font-bold text-ink2">Abrir pendência</h2>
            <p className="mt-0.5 text-[12px] text-muted">
              Ancorada no campo <b className="break-words">{campo}</b> · bloqueante — trava o
              GO até resolução ou aceite do Accountable.
            </p>
          </div>
          <button
            type="button"
            onClick={onCancelar}
            aria-label="Cancelar"
            className="grid h-7 w-7 flex-none place-items-center rounded-md text-[16px] text-muted hover:bg-surface2 hover:text-ink"
          >
            ×
          </button>
        </div>

        <form
          className="mt-4"
          onSubmit={(ev) => {
            ev.preventDefault();
            if (!valido || enviando) return;
            onEnviar({ campo, titulo: titulo.trim(), descricao: descricao.trim(), severidade });
          }}
        >
          <label className="block text-[11px] font-bold uppercase tracking-[.06em] text-faint">
            Título <span className="text-crit">*</span>
          </label>
          <input
            autoFocus
            value={titulo}
            onChange={(ev) => setTitulo(ev.target.value)}
            placeholder={tituloSugerido(campo)}
            className="mt-1 w-full rounded-md border border-line px-3 py-2 text-[13px] outline-none focus:border-blue"
          />

          <label className="mt-3 block text-[11px] font-bold uppercase tracking-[.06em] text-faint">
            Descrição <span className="font-normal normal-case tracking-normal">(opcional)</span>
          </label>
          <textarea
            value={descricao}
            onChange={(ev) => setDescricao(ev.target.value)}
            rows={3}
            placeholder="O que precisa ser checado, com quem, e o que destrava."
            className="mt-1 w-full resize-y rounded-md border border-line px-3 py-2 text-[13px] leading-snug outline-none focus:border-blue"
          />

          <label className="mt-3 block text-[11px] font-bold uppercase tracking-[.06em] text-faint">
            Severidade
          </label>
          <select
            value={severidade}
            onChange={(ev) => setSeveridade(ev.target.value as Severidade)}
            className="mt-1 rounded-md border border-line bg-white px-2 py-2 text-[13px] outline-none focus:border-blue"
          >
            {SEVERIDADES.map((s) => (
              <option key={s.valor} value={s.valor}>
                {s.rotulo}
              </option>
            ))}
          </select>

          <div className="mt-5 flex items-center justify-end gap-2">
            <button type="button" className="mbtn-gh" onClick={onCancelar}>
              Cancelar
            </button>
            <button type="submit" className="mbtn" disabled={!valido || enviando}>
              {enviando ? "Abrindo…" : "Abrir pendência"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export function Validacao() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: briefing, error: erroBriefing } = useBriefing(id);
  // B01: estado vem do servidor (não da sessão) — reload/restart não zeram a tela
  const { data: validacoes, error: erroValidacoes } = useValidacoes(id);
  const { data: pendencias, error: erroPendencias } = usePendencias(id);

  const [selecionado, setSelecionado] = useState<string | null>(null);
  // A9: campo cujo diálogo de pendência está aberto (null = fechado)
  const [campoDialogo, setCampoDialogo] = useState<string | null>(null);
  const fecharDialogo = useCallback(() => setCampoDialogo(null), []);

  const campos = useMemo(() => Object.entries(briefing?.briefing ?? {}), [briefing]);

  /** Decisão vigente por campo (o backend garante uma por campo — emenda B01). */
  const resultados = useMemo(() => {
    const mapa: Record<string, ValidacaoOut> = {};
    for (const v of validacoes ?? []) mapa[v.campo] = v;
    return mapa;
  }, [validacoes]);

  /** Pendências ancoradas, agrupadas pelo campo da `origem` (`validacao:{campo}`). */
  const ancoradas = useMemo(() => {
    const mapa: Record<string, PendenciaOut[]> = {};
    for (const [campo] of campos) {
      mapa[campo] = (pendencias ?? []).filter((p) => p.origem === ORIGEM(campo));
    }
    return mapa;
  }, [pendencias, campos]);

  /** Tudo que ainda bloqueia o GO — inclusive pendência do War Room, sem âncora. */
  const abertas = useMemo(
    () => (pendencias ?? []).filter((p) => p.status === "aberta"),
    [pendencias],
  );

  const decididos = campos.filter(([campo]) =>
    campoDecidido(resultados[campo], ancoradas[campo] ?? []),
  ).length;
  const pct = campos.length > 0 ? (100 * decididos) / campos.length : 0;

  /** Toda mutação re-hidrata as leituras da OS (validações, pendências e saúde). */
  const recarregar = useCallback(
    () => void queryClient.invalidateQueries({ queryKey: ["os", id] }),
    [queryClient, id],
  );

  const validar = useMutation({
    mutationFn: (campo: string) =>
      post<ValidacaoOut>(`/os/${id}/validacoes/${encodeURIComponent(campo)}`),
    onSuccess: (v) => {
      setSelecionado(v.campo);
      recarregar(); // idempotente no servidor: revalidar atualiza a linha, não duplica
    },
  });

  // A9: o POST leva o contexto coletado no diálogo (título/descrição/severidade).
  const abrirPendencia = useMutation({
    mutationFn: (dados: DadosPendencia) =>
      post<PendenciaOut>(
        `/os/${id}/validacoes/${encodeURIComponent(dados.campo)}/pendencia`,
        {
          titulo: dados.titulo,
          descricao: dados.descricao || null,
          severidade: dados.severidade,
        },
      ),
    onSuccess: (_p, dados) => {
      setSelecionado(dados.campo);
      setCampoDialogo(null);
      recarregar();
    },
  });

  const validacaoSelecionada = selecionado ? resultados[selecionado] : undefined;
  // a aberta é a que importa (ainda trava o GO); sem aberta, mostra a que tratou o campo
  const doSelecionado = selecionado ? (ancoradas[selecionado] ?? []) : [];
  const pendenciaSelecionada =
    doSelecionado.find((p) => p.status === "aberta") ?? doSelecionado[0];

  usePainelContextual(
    <>
      <div className="ctx-title">Verificação selecionada</div>
      {validacaoSelecionada ? (
        <>
          <div className="mfield">
            <span className="min-w-0">
              <span className="block text-[12px] font-bold">
                {validacaoSelecionada.campo} —{" "}
                {validacaoSelecionada.veredito === "ok" ? "validado" : "falha"}
              </span>
              {validacaoSelecionada.checagens.map((c, i) => (
                <span key={i} className="block text-[11.5px] text-slatex">
                  {c.ok ? "✓" : "✗"} <b>{c.tipo}</b>: {c.detalhe}
                </span>
              ))}
              {/* B01: quem/quando da decisão vigente — auditoria que sobrevive ao reload */}
              <span className="mt-1 block text-[11px] text-faint">
                checado por {autoria(validacaoSelecionada)}
              </span>
            </span>
          </div>
          <div className="mfield block">
            <span className="block text-[12px] font-bold">Evidência</span>
            <pre className="mt-1 max-h-48 overflow-auto rounded bg-surface2 p-2 font-mono text-[10px] leading-snug text-steel">
              {JSON.stringify(validacaoSelecionada.evidencia, null, 2)}
            </pre>
          </div>
        </>
      ) : pendenciaSelecionada ? (
        <div className="mfield">
          <span>
            <span className="block text-[12px] font-bold">
              Pendência #{pendenciaSelecionada.numero} · {pendenciaSelecionada.titulo}
            </span>
            <span className="block text-[11.5px] text-slatex">
              {pendenciaSelecionada.bloqueante
                ? "Bloqueante — trava o GO até resolução ou aceite do Accountable."
                : "Não bloqueante."}
            </span>
          </span>
          <span
            className={
              pendenciaSelecionada.status === "aberta"
                ? (CHIP_SEVERIDADE[pendenciaSelecionada.severidade ?? ""] ?? "mchip-r")
                : "mchip-g"
            }
          >
            {pendenciaSelecionada.status}
          </span>
        </div>
      ) : (
        <div className="text-[12px] text-muted">
          Valide um campo para ver checagens e evidência aqui.
        </div>
      )}
      <div className="ctx-title">Copiloto</div>
      <Copiloto titulo="Auditora de viabilidade">
        Cada campo é checado contra a fonte real (contagem, schema, frescor) — a checagem
        é determinística; a IA só redige a pendência e sugere resolução.
      </Copiloto>
    </>,
    [validacaoSelecionada, pendenciaSelecionada],
  );

  return (
    <div>
      <TituloTela
        titulo="Validação de Prontidão"
        subtitulo={
          <>
            <b>{decididos}</b> de <b>{campos.length}</b> campos decididos — decida todos
            para liberar o GO (T4).
          </>
        }
      />
      {erroBriefing != null && <BannerErro erro={erroBriefing} contexto="Briefing" />}
      {erroValidacoes != null && <BannerErro erro={erroValidacoes} contexto="Validações" />}
      {erroPendencias != null && <BannerErro erro={erroPendencias} contexto="Pendências" />}
      {validar.error != null && <BannerErro erro={validar.error} contexto="Validação" />}
      {abrirPendencia.error != null && (
        <BannerErro erro={abrirPendencia.error} contexto="Pendência" />
      )}

      <BarraProgresso pct={pct} tom={pct === 100 ? "good" : "blue"} />

      {/* B01: o que ainda trava o GO, recuperado do servidor (some ao resolver/aceitar) */}
      {abertas.length > 0 && (
        <div className="mcard mt-3 border-warn-line bg-warn-bg">
          <div className="mb-2 text-[10px] font-bold uppercase tracking-[.06em] text-warn">
            {abertas.length} pendência(s) aberta(s) — travam o GO até resolução ou aceite
          </div>
          {abertas.map((p) => (
            <div key={p.id} className="mfield bg-white">
              <span className="min-w-0">
                <span className="block text-[12.5px] font-bold">
                  #{p.numero} · {p.titulo}
                </span>
                <span className="block break-words text-[11.5px] text-slatex">
                  {p.origem?.startsWith("validacao:")
                    ? `ancorada no campo ${p.origem.slice("validacao:".length)}`
                    : "aberta no War Room (T4)"}
                  {p.bloqueante ? " · bloqueante" : " · não bloqueante"}
                  {p.accountable != null && " · com accountable definido"}
                </span>
              </span>
              <span className={CHIP_SEVERIDADE[p.severidade ?? ""] ?? "mchip-n"}>
                {p.severidade ?? "sem severidade"}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="mt-3">
        {campos.length === 0 && (
          <EstadoVazio>Briefing vazio — estruture-o na Sala de Ideação (T2).</EstadoVazio>
        )}
        {campos.map(([campo, entrada]) => {
          const e = campoBriefing(entrada);
          const resultado = resultados[campo];
          const doCampo = ancoradas[campo] ?? [];
          const pendenciaAberta = doCampo.find((p) => p.status === "aberta");
          // já tratada = pendência ancorada existe e nenhuma segue aberta (decide o campo)
          const tratada = doCampo.length > 0 && pendenciaAberta === undefined;
          const decidido = campoDecidido(resultado, doCampo);
          // A10 (UAT): estado de envio POR LINHA — `variables` é o campo da linha
          // clicada, então cada botão reflete (e dispara) somente o próprio campo.
          const validando = validar.isPending && validar.variables === campo;
          const abrindo = abrirPendencia.isPending && abrirPendencia.variables?.campo === campo;
          return (
            <div
              key={campo}
              className={`mfield cursor-pointer ${
                pendenciaAberta
                  ? "border-warn-line bg-warn-bg"
                  : selecionado === campo
                    ? "border-blue"
                    : ""
              }`}
              onClick={() => setSelecionado(campo)}
            >
              <span className="min-w-0">
                <span className="block text-[12.5px] font-bold">
                  {campo}{" "}
                  {resultado &&
                    (resultado.veredito === "ok" ? (
                      <span className="mchip-g">validado</span>
                    ) : (
                      <span className="mchip-r">falha</span>
                    ))}
                  {pendenciaAberta && (
                    <span className={CHIP_SEVERIDADE[pendenciaAberta.severidade ?? ""] ?? "mchip-r"}>
                      Pendência #{pendenciaAberta.numero} aberta
                      {pendenciaAberta.severidade && ` · ${pendenciaAberta.severidade}`}
                    </span>
                  )}
                  {tratada && <span className="mchip-g">pendência tratada</span>}
                  {!decidido && !pendenciaAberta && <span className="mchip-w">pendente</span>}
                </span>
                <span className="block break-words text-[11.5px] leading-snug text-slatex">
                  {valorLegivel(e.valor)}
                  {resultado && (
                    <>
                      {" · "}
                      {resultado.checagens.map((c) => `${c.ok ? "✓" : "✗"} ${c.tipo}`).join(" · ")}
                      {" · "}
                      {autoria(resultado)}
                    </>
                  )}
                </span>
              </span>
              <span className="flex flex-none items-center gap-1.5">
                <button
                  type="button"
                  className="mbtn !px-2.5 !py-1 !text-[11px]"
                  disabled={validando}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    validar.mutate(campo);
                  }}
                >
                  {/* B01: revalidar é idempotente no servidor — atualiza, não duplica */}
                  {validando ? "Validando…" : resultado ? "Revalidar" : "Validar"}
                </button>
                <button
                  type="button"
                  className="mbtn-gh !px-2.5 !py-1 !text-[11px]"
                  disabled={abrindo || Boolean(pendenciaAberta)}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    setSelecionado(campo);
                    setCampoDialogo(campo); // A9: coleta contexto antes do POST
                  }}
                >
                  {abrindo ? "Abrindo…" : "Abrir pendência…"}
                </button>
              </span>
            </div>
          );
        })}
      </div>

      {campoDialogo !== null && (
        <DialogoPendencia
          key={campoDialogo}
          campo={campoDialogo}
          enviando={abrirPendencia.isPending}
          onCancelar={fecharDialogo}
          onEnviar={(dados) => abrirPendencia.mutate(dados)}
        />
      )}
    </div>
  );
}
