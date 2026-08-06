/**
 * Roteamento completo do SDD §12:
 * `/` T1 · `/os/:id/(briefing|validacao|warroom|workflow|audiencia|datacloud|criativo|
 * twin|simulacao|portoes|prevoo|lancamento|monitor|perguntas|retro)` ·
 * `/aprovacao/:token` (standalone, sem shell) · `/atelie/*` · `/usuarios` (admin).
 *
 * Emenda E04 — autenticação: `/login` é a ÚNICA rota fora da guarda. Todo o resto,
 * inclusive o portal de aprovação, vive sob `<ExigirSessao>`: o link mágico continua
 * apontando para o pacote, mas quem decide é a sessão autenticada (§8-M8/E05 — "o
 * fecho definitivo é a aprovação exigir sessão autenticada"). `/login` e
 * `/trocar-senha` são standalone (sem shell): sem identidade não há rail nem topbar.
 */
import { useEffect } from "react";
import { Navigate, Outlet, Route, Routes, useParams } from "react-router-dom";

import { AppShell } from "./components/shell/AppShell";
import { ExigirSessao } from "./components/shell/ExigirSessao";
import { Aprovacao } from "./pages/Aprovacao";
import { Atelie } from "./pages/Atelie";
import { Audiencia } from "./pages/Audiencia";
import { Cockpit } from "./pages/Cockpit";
import { Criativo } from "./pages/Criativo";
import { DataCloud } from "./pages/DataCloud";
import { Ensaio } from "./pages/Ensaio";
import { Esteira } from "./pages/Esteira";
import { Ideacao } from "./pages/Ideacao";
import { Lancamento } from "./pages/Lancamento";
import { Login } from "./pages/Login";
import { Monitor } from "./pages/Monitor";
import { Perguntas } from "./pages/Perguntas";
import { Portoes } from "./pages/Portoes";
import { Prevoo } from "./pages/Prevoo";
import { Retro } from "./pages/Retro";
import { TrocarSenha } from "./pages/TrocarSenha";
import { Twin } from "./pages/Twin";
import { Usuarios } from "./pages/Usuarios";
import { Validacao } from "./pages/Validacao";
import { WarRoom } from "./pages/WarRoom";
import { useUi } from "./stores/ui";

/** Publica a OS em foco (rota /os/:id/*) para o rail e a topbar. */
function EscopoOs() {
  const { id } = useParams<{ id: string }>();
  const setOsAtualId = useUi((s) => s.setOsAtualId);

  useEffect(() => {
    setOsAtualId(id ?? null);
  }, [id, setOsAtualId]);

  return <Outlet />;
}

export default function App() {
  return (
    <Routes>
      {/* Única rota anônima (E04) */}
      <Route path="/login" element={<Login />} />

      <Route element={<ExigirSessao />}>
        {/* Standalone — sem shell: troca obrigatória de senha e link mágico (§12) */}
        <Route path="/trocar-senha" element={<TrocarSenha />} />
        <Route path="/aprovacao/:token" element={<Aprovacao />} />

        <Route element={<AppShell />}>
          <Route path="/" element={<Cockpit />} />

          {/* Sala de Ideação em modo pedido — "+ Nova Campanha" (§8-M3) */}
          <Route path="/pedidos/:id" element={<Ideacao modo="pedido" />} />

          <Route path="/os/:id" element={<EscopoOs />}>
            <Route index element={<Navigate to="briefing" replace />} />
            <Route path="briefing" element={<Ideacao />} />
            <Route path="validacao" element={<Validacao />} />
            <Route path="warroom" element={<WarRoom />} />
            <Route path="workflow" element={<Esteira />} />
            <Route path="audiencia" element={<Audiencia />} />
            <Route path="datacloud" element={<DataCloud />} />
            <Route path="criativo" element={<Criativo />} />
            <Route path="twin" element={<Twin />} />
            <Route path="simulacao" element={<Ensaio />} />
            <Route path="portoes" element={<Portoes />} />
            <Route path="prevoo" element={<Prevoo />} />
            <Route path="lancamento" element={<Lancamento />} />
            <Route path="monitor" element={<Monitor />} />
            <Route path="perguntas" element={<Perguntas />} />
            <Route path="retro" element={<Retro />} />
          </Route>

          <Route path="/atelie/*" element={<Atelie />} />

          {/* Administração de acesso — a própria tela barra quem não é admin (E04) */}
          <Route path="/usuarios" element={<Usuarios />} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}
