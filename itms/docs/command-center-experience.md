# TRAFFIX / Urban Intelligence

## Architecture review

The product lives in `web-app`, not the legacy Leaflet pages in `web` or the separate `testing_site` process supervisor. Preserve React 18, TypeScript, Vite, Zustand, MapLibre, Framer Motion and the existing emergency/anomaly command panels.

Data flows from SUMO/TraCI through `run_controlled_scenario`, Avro EventEnvelopes and Redis Streams into FastAPI's `/v1/stream`; the frontend provider normalizes events at 500 ms into shared traffic, incident, emergency and system stores. Commands use `/v1/commands`, then `commands.operator`, then live simulation handlers. HTTP publication is not simulation acknowledgement; state changes arrive on the stream. Incident review uses the separate API-key-protected `/v1/incidents/{id}/confirm|reject` human gate.

Algorithms inspected: fixed-time/Webster baselines, A-CA-MP pressure and adaptive memory, the safety arbitration ladder, graph/conformal incident detection, normalized six-term emergency route costs and alternative path planning, green-corridor reservations/preemption, and the current incident-response orchestration. Safety decisions remain backend-owned; no UI directly sets a green phase.

The current live command runner selects its strategy through `load_corridor`; the benchmark/default SUMO runner and interactive live runner are not interchangeable. Do not label every live run A-CA-MP. Signal colors currently represent recent controller activity, not per-movement lamp truth. Nearby-vehicle queue/speed statistics are frontend spatial estimates.

Existing UI: six routed workspaces, split anomaly/traffic view, notification history, map layers, request selection, route explanations/alternatives, source/destination picking, corridor activation and cancellation. Analytics was a placeholder. Missing `src/data/network` prevented building the checkout; restore it using the actual checked-in GeoJSON.

## Product decisions

- **Command center:** editorial overview, explicit source/freshness, four primary KPIs, dominant live map, incident inbox, emergency mission summary, road conditions and signal health. Every drill-down uses existing shared stores/routes.
- **Traffic:** full map plus searchable roads and junction observations; keyboard-operable lists offer an alternative to pointer-only map selection.
- **Anomalies:** retain real injection/clearing, add detector incident review using existing REST contracts. Demo cannot mutate the backend.
- **Emergency:** retain integrated dispatch, multi-unit routes, cost explanations, rerouting and green-corridor lifecycles; improve responsive workspace layout rather than duplicate the engine.
- **Analytics:** bounded in-memory session observations, selectable time windows, actual congestion/speed/vehicle trends and CSV export. Never fabricate historical KPIs or benchmark improvements.
- **Settings:** source/layer controls and an honest capability guide. No editable safety thresholds.

## Visual system

Midnight ink, slightly raised navy cards, mint primary actions, amber disruptions, red critical faults and blue routing. Strong typographic hierarchy with Jakarta Sans and tabular Plex Mono telemetry. Thin borders, quiet gradients, generous spacing, modest entrance transitions and reduced-motion support. Maps use a dark raster basemap with mandatory provider attribution; bundled network overlays remain available independently of remote tiles.

## Known production boundaries

This is still a local simulation platform: command endpoints lack production authorization, incidents are an in-memory registry, the M6 model is not accuracy-gate ready, M8 camera/vision is not implemented, cumulative corridor preemption budgeting has a documented backend gap, and there is no historical analytics API. A polished frontend does not remove these deployment gates. No invented uptime, prediction accuracy, camera feeds or incident detections.

## Verification scope

Observed in this implementation session:

- `npm run build`, `npm run lint`, `npm run typecheck`: passed. Vite still warns about the MapLibre vendor chunk exceeding 500 kB (approximately 803 kB minified / 217 kB gzip); the warning is not suppressed.
- `npm test`: **124 tests passed** across 15 files. Includes restored real-network geometry, no-data/cadence/retention/CSV analytics, incident normalization, malformed WebSocket frames, stale telemetry and demo command isolation.
- `npm run test:e2e`: **8 passed**, running the production build in Chrome at 1440×1000 and 390×844. Covers all six routes, map layers, road search, keyboard-selectable dispatch points, demo command rejection, incident confirmation, stale stream behavior, CSV downloads, blocked tile requests, navigation focus restoration and reduced-motion CSS. Overview screenshots are in `web-app/test-results/overview-desktop.png` and `overview-mobile.png`.
- Backend `.venv/bin/pytest -q -rs` with `RUN_INTEGRATION_TESTS=1` and a dedicated temporary local Redis: **542 passed, 4 skipped**. The skip reasons identify four optional M6 test modules requiring NumPy; those model tests remain **unverified**. Initially the entire backend suite could not collect because the installed Starlette required `httpx2`; installing that test dependency in the existing virtualenv allowed the real suite to run. No backend dependency files or algorithms were changed.
- Browser live-mode tests use controlled WebSocket/REST fixtures. Backend Redis/SUMO integration is checked separately by the repository tests; a full browser → API → SUMO emergency mission was **not** exercised in this session. No statistical benchmark or M6 accuracy claim is made.

Environment provisioning for additional model tests can be defined in `.gitlab/duo/agent-config.yml` (install the project's optional anomaly dependencies). Public deployment, comprehensive assistive-technology audits and cross-browser testing beyond Chrome remain separate acceptance work.

Browser verification found and fixed: parent-before-child map disposal breaking route navigation, unstable Zustand v5 array selectors causing an emergency-roster render loop, and an expanded legend blocking dispatch controls on mobile. A dev-only dependency-optimization refresh also interrupted one run; the final suite deliberately tests the production build rather than relying on the dev optimizer.
