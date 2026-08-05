import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { ErrorBoundary } from "./components/shell/ErrorBoundary";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 15_000,
      // API mesma-origem (proxy Vite → localhost:8000): navigator.onLine não é
      // confiável e pausaria queries/retries silenciosamente ("paused").
      networkMode: "always",
    },
    mutations: {
      networkMode: "always",
    },
  },
});

// Dev: inspeção do cache no console (não existe em produção)
if (import.meta.env.DEV) {
  (window as unknown as Record<string, unknown>)["__queryClient"] = queryClient;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        {/* último recurso (A16): erro fora do shell nunca vira página branca */}
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
