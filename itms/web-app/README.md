# TRAFFIX Command Center

Traffic-operations dashboard for the ITMS platform — live traffic, anomaly
detection, traffic management and emergency response in one operator interface.

Built to `Traffix_Command_Center_Claude_Code_Plan.docx`, one build phase at a time.

## Stack

Vite · React 18 · TypeScript (strict) · Tailwind CSS · Zustand · Framer Motion ·
lucide-react · React Router · MapLibre GL (raster OpenStreetMap tiles, no API key)
· Vitest.

## Commands

```bash
npm install       # once
npm run dev       # dev server on http://localhost:5173
npm run build     # typecheck + production build
npm run lint      # eslint
npm run typecheck # tsc, no emit
npm test          # vitest run (data-layer mappers + store reducers)
```

The dev server proxies `/api` and `/ws` to the ITMS `api-service` on
`http://localhost:8000`. Set the top-bar **Data** toggle to **Live** to read the
WebSocket, or **Sim** for the self-contained in-browser mock.

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
  data/         bundled Vijayawada corridor network (network.ts + geojson)
  hooks/ utils/
```

Feature build history is tracked with the backend in the repo's `PROGRESS.md`
and `docs/interactive-emergency-response.md`. Analytics is a deliberate
placeholder; every other workspace is built.
