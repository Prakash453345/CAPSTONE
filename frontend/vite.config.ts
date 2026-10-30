import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { itmsNetwork, networkAlias } from "./network.config";
import { cspPlugin } from "./csp.config";

// Response headers for the dev and preview servers. A meta-tag CSP (see
// csp.config.ts) cannot stop framing, so clickjacking is blocked here; a
// production host should send the same headers.
const SECURITY_HEADERS = {
  "X-Frame-Options": "DENY",
  "Content-Security-Policy": "frame-ancestors 'none'",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
};

// TRAFFIX Command Center — Vite config.
// Dev server proxies /api and /ws to the ITMS api-service so the browser can
// talk to it without CORS juggling. (Vitest config lives in vitest.config.ts.)
export default defineConfig({
  plugins: [react(), cspPlugin()],
  define: {
    "import.meta.env.VITE_ITMS_NETWORK": JSON.stringify(itmsNetwork()),
  },
  resolve: {
    alias: [
      networkAlias(),
      { find: "@", replacement: fileURLToPath(new URL("./src", import.meta.url)) },
    ],
  },
  build: {
    // ES2022 for top-level await: src/data/network.ts fetches Amaravati's roads
    // before the map modules use them.
    target: "es2022",
    // Read by scripts/check-bundle-budget.mjs to measure each page's first download.
    manifest: true,
    rollupOptions: {
      output: {
        manualChunks: {
          maplibre: ["maplibre-gl"],
          vendor: ["react", "react-dom", "react-router-dom", "framer-motion"],
        },
      },
    },
  },
  preview: {
    headers: SECURITY_HEADERS,
  },
  server: {
    port: 5173,
    headers: SECURITY_HEADERS,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
        rewrite: (p) => p.replace(/^\/ws/, ""),
      },
    },
  },
});
