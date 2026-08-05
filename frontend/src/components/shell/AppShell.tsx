/**
 * Shell 3 zonas (SDD §12 / layout Maestro dos mocks): topbar vermelha + rail esquerdo
 * colapsável + centro operacional + painel direito contextual (slot — casa do copiloto).
 */
import { Outlet } from "react-router-dom";

import { useUi } from "../../stores/ui";
import { CmdK } from "./CmdK";
import { Rail } from "./Rail";
import { Topbar } from "./Topbar";

export function AppShell() {
  const painel = useUi((s) => s.painel);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Topbar />
      <div className="flex min-h-0 flex-1">
        <Rail />
        <main className="min-w-0 flex-1 overflow-y-auto p-5">
          <Outlet />
        </main>
        {painel != null && (
          <aside
            aria-label="Painel contextual"
            className="w-72 flex-none overflow-y-auto border-l border-line bg-white p-4"
          >
            {painel}
          </aside>
        )}
      </div>
      <CmdK />
    </div>
  );
}
