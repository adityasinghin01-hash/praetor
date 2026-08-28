import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /v1 to the FastAPI app so the frontend is never developed
// against a mock. A mock is a second contract, and the second contract is the one that
// drifts -- the whole reason dashboard/api.py exists as one place.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: true },
  server: {
    port: 5173,
    proxy: { "/v1": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
