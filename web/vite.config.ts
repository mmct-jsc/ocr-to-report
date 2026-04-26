import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Vite config for the OCR-to-Report admin UI.
//
// - `/api/*` is proxied to the FastAPI dev server on :8000 to keep the
//   browser origin equal to Vite (no CORS, no preflights). The SDK
//   talks to `/api`, never the bare host.
// - The TS SDK is consumed as a workspace local dep; we point its
//   import to the source so HMR works without rebuilding the package.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
      "@ocr-to-report/sdk": path.resolve(__dirname, "../sdk-ts/src/index.ts"),
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
  preview: {
    port: 4173,
    host: true,
  },
});
