import { defineConfig } from "vitest/config";
import { fileURLToPath, URL } from "node:url";
import { networkAlias } from "./network.config";

// Standalone Vitest config so vite.config.ts stays a plain Vite config (the
// bundled/nested vite copies otherwise clash on the react plugin's types).
// Tests are plain-logic units — data-layer mappers and store reducers — so no
// React plugin and no DOM environment are needed.
export default defineConfig({
  resolve: {
    alias: [
      networkAlias(),
      { find: "@", replacement: fileURLToPath(new URL("./src", import.meta.url)) },
    ],
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
