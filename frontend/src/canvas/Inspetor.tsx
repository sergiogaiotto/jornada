/**
 * Inspetor do editor T7 (painel direito do canvas): formulário por TIPO de nó com os
 * campos `data` do §5.2 — randomSplit com braços somando 100 (validação inline),
 * decisionSplit com destino escolhido entre os nós do grafo, channel.* com
 * assetRef/optIn/throttle, wait com duracao OU ate… Toda edição é aplicada ao grafo
 * LOCAL (o PUT valida no servidor ao salvar). Excluir (Delete) e Duplicar (Ctrl+D).
 */
import { useState, type ReactNode } from "react";

import { atividadeDoTipo } from "./catalogo";
import type { NoJgc } from "../lib/types";

interface Props {
  no: NoJgc | null;
  idsDeNos: string[];
  onEditarData: (id: string, data: Record<string, unknown>) => void;
  onExcluir: (id: string) => void;
  onDuplicar: (id: string) => void;
}

function Campo({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <label className="mb-2 block">
      <span className="mb-0.5 block text-[10px] font-bold uppercase tracking-[.06em] text-faint">
        {rotulo}
      </span>
      {children}
    </label>
  );
}

const CLS_INPUT =
  "w-full rounded-md border border-line2 bg-white px-2 py-1 text-[12px] outline-none focus:border-blue";

function Texto({
  valor,
  onMudar,
  placeholder,
}: {
  valor: unknown;
  onMudar: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <input
      value={typeof valor === "string" ? valor : valor == null ? "" : String(valor)}
      onChange={(e) => onMudar(e.target.value)}
      placeholder={placeholder}
      className={CLS_INPUT}
    />
  );
}

function Selecao({
  valor,
  opcoes,
  onMudar,
}: {
  valor: unknown;
  opcoes: (string | { v: string; r: string })[];
  onMudar: (v: string) => void;
}) {
  return (
    <select value={String(valor ?? "")} onChange={(e) => onMudar(e.target.value)} className={CLS_INPUT}>
      {opcoes.map((o) => {
        const { v, r } = typeof o === "string" ? { v: o, r: o } : o;
        return (
          <option key={v} value={v}>
            {r}
          </option>
        );
      })}
    </select>
  );
}

/** Textarea JSON (updateContact.valores / exception.payloadOriginal) com parse inline. */
function EditorJson({
  valor,
  onMudar,
  somenteLeitura = false,
}: {
  valor: unknown;
  onMudar?: (v: Record<string, unknown>) => void;
  somenteLeitura?: boolean;
}) {
  const [texto, setTexto] = useState(() => JSON.stringify(valor ?? {}, null, 1));
  const [erro, setErro] = useState<string | null>(null);
  return (
    <>
      <textarea
        value={texto}
        readOnly={somenteLeitura}
        rows={4}
        onChange={(e) => {
          setTexto(e.target.value);
          try {
            const parseado = JSON.parse(e.target.value) as unknown;
            if (typeof parseado !== "object" || parseado === null || Array.isArray(parseado))
              throw new Error("esperado um objeto JSON");
            setErro(null);
            onMudar?.(parseado as Record<string, unknown>);
          } catch (excecao) {
            setErro(excecao instanceof Error ? excecao.message : String(excecao));
          }
        }}
        className={`${CLS_INPUT} resize-y font-mono text-[10.5px]`}
      />
      {erro && <div className="mt-0.5 text-[10.5px] text-crit">✗ JSON inválido: {erro}</div>}
    </>
  );
}

