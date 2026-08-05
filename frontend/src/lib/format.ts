/** Formatação pt-BR (SDD §12 i18n): inteiros, compactos ("847,3k"), moeda e frescor. */

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString("pt-BR");
}

/** Compacto no estilo dos mocks: 847.312 → "847,3k" · 2.104.500 → "2,1M". */
export function fmtCompacto(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) >= 1_000_000)
    return `${(n / 1_000_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}M`;
  if (Math.abs(n) >= 1_000)
    return `${(n / 1_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}k`;
  return n.toLocaleString("pt-BR");
}

export function fmtBRL(v: number | string | null | undefined, casas = 2): string {
  const n = typeof v === "string" ? Number(v) : v;
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  });
}

/** Tarifa unitária com 4 casas (tarifário §11.4: email 0,0018 · whatsapp 0,3597). */
export function fmtTarifa(v: number | string | null | undefined): string {
  return fmtBRL(v, 4);
}

export function horasDesde(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return (Date.now() - t) / 3_600_000;
}

/** Frescor relativo no estilo dos mocks: "há 3h" · "há 1d" · "tempo real" (<1h). */
export function tempoRelativo(iso: string | null | undefined): string {
  const horas = horasDesde(iso);
  if (horas === null) return "—";
  if (horas < 1) return "tempo real";
  if (horas < 48) return `há ${Math.round(horas)}h`;
  return `há ${Math.round(horas / 24)}d`;
}

/** Rótulo legível de uma fonte/lista snake_case ("hybris_base_clientes" → "hybris base clientes"). */
export function rotuloFonte(nome: string): string {
  return nome.split("_").join(" ");
}
