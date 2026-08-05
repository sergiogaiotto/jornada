import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// SDD §12 — SPA Vite+React+TS. Proxy dev: /api/v1 → backend FastAPI (localhost:8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
