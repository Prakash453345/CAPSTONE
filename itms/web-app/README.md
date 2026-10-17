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

## Cities (Vijayawada and Amaravati)

`npm run dev` shows both cities on one map: Vijayawada's MG Road corridor and
the real Amaravati map (`scenarios/generated/amaravati_v2/`, 121 signals),
about 15 km apart. To show only one, set `VITE_CITY` (`vijayawada` or
`amaravati`), on the command line or in a git-ignored `.env.local`:

```bash
VITE_CITY=amaravati npm run dev
```

Vijayawada's network is bundled; Amaravati's (~400 KB) is a separate file the
app fetches once at startup, so it stays out of every page's JavaScript
(`scripts/check-bundle-budget.mjs`). That uses top-level await, hence
`build.target: "es2022"`.

The backend simulates one city at a time (Vijayawada unless
`ITMS_SCENARIO=$PWD/scenarios/generated/amaravati_v2 make dev`), so in Live mode
only that city has vehicles; Demo mode animates both. To add a city, export its
georeferenced SUMO network with `python scenarios/networks/vijayawada/export_geojson.py
<net.xml> <out.geojson>` and list it in `src/data/city.ts` and `src/data/network.ts`.
The Amaravati export carries no street names (its OSM build kept none), so its
roads are labelled by class ("Primary road"). Emergency depots, hospitals and
camera sites are still Vijayawada's only.

## Crew page (emergency-vehicle crews)

`/drive` is the page an ambulance, fire or police crew follows on the road. It
sits behind the same sign-in as the console and reads the same live data, so
what the dispatcher sees and what the crew sees agree. Choose your unit (it
picks the first one with a call if you have not) and it shows:

- **Next instruction**: a large turn banner with the distance, built from the
  edges of the route the system dispatched (`src/drive/plan.ts`).
- **Signals ahead**: each signal still on the route and whether the green
  corridor is *holding* it for you, is *clearing* it as you approach, or it is
  just red/amber/green or faulted (`src/drive/situation.ts`). A fault outranks
  everything, and a signal that is not held for you is flagged as approximate.
- **On your route**: blocked or disrupted roads, heavy traffic, signal faults,
  other emergency units sharing the road, and a weather note.
- **Trip bar**: arrival time, time and distance left, speed, and a progress bar,
  with the full list of directions, voice on/off, and **New route** (sends the
  same `RECALCULATE` command dispatchers use; Live mode only).
- Spoken guidance (500 m / 200 m / 60 m before each turn, critical hazards,
  signals held or not safe to run, a changed route, arrival), the screen kept
  awake while driving, a banner when the connection drops, and an off-route
  warning. Everything works on a phone: the panels become a band along the
  bottom and the map follows the vehicle.

In the browser Demo it follows the simulated ambulance (`amb-01`). The
vehicle's position and route come from the data provider, not the device's
GPS. Logic lives in `src/drive/` (pure, unit-tested); UI in
`src/components/drive/` and `src/app/drive/`.

## Layout

```
src/
  app/          route tree, per-workspace pages (Dashboard, Traffic, Anomalies,
                Emergency, Analytics, Settings), nav config, login, drive
  drive/        guidance engine for the Drive page (route plan, turns, signal
                and hazard status, voice cues) and its hooks
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
