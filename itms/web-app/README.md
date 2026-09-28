# TRAFFIX Command Center

Traffic-operations dashboard for the ITMS platform — live traffic, anomaly
detection, traffic management and emergency response in one operator interface.

TRAFFIX / Urban Intelligence: a map-first command center with an operator inbox,
emergency tracking, road and signal intelligence, and measured session analytics.
Architecture review and design decisions: [`../docs/command-center-experience.md`](../docs/command-center-experience.md).

## Stack

Vite · React 18 · TypeScript (strict) · Tailwind CSS · Zustand · Framer Motion ·
lucide-react · React Router · MapLibre GL (CARTO dark raster basemap with
OpenStreetMap attribution) · Vitest · Playwright.

## Commands

```bash
npm install       # once
npm run dev       # dev server on http://localhost:5173
npm run build     # typecheck + production build
npm run lint      # eslint
npm run typecheck # tsc, no emit
npm test          # vitest run (data-layer mappers + store reducers)
npm run test:e2e  # builds + tests production preview, desktop/mobile Chrome
```

The browser suite uses locally installed Google Chrome (`channel: chrome`).
Alternatively install a Playwright browser and change the channel in
`playwright.config.ts`. Screenshots and failure traces go to gitignored
`test-results/`. Browser stream/API fixtures test frontend behavior; they are
not a substitute for the backend Redis/SUMO integration tests.

The dev server proxies `/api` and `/ws` to the ITMS `api-service` on
`http://localhost:8000`. Set the top-bar **Data** toggle to **Live** to read the
WebSocket, or **Demo** for the self-contained in-browser mock. Demo is explicitly
read-only: commands cannot reach the real backend until Live is selected and the
socket is connected. Incident review uses the existing protected REST endpoint;
the operator supplies an API key per review, which is never stored.

Session analytics retains up to 30 minutes of actual received observations in
memory, with selectable windows and CSV export. Changing data source resets the
history. Missing speed stays missing rather than being displayed as zero.

## Layout

```
src/
  app/          route tree, per-workspace pages (Dashboard, Traffic, Anomalies,
                Emergency, Analytics, Settings), nav config
  components/
    layout/     AppShell, SideNav, TopBar, ConnectionPill
    ui/         primitives — button, badge, stat-tile, status-dot, skeleton, …
    map/        TrafficMap + imperative MapLibre layers (roads, vehicles, signals,
                anomalies, emergency route / vehicle / corridor) + panels
    panels/     ActivityFeed
  store/        Zustand — systemStore, mapStore, incidentStore, trafficStore, emergencyStore
  services/traffic/  data layer — mock provider, live WebSocket provider,
                     wsMappers (pure, unit-tested), TrafficDataBridge, commands
  types/        domain models
  data/         adapter importing the canonical scenario GeoJSON at build time
  hooks/ utils/
```

## Deployment boundaries

`npm run build` produces `dist/`. Serve it with an SPA fallback to `index.html`
for all six routes. A production reverse proxy must route `/api/*` to api-service
with the `/api` prefix removed, and `/ws/*` to that service with `/ws` removed,
including WebSocket Upgrade headers and a suitable idle timeout. Vite's dev
proxy is not a production server. `VITE_API_BASE` and `VITE_WS_URL` can instead
point at an explicitly configured service at build time; never put API keys in
Vite variables (they become public bundle contents).

Remote tiles and Google Fonts require network access. System fonts and bundled
road/vehicle overlays still work if those resources are unavailable; WebGL is
required for the map. Preserve OSM/CARTO attribution and review the tile provider's
usage terms/capacity before deploying publicly.

This interface does not make the backend safe for public deployment: command
endpoints still need production authentication/authorization, incident state is
in-memory, the M6 model needs training/accuracy validation, camera ingestion is
not implemented, and historical KPI endpoints do not exist. Signal colors in
Live mean recent controller activity, not individual lamp phases. The UI does
not expose safety timing edits or bypass the arbitration ladder.

Feature build history is tracked in `../PROGRESS.md` and
`../docs/interactive-emergency-response.md`.
