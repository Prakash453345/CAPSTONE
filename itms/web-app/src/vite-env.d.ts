/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** api-service base path. Defaults to `/api` (Vite proxies it to :8000 in dev). */
  readonly VITE_API_BASE?: string;
  /** Full WebSocket URL to the api-service stream. Defaults to `/ws/v1/stream` on the current host. */
  readonly VITE_WS_URL?: string;
  /** Google Maps Platform key with the Map Tiles API enabled. Unset = CARTO basemap. */
  readonly VITE_GOOGLE_MAPS_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
