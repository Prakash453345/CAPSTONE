import { fileURLToPath, URL } from "node:url";

/**
 * Which SUMO network the console is built against. It must match the network
 * the live sim-service runs (SIM_NETWORK), because road and junction ids come
 * from the network file.
 *
 *   corridor  the single MG Road arterial (default; what the tests describe)
 *   district  the surrounding arterial grid, where emergency routes compete
 *
 * Set VITE_ITMS_NETWORK=district for `npm run dev` / `npm run build`. Only the
 * chosen network's geometry is bundled.
 */
const NETWORKS = ["corridor", "district"] as const;
export type ItmsNetwork = (typeof NETWORKS)[number];

export function itmsNetwork(): ItmsNetwork {
  const value = process.env.VITE_ITMS_NETWORK ?? "corridor";
  if (!(NETWORKS as readonly string[]).includes(value)) {
    throw new Error(`VITE_ITMS_NETWORK must be one of ${NETWORKS.join(", ")}, got "${value}"`);
  }
  return value as ItmsNetwork;
}

/**
 * Alias entry for the chosen network's GeoJSON, imported as
 * `@itms-network?raw`. A regex, because a plain string alias only matches the
 * bare id or `id/...`, never `id?raw`.
 */
export function networkAlias(): { find: RegExp; replacement: string } {
  return {
    find: /^@itms-network(?=\?|$)/,
    replacement: fileURLToPath(
      new URL(`../backend/data/scenarios/networks/vijayawada/vijayawada_${itmsNetwork()}.geojson`, import.meta.url),
    ),
  };
}
