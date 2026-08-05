/**
 * ErrorBoundary global (achado A16 do UAT): erro de render em qualquer tela não pode
 * derrubar a SPA inteira em página branca — fallback amigável com "Recarregar".
 * Usado em dois níveis: dentro do shell (por rota — o chrome sobrevive e a navegação
 * pelo rail continua possível) e na raiz (último recurso, cobre o próprio shell).
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  erro: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { erro: null };

  static getDerivedStateFromError(erro: Error): State {
    return { erro };
  }

  componentDidCatch(erro: Error, info: ErrorInfo): void {
    // Diagnóstico no console — a UI mostra só a mensagem amigável.
    console.error("Erro de render capturado pelo ErrorBoundary:", erro, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.erro !== null) {
      return (
        <div className="m-6 rounded-lg border border-warn-line bg-warn-bg px-5 py-4 text-[13px] text-ink">
          <b>Algo deu errado nesta tela.</b>
          <div className="mt-1 text-[12px] text-muted">
            O restante da aplicação segue funcionando — recarregue para tentar de novo.
            {this.state.erro.message && (
              <span className="mt-1 block font-mono text-[11px]">{this.state.erro.message}</span>
            )}
          </div>
          <button type="button" className="mbtn mt-3" onClick={() => window.location.reload()}>
            Recarregar
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
