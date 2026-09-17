import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/**
 * Two ways to run this, and the backend port is the same in both.
 *
 * `npm run dev` serves the source with hot reload and proxies /api to the Python bridge, so the
 * frontend talks to the real Wilco while being edited. `npm run build` writes dist/, which
 * frontend_server.py then serves itself — one process, one port, no proxy.
 */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The bridge needs a JSON content type and a same-machine Origin, which the proxy supplies.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8799",
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
    // Assets live in public/assets and are referenced as /assets/... — the same paths the React
    // code already uses, and the same paths the Python server serves.
    assetsDir: "static",
    sourcemap: false,
  },
});