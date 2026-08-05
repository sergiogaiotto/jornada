/**
 * Catálogo das atividades do editor T7 — os tipos FECHADOS do JGC (SDD §5.2),
 * agrupados nas categorias visuais do Journey Builder (paleta jb-* do tailwind).
 * Cada entrada carrega o tooltip do §5.2 (campos obrigatórios + no que compila no
 * SFMC) e a fábrica de `data` default — sempre um objeto que satisfaz o schema
 * (`jgc.schema.json`); o lint local (lint.ts) aponta o que ainda falta conectar.
 * `exception` NÃO entra na paleta: só nasce do Adopt Wizard (§5.2) e bloqueia publish.
 */
import type { CategoriaJb } from "../components/twin/NoJb";
import type { NoJgc } from "../lib/types";

export interface TipoDeAtividade {
  tipo: string;
  rotulo: string;
  categoria: CategoriaJb;
  grupo: string;
  icone: string;
  /** tooltip §5.2: data obrigatório + alvo de compilação SFMC */
  tooltip: string;
  dataDefault: () => Record<string, unknown>;
}

/** Cor hex por categoria (tailwind jb-*) — MiniMap e chips da paleta. */
export const COR_CATEGORIA: Record<CategoriaJb, string> = {
  entry: "#2E844A",
  msg: "#0B827C",
  flow: "#DD7A01",
  wait: "#DD7A01",
  ein: "#9050E9",
  upd: "#0176D3",
  exit: "#747E8B",
};

const CANAIS: { canal: string; rotulo: string; icone: string }[] = [
  { canal: "email", rotulo: "E-mail", icone: "✉" },
  { canal: "sms", rotulo: "SMS", icone: "💬" },
  { canal: "push", rotulo: "Push", icone: "🔔" },
  { canal: "whatsapp", rotulo: "WhatsApp", icone: "🟢" },
  { canal: "rcs", rotulo: "RCS", icone: "✉" },
];

