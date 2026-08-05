import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// SDD §12 — SPA Vite+React+TS. Proxy dev: /api/v1 → backend FastAPI (localhost:8000).
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // separa vendor pesado em chunks próprios (cache estável entre deploys
        // e nenhum chunk >500kB — sem o warning de chunk size do Vite/Rollup)
        manualChunks: {
          "vendor-react": ["react", "react-dom", "react-router-dom"],
          "vendor-flow": ["@xyflow/react"],
          "vendor-charts": ["recharts"],
        },
      },
    },
  },
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
