/**
 * Header de versionamento e exportação do canvas T7 (emenda §8-M7):
 * - dropdown de VERSÕES (GET /os/{id}/jornadas — "v2 · rascunho (atual)");
 * - "Comparar com…" → diff visual pintado no próprio canvas (GET diff do BE);
 * - Exportar ▾ → download via GET /jornadas/{id}/export (JSON = spec de import
 *   NATIVO do Journey Builder · XML = integração/auditoria com manifest+XSD).
 */
import { useCallback, useState } from "react";

import { useFecharForaEsc } from "../lib/hooks";
import type { JornadaResumoOut } from "../lib/types";

interface Props {
  versoes: JornadaResumoOut[];
  /** versão em exibição no canvas */
  exibidaId: string;
  /** última versão (a "atual" — única editável) */
  ultimaId: string;
  compararComId: string | null;
  exportando: boolean;
  onVerVersao: (id: string) => void;
  onCompararCom: (id: string | null) => void;
  onExportar: (formato: "json" | "xml") => void;
}

export function HeaderVersoes({
  versoes,
  exibidaId,
  ultimaId,
  compararComId,
  exportando,
  onVerVersao,
  onCompararCom,
  onExportar,
}: Props) {
  const [exportAberto, setExportAberto] = useState(false);
  const fecharExport = useCallback(() => setExportAberto(false), []);
  // clique fora / Esc fecham o dropdown (padrão do DropdownGuia)
  const raizExport = useFecharForaEsc(exportAberto, fecharExport);
  const ordenadas = [...versoes].sort((a, b) => b.versao - a.versao);

  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-line bg-white px-3 py-1.5">
      <label className="flex items-center gap-1.5 text-[11px] font-bold text-steel">
        Versões
        <select
          value={exibidaId}
          onChange={(e) => onVerVersao(e.target.value)}
          className="rounded-md border border-line2 px-2 py-1 text-[11.5px] font-normal outline-none focus:border-blue"
          title="Linha do tempo do twin (GET /os/{id}/jornadas) — selecionar versão antiga abre somente leitura"
        >
          {ordenadas.map((v) => (
            <option key={v.id} value={v.id}>
              v{v.versao} · {v.estado}
              {v.id === ultimaId ? " (atual)" : ""}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-1.5 text-[11px] font-bold text-steel">
        Comparar com…
        <select
          value={compararComId ?? ""}
          onChange={(e) => onCompararCom(e.target.value || null)}
          className="rounded-md border border-line2 px-2 py-1 text-[11.5px] font-normal outline-none focus:border-blue"
          title="Diff visual entre versões — pinta adicionados/removidos/alterados no próprio canvas"
        >
          <option value="">—</option>
          {ordenadas
            .filter((v) => v.id !== exibidaId)
            .map((v) => (
              <option key={v.id} value={v.id}>
                v{v.versao} · {v.estado}
              </option>
            ))}
        </select>
      </label>
      {compararComId && (
        <button
          type="button"
          className="mbtn-gh !px-2 !py-0.5 !text-[11px]"
          onClick={() => onCompararCom(null)}
        >
          ✕ limpar
        </button>
      )}

      <div ref={raizExport} className="relative ml-auto">
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={exportAberto}
          className="mbtn-gh !px-2.5 !py-1 !text-[11px]"
          disabled={exportando}
          onClick={() => setExportAberto((v) => !v)}
        >
          {exportando ? "Exportando…" : "⬇ Exportar ▾"}
        </button>
        {exportAberto && (
          <div className="absolute right-0 top-8 z-20 w-72 rounded-lg border border-line bg-white p-1.5 shadow-card">
            <button
              type="button"
              className="block w-full rounded-md px-2.5 py-1.5 text-left text-[11.5px] hover:bg-surface2"
              onClick={() => {
                setExportAberto(false);
                onExportar("json");
              }}
            >
              <b>JSON (spec de import) ↓</b>
              <span className="block text-[10.5px] text-muted">
                import NATIVO do Journey Builder — REST /interaction/v1/interactions
              </span>
            </button>
            <button
              type="button"
              className="block w-full rounded-md px-2.5 py-1.5 text-left text-[11.5px] hover:bg-surface2"
              onClick={() => {
                setExportAberto(false);
                onExportar("xml");
              }}
            >
              <b>XML (Journey Builder) ↓</b>
              <span className="block text-[10.5px] text-muted">
                mesma spec canônica + manifest (hash, versão, geradoEm) — integração e
                auditoria corporativa, validável pelo XSD
              </span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
