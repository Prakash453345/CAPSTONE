import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import { itmsNetwork, networkAlias } from "./network.config";

// TRAFFIX Command Center — Vite config.
// Dev server proxies /api and /ws to the ITMS api-service so the browser can
// talk to it without CORS juggling. (Vitest config lives in vitest.config.ts.)
export default defineConfig({
  plugins: [react()],
  define: {
    "import.meta.env.VITE_ITMS_NETWORK": JSON.stringify(itmsNetwork()),
  },
  resolve: {
    alias: [
      networkAlias(),
      { find: "@", replacement: fileURLToPath(new URL("./src", import.meta.url)) },
      // The vendored TacticalGlobe3D component (src/vendor/TacticalGlobe3D.js)
      // imports the editor-only "framer" package; this shim stands in for it
      // at runtime. See src/vendor/framer-shim.ts for why that's safe.
      { find: "framer", replacement: fileURLToPath(new URL("./src/vendor/framer-shim.ts", import.meta.url)) },
    ],
  },
  build: {
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
  server: {
    port: 5173,
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