export function Inspetor({ no, idsDeNos, onEditarData, onExcluir, onDuplicar }: Props) {
  if (!no) {
    return (
      <div className="flex h-full w-60 flex-none flex-col border-l border-line bg-surface2 p-3 text-[12px] text-muted">
        <div className="ctx-title !mt-0">Inspetor</div>
        Selecione um nó do canvas para editar os campos do §5.2 — ou arraste uma atividade
        da paleta para criar um novo.
      </div>
    );
  }

  const d = no.data ?? {};
  const editar = (patch: Record<string, unknown>) => onEditarData(no.id, { ...d, ...patch });
  const atividade = atividadeDoTipo(no.type);

  return (
    <div className="flex h-full w-60 flex-none flex-col border-l border-line bg-surface2">
      <div className="border-b border-line p-3 pb-2">
        <div className="text-[12px] font-bold text-ink2">
          {atividade?.rotulo ?? no.type}{" "}
          <span className="font-mono text-[10px] font-normal text-faint">{no.id}</span>
        </div>
        <div className="mt-1 flex gap-1.5">
          <button
            type="button"
            className="mbtn-gh !px-2 !py-0.5 !text-[10.5px]"
            title="Ctrl+D"
            onClick={() => onDuplicar(no.id)}
          >
            ⧉ Duplicar
          </button>
          <button
            type="button"
            className="mbtn-gh !px-2 !py-0.5 !text-[10.5px] !text-crit"
            title="Delete"
            onClick={() => onExcluir(no.id)}
          >
            ✕ Excluir
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3" key={no.id}>
        <CamposDoTipo no={no} d={d} editar={editar} idsDeNos={idsDeNos} />
      </div>
    </div>
  );
}

