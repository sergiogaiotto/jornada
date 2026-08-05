/**
 * Painel de problemas do editor T7: lint local (§5.3 espelhado — ao vivo) + erros
 * 422 do servidor (jgc_validate no PUT). Clicar num problema centraliza o nó no
 * canvas (anel vermelho via data.erro do NoJb).
 */
import type { ProblemaLint } from "./lint";

export function PainelProblemas({
  problemas,
  onFocar,
}: {
  problemas: ProblemaLint[];
  onFocar: (noId: string) => void;
}) {
  if (problemas.length === 0)
    return (
      <div className="mt-2 rounded-md border border-line bg-surface2 px-3 py-1.5 text-[11.5px] text-good">
        ✓ Nenhum problema — o grafo passa no espelho local do jgc_validate (§5.3).
      </div>
    );
  return (
    <div className="mt-2 rounded-md border border-warn-line bg-warn-bg px-3 py-2">
      <div className="mb-1 text-[10px] font-bold uppercase tracking-[.08em] text-warn">
        Problemas ({problemas.length}) — o veredito final é o jgc_validate do servidor
      </div>
      <div className="grid max-h-28 gap-0.5 overflow-y-auto">
        {problemas.map((p, i) => (
          <button
            key={i}
            type="button"
            disabled={!p.no}
            onClick={() => p.no && onFocar(p.no)}
            className={`w-fit max-w-full truncate text-left text-[11.5px] text-crit ${
              p.no ? "cursor-pointer hover:underline" : "cursor-default"
            }`}
            title={p.no ? `Centralizar ${p.no} no canvas` : undefined}
          >
            ✗ <b>{p.no ?? "grafo"}</b> · {p.regra}
            {p.origem === "servidor" && (
              <span className="mchip-r ml-1 !text-[9px] uppercase">servidor</span>
            )}{" "}
            — {p.mensagem}
          </button>
        ))}
      </div>
    </div>
  );
}
