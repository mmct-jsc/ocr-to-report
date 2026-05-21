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
// ``DEPLOY_TARGET=pages`` flips the build to GitHub-Pages-friendly mode:
//   * base path becomes ``/ocr-to-report/`` so asset URLs resolve under
//     ``https://mmct-jsc.github.io/ocr-to-report/``.
//   * the rest of the config is identical (the SPA still talks to ``/api``
//     by convention; on Pages there is no API, so the demo route shows
//     "API unreachable" by design — it's a feature tour, not a live app).
const isPagesBuild = process.env.DEPLOY_TARGET === "pages";

export default defineConfig({
  plugins: [react()],
  base: isPagesBuild ? "/ocr-to-report/" : "/",
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