function CamposDoTipo({
  no,
  d,
  editar,
  idsDeNos,
}: {
  no: NoJgc;
  d: Record<string, unknown>;
  editar: (patch: Record<string, unknown>) => void;
  idsDeNos: string[];
}) {
  const tipo = no.type;

  if (tipo === "entrySource")
    return (
      <>
        <Campo rotulo="deRef (Data Extension)">
          <Texto valor={d["deRef"]} onMudar={(v) => editar({ deRef: v })} />
        </Campo>
        <Campo rotulo="Modo">
          <Selecao
            valor={d["modo"]}
            opcoes={["fire_once", "scheduled"]}
            onMudar={(v) => editar({ modo: v })}
          />
        </Campo>
        {d["modo"] === "scheduled" && (
          <Campo rotulo="Agenda (cron/janela)">
            <Texto valor={d["agenda"]} onMudar={(v) => editar({ agenda: v || null })} />
          </Campo>
        )}
        <Campo rotulo="Reentrada (§5.3)">
          <Selecao
            valor={d["reentrada"] ?? "nao"}
            opcoes={["nao", "apos_saida", "qualquer_momento"]}
            onMudar={(v) => editar({ reentrada: v })}
          />
        </Campo>
      </>
    );

  if (tipo === "randomSplit") {
    const bracos = ((d["braços"] ?? d["bracos"] ?? []) as { id?: string; pct?: number }[]).map(
      (b) => ({ id: String(b.id ?? ""), pct: Number(b.pct ?? 0) }),
    );
    const soma = bracos.reduce((acc, b) => acc + b.pct, 0);
    const aplicar = (novos: { id: string; pct: number }[]) => editar({ ["braços"]: novos });
    return (
      <>
        <div className="mb-1 text-[10px] font-bold uppercase tracking-[.06em] text-faint">
          Braços (id · pct) — holdout = id "holdout"
        </div>
        {bracos.map((b, i) => (
          <div key={i} className="mb-1 flex items-center gap-1">
            <input
              value={b.id}
              onChange={(e) =>
                aplicar(bracos.map((x, j) => (j === i ? { ...x, id: e.target.value } : x)))
              }
              className={`${CLS_INPUT} !w-24`}
              aria-label={`Id do braço ${i + 1}`}
            />
            <input
              type="number"
              value={b.pct}
              min={0}
              max={100}
              onChange={(e) =>
                aplicar(
                  bracos.map((x, j) => (j === i ? { ...x, pct: Number(e.target.value) } : x)),
                )
              }
              className={`${CLS_INPUT} !w-16`}
              aria-label={`Pct do braço ${i + 1}`}
            />
            <button
              type="button"
              title="Remover braço"
              className="text-[12px] text-crit"
              onClick={() => aplicar(bracos.filter((_, j) => j !== i))}
            >
              ✕
            </button>
          </div>
        ))}
        <button
          type="button"
          className="mbtn-gh !px-2 !py-0.5 !text-[10.5px]"
          onClick={() => aplicar([...bracos, { id: `braco${bracos.length + 1}`, pct: 0 }])}
        >
          + braço
        </button>
        <div
          className={`mt-1.5 text-[11px] font-bold ${Math.abs(soma - 100) > 1e-9 ? "text-crit" : "text-good"}`}
        >
          Σ pcts = {soma} {Math.abs(soma - 100) > 1e-9 ? "✗ deve somar 100 (§5.3)" : "✓"}
        </div>
        <div className="mt-1 text-[10px] text-faint">
          Cada braço precisa de uma aresta de saída com cond = id do braço.
        </div>
      </>
    );
  }

  if (tipo === "decisionSplit") {
    const regras = ((d["regras"] ?? []) as { expr?: string; to?: string }[]).map((r) => ({
      expr: String(r.expr ?? ""),
      to: String(r.to ?? ""),
    }));
    const aplicar = (novas: { expr: string; to: string }[]) => editar({ regras: novas });
    return (
      <>
        <div className="mb-1 text-[10px] font-bold uppercase tracking-[.06em] text-faint">
          Regras (expr → destino)
        </div>
        {regras.map((r, i) => (
          <div key={i} className="mb-2 rounded-md border border-line bg-white p-1.5">
            <input
              value={r.expr}
              placeholder="expr sobre atributos/eventos"
              onChange={(e) =>
                aplicar(regras.map((x, j) => (j === i ? { ...x, expr: e.target.value } : x)))
              }
              className={`${CLS_INPUT} mb-1 font-mono !text-[10.5px]`}
              aria-label={`Expressão da regra ${i + 1}`}
            />
            <div className="flex items-center gap-1">
              <select
                value={r.to}
                onChange={(e) =>
                  aplicar(regras.map((x, j) => (j === i ? { ...x, to: e.target.value } : x)))
                }
                className={CLS_INPUT}
                aria-label={`Destino da regra ${i + 1}`}
              >
                <option value="">— destino…</option>
                {idsDeNos
                  .filter((id) => id !== no.id)
                  .map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))}
              </select>
              <button
                type="button"
                title="Remover regra"
                className="text-[12px] text-crit"
                onClick={() => aplicar(regras.filter((_, j) => j !== i))}
              >
                ✕
              </button>
            </div>
          </div>
        ))}
        <button
          type="button"
          className="mbtn-gh !px-2 !py-0.5 !text-[10.5px]"
          onClick={() => aplicar([...regras, { expr: "", to: "" }])}
        >
          + regra
        </button>
      </>
    );
  }

  if (tipo === "engagementSplit")
    return (
      <>
        <Campo rotulo="Métrica">
          <Selecao
            valor={d["metrica"]}
            opcoes={["open", "click"]}
            onMudar={(v) => editar({ metrica: v })}
          />
        </Campo>
        <Campo rotulo="Janela (ISO 8601, ex.: P3D)">
          <Texto valor={d["janela"]} onMudar={(v) => editar({ janela: v })} />
        </Campo>
      </>
    );

  if (tipo === "frequencySplit") {
    const classes = (d["classes"] ?? []) as string[];
    return (
      <>
        <div className="mb-1 text-[10px] font-bold uppercase tracking-[.06em] text-faint">
          Classes (fonte = governor)
        </div>
        {(["saturado", "ok", "sub"] as const).map((classe) => (
          <label key={classe} className="mb-1 flex items-center gap-2 text-[12px]">
            <input
              type="checkbox"
              checked={classes.includes(classe)}
              onChange={(e) =>
                editar({
                  classes: e.target.checked
                    ? [...classes, classe]
                    : classes.filter((c) => c !== classe),
                  fonte: "governor",
                })
              }
            />
            {classe}
          </label>
        ))}
        <div className="mt-1 text-[10px] text-faint">
          Cada classe precisa de aresta de saída com cond = nome da classe.
        </div>
      </>
    );
  }

  if (tipo === "sto")
    return (
      <>
        <Campo rotulo="Janela (horas)">
          <input
            type="number"
            min={1}
            value={Number(d["janelaHoras"] ?? 24)}
            onChange={(e) => editar({ janelaHoras: Number(e.target.value) })}
            className={CLS_INPUT}
          />
        </Campo>
        <Campo rotulo="Fallback">
          <Texto valor={d["fallback"]} onMudar={(v) => editar({ fallback: v })} />
        </Campo>
      </>
    );

  if (tipo === "wait") {
    const modo = d["ate"] !== undefined && d["duracao"] === undefined ? "ate" : "duracao";
    return (
      <>
        <Campo rotulo="Espera por">
          <Selecao
            valor={modo}
            opcoes={[
              { v: "duracao", r: "duração fixa (ISO 8601)" },
              { v: "ate", r: "até atributo (Wait By Attribute)" },
            ]}
            onMudar={(v) =>
              editar(v === "ate" ? { duracao: undefined, ate: "" } : { ate: undefined, duracao: "P1D" })
            }
          />
        </Campo>
        {modo === "duracao" ? (
          <Campo rotulo="Duração (ex.: P2D, PT12H)">
            <Texto valor={d["duracao"]} onMudar={(v) => editar({ duracao: v })} />
          </Campo>
        ) : (
          <Campo rotulo="Atributo alvo">
            <Texto valor={d["ate"]} onMudar={(v) => editar({ ate: v })} />
          </Campo>
        )}
      </>
    );
  }

  if (tipo.startsWith("channel."))
    return (
      <>
        <Campo rotulo="assetRef (criativo aprovado T6)">
          <Texto valor={d["assetRef"]} onMudar={(v) => editar({ assetRef: v })} />
        </Campo>
        <Campo rotulo="optIn (obrigatório §5.3)">
          <Texto
            valor={typeof d["optIn"] === "boolean" ? (d["optIn"] ? "true" : "") : d["optIn"]}
            onMudar={(v) => editar({ optIn: v })}
            placeholder="ex.: email_optin"
          />
        </Campo>
        <Campo rotulo="throttlePorHora (≤ cap da política)">
          <input
            type="number"
            min={0}
            value={d["throttlePorHora"] == null ? "" : Number(d["throttlePorHora"])}
            onChange={(e) =>
              editar({
                throttlePorHora: e.target.value === "" ? undefined : Number(e.target.value),
              })
            }
            className={CLS_INPUT}
            placeholder="sem throttle"
          />
        </Campo>
        <div className="text-[10px] text-faint">
          custoUnit vem do lookup tarifa_canal — o taxímetro NÃO confia no campo (§5.2).
        </div>
      </>
    );

  if (tipo === "updateContact")
    return (
      <>
        <Campo rotulo="deRef (Data Extension)">
          <Texto valor={d["deRef"]} onMudar={(v) => editar({ deRef: v })} />
        </Campo>
        <Campo rotulo="Valores (objeto JSON)">
          <EditorJson valor={d["valores"]} onMudar={(v) => editar({ valores: v })} />
        </Campo>
      </>
    );

  if (tipo === "goal")
    return (
      <>
        <Campo rotulo="Métrica">
          <Texto valor={d["metrica"]} onMudar={(v) => editar({ metrica: v })} />
        </Campo>
        <Campo rotulo="deRef (evidência da conversão)">
          <Texto valor={d["deRef"]} onMudar={(v) => editar({ deRef: v })} />
        </Campo>
      </>
    );

  if (tipo === "exit")
    return (
      <Campo rotulo="Motivo">
        <Texto valor={d["motivo"]} onMudar={(v) => editar({ motivo: v })} />
      </Campo>
    );

  if (tipo === "exception")
    return (
      <>
        <div className="mb-1 text-[11px] font-bold text-crit">
          Nó de exceção (Adopt Wizard) — bloqueia publish até resolução (§5.2).
        </div>
        <Campo rotulo="payloadOriginal (somente leitura)">
          <EditorJson valor={d["payloadOriginal"]} somenteLeitura />
        </Campo>
      </>
    );

  return <div className="text-[11.5px] text-muted">Tipo sem formulário: {tipo}.</div>;
}