export const CATALOGO: TipoDeAtividade[] = [
  {
    tipo: "entrySource",
    rotulo: "Entry Source",
    categoria: "entry",
    grupo: "Entry Source",
    icone: "▶",
    tooltip:
      "§5.2 entrySource — data: deRef, modo (fire_once/scheduled), agenda?, reentrada. " +
      "Compila para Event Definition + Entry Source.",
    dataDefault: () => ({ deRef: "DE_entrada", modo: "fire_once", agenda: null, reentrada: "nao" }),
  },
  {
    tipo: "randomSplit",
    rotulo: "Random Split",
    categoria: "flow",
    grupo: "Flow Control",
    icone: "%",
    tooltip:
      "§5.2 randomSplit — data: braços[{id, pct}] (Σ pct = 100); usado para HOLDOUT " +
      "(braço id `holdout`) e A/B. Compila para Random Split.",
    dataDefault: () => ({
      "braços": [
        { id: "tratado", pct: 90 },
        { id: "holdout", pct: 10 },
      ],
    }),
  },
  {
    tipo: "decisionSplit",
    rotulo: "Decision Split",
    categoria: "flow",
    grupo: "Flow Control",
    icone: "?",
    tooltip:
      "§5.2 decisionSplit — data: regras[{expr sobre atributos/eventos, to}]. " +
      "Compila para Decision Split.",
    dataDefault: () => ({ regras: [{ expr: "perfil == 'heavy_user'", to: "" }] }),
  },
  {
    tipo: "engagementSplit",
    rotulo: "Engagement Split",
    categoria: "flow",
    grupo: "Flow Control",
    icone: "E",
    tooltip:
      "§5.2 engagementSplit — data: metrica (open/click), janela. Exige os DOIS braços " +
      "(engajou/não) com destino. Compila para Engagement Split.",
    dataDefault: () => ({ metrica: "open", janela: "P3D" }),
  },
  {
    tipo: "frequencySplit",
    rotulo: "Frequency Split",
    categoria: "flow",
    grupo: "Flow Control",
    icone: "f",
    tooltip:
      "§5.2 frequencySplit — data: classes (saturado/ok/sub), fonte=governor. Cada classe " +
      "precisa de aresta com cond igual ao nome. Einstein Frequency ou twin-emulado.",
    dataDefault: () => ({ classes: ["saturado", "ok", "sub"], fonte: "governor" }),
  },
  {
    tipo: "wait",
    rotulo: "Wait",
    categoria: "wait",
    grupo: "Flow Control",
    icone: "⏱",
    tooltip:
      "§5.2 wait — data: duracao (ISO 8601, ex.: P2D, PT12H) OU ate (atributo com o " +
      "instante alvo). Compila para Wait.",
    dataDefault: () => ({ duracao: "P1D" }),
  },
  {
    tipo: "sto",
    rotulo: "STO",
    categoria: "ein",
    grupo: "Otimização",
    icone: "✦",
    tooltip:
      "§5.2 sto — data: janelaHoras (24), fallback. Einstein STO ou twin-emulado " +
      "(Wait By Attribute com hora ótima).",
    dataDefault: () => ({ janelaHoras: 24, fallback: "enviar_imediato" }),
  },
  ...CANAIS.map(({ canal, rotulo, icone }) => ({
    tipo: `channel.${canal}`,
    rotulo,
    categoria: "msg" as CategoriaJb,
    grupo: "Mensagens",
    icone,
    tooltip:
      `§5.2 channel.${canal} — data: assetRef, throttlePorHora?, optIn (obrigatório §5.3); ` +
      "custoUnit vem do lookup tarifa_canal (o taxímetro não confia no campo). " +
      "Compila para Send/Message activity.",
    dataDefault: () => ({ assetRef: `asset_${canal}_1`, optIn: `${canal}_optin` }),
  })),
  {
    tipo: "updateContact",
    rotulo: "Update Contact",
    categoria: "upd",
    grupo: "Customer Updates",
    icone: "↺",
    tooltip: "§5.2 updateContact — data: deRef, valores. Compila para Update Contact.",
    dataDefault: () => ({ deRef: "DE_atualizacao", valores: { origem: "jornada" } }),
  },
  {
    tipo: "goal",
    rotulo: "Meta / Goal",
    categoria: "exit",
    grupo: "Meta / Exit",
    icone: "🎯",
    tooltip: "§5.2 goal — data: metrica, deRef. Obrigatório no grafo (§5.3). Compila para Goal.",
    dataDefault: () => ({ metrica: "conversao", deRef: "DE_conversoes" }),
  },
  {
    tipo: "exit",
    rotulo: "Exit",
    categoria: "exit",
    grupo: "Meta / Exit",
    icone: "◼",
    tooltip: "§5.2 exit — data: motivo. Compila para Exit.",
    dataDefault: () => ({ motivo: "fim_da_jornada" }),
  },
];

/** Grupos na ordem de exibição da paleta (mesma ordem do Journey Builder). */
export const GRUPOS_PALETA = [
  "Entry Source",
  "Flow Control",
  "Otimização",
  "Mensagens",
  "Customer Updates",
  "Meta / Exit",
];

export function atividadeDoTipo(tipo: string): TipoDeAtividade | undefined {
  return CATALOGO.find((a) => a.tipo === tipo);
}

/** Próximo id livre no padrão `n<seq>` — não colide com ids existentes. */
export function proximoId(nos: NoJgc[]): string {
  let maior = 0;
  for (const no of nos) {
    const m = /^n(\d+)$/.exec(no.id);
    if (m) maior = Math.max(maior, Number(m[1]));
  }
  let candidato = `n${maior + 1}`;
  const ids = new Set(nos.map((n) => n.id));
  while (ids.has(candidato)) candidato = `n${Number(candidato.slice(1)) + 1}`;
  return candidato;
}

/** Próximo id livre de aresta no padrão `e<seq>`. */
export function proximoIdAresta(ids: Iterable<string>): string {
  let maior = 0;
  const existentes = new Set<string>();
  for (const id of ids) {
    existentes.add(id);
    const m = /^e(\d+)$/.exec(id);
    if (m) maior = Math.max(maior, Number(m[1]));
  }
  let candidato = `e${maior + 1}`;
  while (existentes.has(candidato)) candidato = `e${Number(candidato.slice(1)) + 1}`;
  return candidato;
}
