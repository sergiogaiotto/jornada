/**
 * T3 · Validação de Prontidão — campo a campo (mock T3): cada campo do briefing é
 * checado automaticamente contra a fonte (POST /os/{id}/validacoes/{campo} → checagens
 * + evidência) com duas ações por campo: Validar ou Abrir pendência (bloqueante trava
 * o GO). Painel direito mostra a evidência da verificação selecionada.
 *
 * A9 (UAT): "Abrir pendência" NÃO dispara mais o POST em 1 clique cego — abre um
 * diálogo modal que coleta título (obrigatório, prefill citando o campo), descrição
 * (opcional) e severidade (default `media`) antes de enviar. Esc/clique-fora cancelam.
 */
import { useMutation } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { Copiloto } from "../components/ai/Copiloto";
import { BannerErro, BarraProgresso, EstadoVazio, TituloTela } from "../components/ui/basics";
import { post } from "../lib/api";
import { useBriefing, useFecharForaEsc, usePainelContextual } from "../lib/hooks";
import {
  campoBriefing,
  valorLegivel,
  type PendenciaOut,
  type ValidacaoOut,
} from "../lib/types";

type Severidade = "baixa" | "media" | "alta";

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
  const { data: briefing, error: erroBriefing } = useBriefing(id);

  const [resultados, setResultados] = useState<Record<string, ValidacaoOut>>({});
  const [pendencias, setPendencias] = useState<Record<string, PendenciaOut>>({});
  const [selecionado, setSelecionado] = useState<string | null>(null);
  // A9: campo cujo diálogo de pendência está aberto (null = fechado)
  const [campoDialogo, setCampoDialogo] = useState<string | null>(null);
  const fecharDialogo = useCallback(() => setCampoDialogo(null), []);

  const campos = useMemo(() => Object.entries(briefing?.briefing ?? {}), [briefing]);
  const decididos = campos.filter(([campo]) => resultados[campo] || pendencias[campo]).length;
  const pct = campos.length > 0 ? (100 * decididos) / campos.length : 0;

  const validar = useMutation({
    mutationFn: (campo: string) =>
      post<ValidacaoOut>(`/os/${id}/validacoes/${encodeURIComponent(campo)}`),
    onSuccess: (v) => {
      setResultados((r) => ({ ...r, [v.campo]: v }));
      setSelecionado(v.campo);
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
    onSuccess: (p, dados) => {
      setPendencias((m) => ({ ...m, [dados.campo]: p }));
      setSelecionado(dados.campo);
      setCampoDialogo(null);
    },
  });

  const validacaoSelecionada = selecionado ? resultados[selecionado] : undefined;
  const pendenciaSelecionada = selecionado ? pendencias[selecionado] : undefined;

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
          <span className="mchip-r">aberta</span>
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
      {validar.error != null && <BannerErro erro={validar.error} contexto="Validação" />}
      {abrirPendencia.error != null && (
        <BannerErro erro={abrirPendencia.error} contexto="Pendência" />
      )}

      <BarraProgresso pct={pct} tom={pct === 100 ? "good" : "blue"} />
      <div className="mt-3">
        {campos.length === 0 && (
          <EstadoVazio>Briefing vazio — estruture-o na Sala de Ideação (T2).</EstadoVazio>
        )}
        {campos.map(([campo, entrada]) => {
          const e = campoBriefing(entrada);
          const resultado = resultados[campo];
          const pendencia = pendencias[campo];
          const comPendencia = Boolean(pendencia);
          // A10 (UAT): estado de envio POR LINHA — `variables` é o campo da linha
          // clicada, então cada botão reflete (e dispara) somente o próprio campo.
          const validando = validar.isPending && validar.variables === campo;
          const abrindo = abrirPendencia.isPending && abrirPendencia.variables?.campo === campo;
          return (
            <div
              key={campo}
              className={`mfield cursor-pointer ${
                comPendencia
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
                  {pendencia && (
                    <span className="mchip-r">Pendência #{pendencia.numero} aberta</span>
                  )}
                  {!resultado && !pendencia && <span className="mchip-w">pendente</span>}
                </span>
                <span className="block break-words text-[11.5px] leading-snug text-slatex">
                  {valorLegivel(e.valor)}
                  {resultado && (
                    <>
                      {" · "}
                      {resultado.checagens.map((c) => `${c.ok ? "✓" : "✗"} ${c.tipo}`).join(" · ")}
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
                  {validando ? "Validando…" : "Validar"}
                </button>
                <button
                  type="button"
                  className="mbtn-gh !px-2.5 !py-1 !text-[11px]"
                  disabled={abrindo || comPendencia}
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
