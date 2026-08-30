import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The dev server proxies /v1 to the FastAPI app so the frontend is never developed
// against a mock. A mock is a second contract, and the second contract is the one that
// drifts -- the whole reason dashboard/api.py exists as one place.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // shadcn/React Bits components are published against the "@/" alias.
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    // Fonts must be emitted as files, never inlined. Vite base64s any asset under 4 KB
    // into the CSS, and the Content Security Policy is `default-src 'self'` with no
    // `data:` — so every inlined face was blocked in production while looking perfect in
    // dev, where no policy applies. It also pushed the stylesheet from 47 KB to 741 KB.
    assetsInlineLimit: 0,
  },
  server: {
    port: 5173,
    // `/login` and `/logout` are served by FastAPI, not by this app. Without them here
    // the dev server answers with its own SPA fallback, so "Sign in" lands back on the
    // page that sent you — dev quietly disagreeing with production about whether the
    // app can be signed into at all.
    proxy: {
      "/v1": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/login": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/logout": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
