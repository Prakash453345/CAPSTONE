/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** api-service base path. Defaults to `/api` (Vite proxies it to :8000 in dev). */
  readonly VITE_API_BASE?: string;
  /** Full WebSocket URL to the api-service stream. Defaults to `/ws/v1/stream` on the current host. */
  readonly VITE_WS_URL?: string;
  /** Google Maps Platform key with the Map Tiles API enabled. */
  readonly VITE_GOOGLE_MAPS_API_KEY?: string;
  /** Legacy basemap tile key retained from local edits. Never commit key values. */
  readonly VITE_MAP_API_KEY?: string;
  /** Map start centre, `"lat,lon"`. Defaults to the Vijayawada corridor. */
  readonly VITE_MAP_CENTER?: string;
  /** Which SUMO network the console is built against (see network.config.ts). */
  readonly VITE_ITMS_NETWORK?: "corridor" | "district";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
