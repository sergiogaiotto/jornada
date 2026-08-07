/**
 * Lint local do editor T7 — espelho LEVE do `jgc_validate` (SDD §5.3, código puro):
 * ids únicos, from/to existentes, braço/classe/regra sem destino, Σ pcts = 100,
 * opt-in de canal, wait sem duração, grafo sem entrySource/goal, nó órfão e
 * reentrada≠nao com holdout. O veredito FINAL continua sendo o servidor (PUT →
 * jgc_validate) — o lint só antecipa os erros no painel de problemas do canvas.
 */
import type { GrafoJgc, NoJgc } from "../lib/types";

export interface ProblemaLint {
  no: string | null;
  regra: string;
  mensagem: string;
  /** origem: lint local (ao vivo) ou 422 do servidor (após salvar) */
  origem: "local" | "servidor";
}

const TERMINAIS = new Set(["goal", "exit", "exception"]);

function braços(no: NoJgc): { id?: string; pct?: number }[] {
  const d = no.data ?? {};
  return (d["braços"] ?? d["bracos"] ?? []) as { id?: string; pct?: number }[];
}

export function lintarGrafo(grafo: GrafoJgc): ProblemaLint[] {
  const problemas: ProblemaLint[] = [];
  const erro = (no: string | null, regra: string, mensagem: string) =>
    problemas.push({ no, regra, mensagem, origem: "local" });

  const nos = grafo.nodes ?? [];
  const arestas = grafo.edges ?? [];
  const ids = new Set<string>();
  for (const no of nos) {
    if (ids.has(no.id)) erro(no.id, "estrutura", `Id de nó duplicado: ${no.id}.`);
    ids.add(no.id);
  }

  // arestas: from/to precisam apontar para nós existentes (§5.1)
  for (const a of arestas) {
    if (!a.from || !ids.has(a.from))
      erro(null, "estrutura", `Aresta ${a.id} parte de nó inexistente: ${a.from || "?"}.`);
    if (!a.to || !ids.has(a.to))
      erro(a.from && ids.has(a.from) ? a.from : null, "braco_sem_destino",
        `Aresta ${a.id} aponta para nó inexistente: ${a.to || "?"}.`);
  }

  // saídas por nó (regras de decisionSplit contam — mesma adjacência do backend)
  const saidas = new Map<string, { to: string; cond: string | null }[]>();
  const empilhar = (de: string, to: string, cond: string | null) =>
    saidas.set(de, [...(saidas.get(de) ?? []), { to, cond }]);
  for (const a of arestas) if (a.from) empilhar(a.from, a.to, a.cond ?? null);
  for (const no of nos) {
    if (no.type !== "decisionSplit") continue;
    const regras = (no.data?.["regras"] ?? []) as { expr?: string; to?: string }[];
    for (const r of regras) if (r.to) empilhar(no.id, r.to, r.expr ?? null);
  }

  const entradas = nos.filter((n) => n.type === "entrySource").map((n) => n.id);
  if (entradas.length === 0)
    erro(null, "no_orfao", "Grafo sem entrySource (§5.2) — nada é alcançável.");

  // alcançabilidade (BFS a partir das entradas)
  const alcancados = new Set(entradas);
  const fila = [...entradas];
  while (fila.length > 0) {
    const atual = fila.pop() as string;
    for (const s of saidas.get(atual) ?? [])
      if (ids.has(s.to) && !alcancados.has(s.to)) {
        alcancados.add(s.to);
        fila.push(s.to);
      }
  }

  for (const no of nos) {
    const tipo = no.type;
    const arestasDoNo = saidas.get(no.id) ?? [];
    const conds = new Set(arestasDoNo.map((a) => String(a.cond)));
    if (!alcancados.has(no.id) && entradas.length > 0)
      erro(no.id, "no_orfao", `Nó órfão: ${no.id} (${tipo}) inalcançável da entrada.`);
    if (!TERMINAIS.has(tipo) && arestasDoNo.length === 0)
      erro(no.id, "braco_sem_destino", `Nó ${no.id} (${tipo}) sem aresta de saída (§5.3).`);

    if (tipo === "randomSplit") {
      const bs = braços(no);
      const soma = bs.reduce((acc, b) => acc + Number(b.pct ?? 0), 0);
      if (bs.length === 0)
        erro(no.id, "campo_obrigatorio", `randomSplit ${no.id} sem braços (§5.2).`);
      else if (Math.abs(soma - 100) > 1e-9)
        erro(no.id, "soma_pcts", `Soma dos pcts do randomSplit ${no.id} = ${soma} ≠ 100.`);
      for (const b of bs)
        if (!conds.has(String(b.id)))
          erro(no.id, "braco_sem_destino",
            `Braço "${b.id}" do randomSplit ${no.id} sem aresta com cond="${b.id}" (§5.3).`);
    }
    if (tipo === "frequencySplit") {
      // D05/I01: classe pode ser string OU objeto {id, min/max} — casar por id,
      // como o backend (a comparação por String(classe) virava "[object Object]"
      // e o lint reprovava localmente um grafo que o servidor aceita).
      for (const classe of (no.data?.["classes"] ?? []) as
        (string | { id?: string })[]) {
        const rotulo = typeof classe === "object" && classe !== null ? classe.id : classe;
        if (!conds.has(String(rotulo)))
          erro(no.id, "braco_sem_destino",
            `Classe "${rotulo}" do frequencySplit ${no.id} sem aresta com cond="${rotulo}".`);
      }
    }
    if (tipo === "engagementSplit" && arestasDoNo.length < 2)
      erro(no.id, "braco_sem_destino",
        `engagementSplit ${no.id} exige os dois braços (engajou/não) com destino.`);
    if (tipo === "decisionSplit") {
      const regras = (no.data?.["regras"] ?? []) as
        { expr?: string; to?: string; id?: string; cond?: string | null }[];
      if (regras.length === 0)
        erro(no.id, "campo_obrigatorio", `decisionSplit ${no.id} sem regras (§5.2).`);
      // I02 — espelho da regra bloqueante `roteamento_ambiguo` do §5.3: regra com `to`
      // (forma nova) e aresta real saindo do MESMO nó (forma clássica) duplicariam a
      // saída na adjacência única (D07) — taxímetro, motor §6 e compilador contavam o
      // braço repetido (+33%). Antes deste espelho o lint tinha o vício CONTRÁRIO:
      // exigia `to` em toda regra, reprovando localmente a forma clássica {id, cond}
      // que o D07 legalizou — o painel acusava erro num grafo que o servidor aceita.
      const comTo = regras.filter((r) => r.to);
      const semTo = regras.filter((r) => !r.to);
      const arestasReais = arestas.filter((a) => a.from === no.id);
      if (comTo.length > 0 && (arestasReais.length > 0 || semTo.length > 0))
        erro(no.id, "roteamento_ambiguo",
          `decisionSplit ${no.id} mistura roteamento por regra (regras[].to) com ` +
          `roteamento por aresta — as duas formas são mutuamente exclusivas por nó ` +
          `(§5.3). Use regras[{expr, to}] SEM arestas saindo do nó, OU regras[{id, ` +
          `cond}] com o destino nas arestas — nunca ambos.`);
      for (const [i, r] of regras.entries()) {
        if (r.to && !ids.has(r.to)) erro(no.id, "braco_sem_destino",
          `Regra ${i + 1} do decisionSplit ${no.id} aponta para nó inexistente: ${r.to}.`);
        // regra incompleta: nem destino (forma nova) nem id (forma clássica) — o
        // estado que o "+ regra" do Inspetor cria antes de o usuário preencher.
        if (!r.to && !r.id) erro(no.id, "braco_sem_destino",
          `Regra ${i + 1} do decisionSplit ${no.id} sem destino: preencha o "to" ` +
          `(forma nova) ou o "id" casando com o cond de uma aresta (forma clássica).`);
        // braço clássico MORTO (auditoria da onda 5): regra {id} sem aresta com o
        // cond correspondente não roteia ninguém — espelho do check do backend.
        if (comTo.length === 0 && !r.to && r.id && !conds.has(String(r.id)))
          erro(no.id, "braco_sem_destino",
            `Regra "${r.id}" do decisionSplit ${no.id} sem aresta com cond="${r.id}" ` +
            `(braço morto — §5.3).`);
      }
    }
    if (tipo.startsWith("channel.")) {
      if (!no.data?.["optIn"])
        erro(no.id, "optin_ausente", `Nó ${no.id} (${tipo}) sem opt-in configurado (§5.3).`);
      if (!no.data?.["assetRef"])
        erro(no.id, "campo_obrigatorio", `Nó ${no.id} (${tipo}) sem assetRef (§5.2).`);
    }
    if (tipo === "wait" && !no.data?.["duracao"] && !no.data?.["ate"])
      erro(no.id, "campo_obrigatorio", `Nó ${no.id} (wait) exige duracao OU ate (§5.2).`);
  }

  if (!nos.some((n) => n.type === "goal"))
    erro(null, "sem_goal", "Grafo sem nó goal (§5.3).");
  if (nos.some((n) => n.type === "exception"))
    erro(nos.find((n) => n.type === "exception")?.id ?? null, "exception",
      "Grafo com nó exception (Adopt Wizard) — bloqueia publish até resolução (§5.2).");

  // reentrada ≠ nao com holdout quebra o experimento (§5.3)
  const temHoldout = nos.some(
    (n) => n.type === "randomSplit" &&
      braços(n).some((b) => String(b.id ?? "").toLowerCase() === "holdout"),
  );
  const reentrada =
    (nos.find((n) => n.type === "entrySource")?.data?.["reentrada"] as string | undefined) ||
    String(grafo.meta?.reentrada ?? "nao");
  if (reentrada !== "nao" && temHoldout)
    erro(entradas[0] ?? null, "reentrada_com_holdout",
      `reentrada=${reentrada} com holdout no grafo quebra o experimento (§5.3) — use reentrada=nao.`);

  return problemas;
}
