# Astra Master Prompt — ITMS Command Centre Website

Copy everything below into Astra.

---

You are the principal product designer and senior frontend engineer for a world-class intelligent mobility platform. Design and build an extraordinary, production-quality website and operator command centre for **ITMS — Intelligent Traffic Management & Emergency Response Platform**.

This must feel like an original, premium product created by a top-tier global technology company: Apple-level editorial clarity, Amazon-level operational confidence and information architecture, and a modern mission-control product experience. Do not imitate, copy, or reference any brand’s visual identity. Create an original visual system.

## Primary goal

Create a complete, polished digital product experience that makes the following story immediately clear:

> ITMS sees changing traffic conditions, detects possible incidents, keeps a human decision-maker in control, routes emergency responders intelligently, and safely prepares a green corridor while protecting normal road users.

The site must have two connected experiences:

1. **Public product site** — an exceptional, cinematic, credible presentation of the platform, research, safety model, and measurable impact.
2. **Operator Command Centre** — a sophisticated live dashboard where an operator can see traffic, investigate anomalies, create or confirm incidents, dispatch an emergency unit, observe a route, activate a green corridor, and monitor recovery.

The Command Centre is the hero product. It must not look like a generic admin template, a cryptocurrency dashboard, a toy smart-city mockup, or a collection of unrelated cards.

## Existing project — preserve and extend

This project already has a frontend application. Extend it rather than creating a disconnected second application.

Existing stack:

- Vite + React 18 + TypeScript in strict mode
- Tailwind CSS
- Zustand state stores
- Framer Motion
- MapLibre GL
- React Router
- lucide-react icons
- Vitest

Existing frontend structure:

```text
web-app/
  src/app/                 # Dashboard, Traffic, Anomalies, Emergency, Analytics, Settings routes
  src/components/layout/   # AppShell, SideNav, TopBar, ConnectionPill
  src/components/map/      # TrafficMap, MapLibre layers, legend, controls, command panels
  src/components/panels/   # Activity feed and action bar
  src/services/traffic/    # WebSocket provider, mock provider, command client, event mappers
  src/store/               # traffic, incident, emergency, map, system, notification stores
```

Do not remove the existing live-data architecture. Improve the UI/UX, create missing visual experiences, and preserve clean component boundaries.

## Product truth — do not fabricate claims

The platform is a capstone/research implementation using a real SUMO model of the Vijayawada, India corridor. It is not a deployed city traffic-control system. Use language such as **simulation**, **pilot corridor**, **operator workspace**, **research-validated scenario**, and **safety-constrained control**. Never claim that the system is deployed in a real city or currently controls live public infrastructure.

### What the project actually does

- **M1 live traffic state:** SUMO/TraCI provides moving vehicles and approach occupancy on a real Vijayawada network.
- **M2 safety kernel:** signal decisions are checked against hard interlocks: conflicting greens, minimum green, clearance, pedestrian clearance, maximum wait, preemption budget, legal transitions, and controller read-back behavior.
- **M5 A-CA-MP adaptive control:** adaptive, downstream-aware signal control with queue state, memory, fairness, spillback prevention, calibration, and safe fallback behavior.
- **M6 anomaly detection:** graph/pattern-based anomaly detection creates incident candidates; a human operator must confirm or reject an incident. The pipeline is built, but the trained detector is still a proof-of-training model and should not be presented as fully accurate.
- **M7 emergency dispatch and green corridor:** chooses an appropriate facility/route, can react to anomalies and reroute, and reserves safe signal movements for authorised emergency vehicles through the existing safety/arbiter layer.
- **Interactive simulation:** an operator can create an anomaly that physically changes the SUMO simulation, dispatch an emergency response, activate a green corridor, force a reroute by blocking a road ahead, and observe arrival/recovery.

### Important honest limitations to show elegantly

- Human confirmation remains required before a candidate becomes an actionable incident.
- The anomaly detector is not yet trained to its final accuracy target.
- The system should show **simulation / live demo** state clearly.
- Safety logic is a hard constraint, not a metric to trade away for speed.
- Dashboard claims must use live data when available, mock data only when the user explicitly selects simulation mode.

## Backend and live-data contract

The frontend reads event envelopes from:

```text
WebSocket: /v1/stream
Development proxy: /ws -> http://localhost:8000/v1/stream
```

The API also supports incident data and protected human-gate actions:

```text
GET  /v1/incidents
GET  /v1/incidents/{id}
POST /v1/incidents/{id}/confirm
POST /v1/incidents/{id}/reject
POST /v1/commands
```

The current event stream may include:

```text
SystemHeartbeat
VehiclePositionUpdated
ApproachState
SignalChanged
SignalFaulted
IncidentCandidate
IncidentDetected
IncidentUpdated
AnomalyUpdated
EmergencyRequestUpdated
EmergencyVehicleUpdated
GreenCorridorUpdated
EmergencyDispatched
```

Use the existing typed WebSocket mappers and stores. Do not parse event JSON directly inside presentation components. All incoming events must remain normalised in the services/store layer.

## Visual direction

### Brand personality

Use a visual personality that is:

- precise, calm, reliable, intelligent, and high-trust;
- cinematic but never loud or gimmicky;
- sophisticated enough for a city operations centre;
- humane enough to communicate emergency response and public safety;
- technically credible without looking cold or bureaucratic.

### Design system

Use a premium dark command-centre system as the operational environment:

- Background: near-black graphite / midnight navy, never pure black everywhere.
- Layered surfaces: deep slate panels with subtle elevation and fine border contrast.
- Primary active color: electric cyan / arctic blue for live telemetry and interaction.
- Safe/healthy: restrained emerald green.
- Attention: intelligent amber.
- Critical incident: controlled red/coral, used sparingly.
- Emergency corridor / response: violet or electric magenta as a distinct but restrained semantic layer.
- Typography: clean modern sans-serif for interface; tabular/monospace face for IDs, times, telemetry, and metrics.
- Use a disciplined 4/8px spacing rhythm, a defined radius scale, and carefully balanced panel density.
- Avoid gratuitous gradients, over-rounded cards, glassmorphism everywhere, neon overload, stock “AI” imagery, fake charts, and excessive icon usage.

For the public product pages, move to a lighter, editorial product presentation with white/soft-gray surfaces, deep ink text, high-quality dark maps/visualisations, and limited use of the operational cyan accent. The transition between public site and command centre should feel intentional.

### Motion and rendering quality

Motion is mandatory, but every animation must communicate state, hierarchy, or cause and effect.

- Build a cinematic hero with a generative corridor/network animation: thin route lines, signal nodes, vehicles as moving points, and a single emergency-response path becoming visible.
- Animate dashboard panels on entry with short staggered transitions (150–300ms), not slow spectacle.
- Animate live vehicle positions smoothly along map paths.
- Animate route rerouting as a path redraw, not a hard flash.
- Animate corridor reservations with a subtle pulse travelling ahead of the emergency vehicle.
- Animate anomaly creation as a focused locator/ripple and not an alarming explosion.
- Use animated counters only when values change.
- Use skeleton states while the map or stream is loading.
- Respect `prefers-reduced-motion`: remove non-essential movement, preserve state changes, and never make the interface harder to use.
- Use GPU-friendly transforms/opacity and avoid expensive perpetual layout animations.

## Public site information architecture

Create these sections/pages with excellent storytelling and navigation.

### 1. Home / Landing page

Hero structure:

- Small status label: `SAFETY-CONSTRAINED TRAFFIC INTELLIGENCE`
- Headline: `Traffic that responds before the city has to ask.`
- Supporting copy: Explain detection, human confirmation, dispatch, and safe corridor control in plain language.
- Primary CTA: `Enter Command Centre`
- Secondary CTA: `Explore the system`
- Hero visual: an interactive/animated abstract map of the Vijayawada pilot corridor. On interaction, show a traffic anomaly, verified incident, dispatched unit, and protected corridor as a concise story.

Below hero:

- A three-step timeline: **Understand → Decide → Clear the way**.
- A live/simulated status strip with transparent labels such as `7 signalised junctions`, `simulation connected`, `human-gated incident workflow`, and `safety interlocks active`.
- A full-width narrative section explaining that the system is designed to make decisions explainable, not just automatic.

### 2. Platform / How it works

Build a premium scrollytelling architecture diagram that reveals in sequence:

```text
Traffic & sensors → event stream → anomaly candidate → human confirmation
→ dispatch and route → safe green corridor → recovery and audit
```

Each stage must have a concise explanation, real event names as technical detail, and a clear boundary between automated recommendation and human authority.

### 3. Safety by design

Create a visually exceptional safety page. Make it one of the best parts of the website.

Show the “safety gate” as a layered decision system:

```text
Emergency / manual authority
        ↓
Adaptive optimisation
        ↓
L0 safety interlocks
        ↓
Signal cabinet read-back
```

Explain, in readable language, that no algorithm can bypass conflicting-green prevention, clearance intervals, pedestrian protection, maximum wait bounds, or hardware-fault fallback. Use an interactive “decision rejected / safe fallback” demonstration rather than vague safety marketing.

### 4. Research and results

Build a sober, credible research page. Do not make false “best in market” claims.

Include:

- Vijayawada simulation overview
- comparison methodology: paired seeds, test scenarios, safety gate
- adaptive control / A-CA-MP explanation
- emergency-corridor evaluation
- clear badges: `Measured`, `Under evaluation`, `Simulation only`, `Human approval required`
- a results chart component that can show data honestly, including confidence intervals and negative findings
- a section titled `What we are still proving` for detector accuracy, wider-network validation, and field deployment work

### 5. Technology / Architecture

Show the event-driven system architecture: SUMO, Redis Streams, API service, WebSocket, MapLibre frontend, incident state machine, routing, signal controller, and safety interlocks. Use clean vector diagrams built in HTML/SVG/CSS—not a pasted screenshot.

### 6. Call to action / Demo access

Provide a polished entry point to the command centre and a small “Run the demo” section with developer/operator steps. Keep it secondary to the product narrative.

## Operator Command Centre

The operator console must feel like a real system used during traffic operations. It should be responsive, dense without being cramped, keyboard-aware, and calm under pressure.

### Global application shell

Desktop:

- Narrow left navigation rail with icon + label expansion on hover/focus.
- Top bar with corridor name, current simulation/live mode, connection state, clock, notification bell, and user/operator context.
- Persistent live connection pill: `Live`, `Reconnecting`, `Simulation`, `Stale`, or `Offline`.
- Avoid a huge page title occupying dashboard space.

Mobile/tablet:

- Use responsive stacked panels and a bottom navigation pattern.
- Preserve map interaction and core emergency actions.
- Never hide critical state merely to fit the viewport.

### Dashboard route

Make this the most impressive view.

Layout:

```text
Top operational KPI strip
Large live traffic map                  Right-side operational rail
  ├─ vehicle/signal/anomaly layers        ├─ active incidents
  ├─ traffic heat / occupancy              ├─ active emergency response
  ├─ emergency route/corridor              ├─ corridor status
  └─ map controls                          └─ live activity feed
Bottom analysis band
  ├─ traffic flow / congestion trend
  ├─ safety and signal status
  └─ queue / approach health
```

KPIs must include only useful information:

- active vehicles
- corridor congestion / busiest links
- signals online and safe
- candidate incidents requiring review
- active emergency requests
- stream freshness / event rate

Avoid made-up business metrics. When no live state is available, show a polished empty state explaining how to start live mode or activate simulation mode.

### Map behavior

The map is the core UI, not background decoration.

Build on the existing MapLibre integration and real Vijayawada corridor geometry.

Layers and semantics:

- roads: low-traffic slate → cyan/amber/red based on occupancy/congestion;
- vehicles: small, efficient symbols, optionally distinguish car, bike, auto-rickshaw, bus, and emergency vehicle;
- signalised intersections: subtle state indicators; do not suggest an unsafe green if state is unknown;
- anomalies: severity-specific markers and affected-edge halo;
- incident candidates: visually distinct from confirmed incidents;
- emergency route: high-contrast violet/cyan route line;
- green corridor reservations: progressive, time-aware highlighted junctions ahead of the emergency unit;
- route reroute: animate old route fading into a new route and display the reason;
- hover/click: show a compact, useful inspector, not an oversized popup.

Map controls:

- zoom, fit corridor, layer visibility, map theme, and “follow emergency unit” mode;
- a clear map legend that is collapsible but never ambiguous;
- tooltip and keyboard access for all map information;
- map interaction must remain smooth with many markers.

### Anomalies workspace

Build an anomaly and incident-review workflow:

- timeline/queue on the left, map in the center, detail inspector on the right;
- filters for severity, status, source, time, and confidence;
- a real human-gate interaction for candidate incidents: **Confirm** and **Reject** require an operator identity/reason UI;
- prominent distinction: candidate ≠ confirmed incident;
- “Create anomaly” flow for simulation mode: click a road, choose type/severity/duration, preview impact, submit;
- use optimistic UI only when the command is sent, then reconcile with event stream state.

### Traffic workspace

Show network flow with a systems-engineering lens:

- corridor heat map
- top congested approaches
- signal health
- phase/occupancy relationship
- movement-level queues where available
- trend charts with time-window controls
- current controller mode: A-CA-MP / fallback / preemption / degraded
- explicit warnings if telemetry is stale or derived metrics are low confidence

### Emergency workspace

This must feel exceptionally polished and practical.

Provide a guided operator workflow:

1. Select a confirmed incident or create a simulation response.
2. Select response type/unit and origin/destination.
3. Show route alternatives with ETA, distance, route cost, anomalies avoided, predicted signal delay, and reliability.
4. Let the operator calculate/dispatch the preferred route.
5. Show green-corridor activation with a visible safety/preemption status at each junction.
6. During movement, show unit location, ETA, route progress, upcoming intersection, reservations, and re-route explanation.
7. On completion, show a dignified incident timeline and recovery summary.

Do not use “green corridor” merely as a green decorative line. It must visually communicate planned, held, cleared, deferred, and released junction reservations.

### Analytics workspace

Build a meaningful, presentation-ready analytics experience:

- select time period and scenario
- person-delay / travel-time / stops / throughput / wait-time cards
- compare controller arms honestly where data exists
- confidence intervals and result status
- anomaly/incident response timeline
- green-corridor outcome metrics: ETA reduction, emergency stops, cross-street wait, reservation releases
- export-ready table layout
- include a `Research notes` panel for assumptions and limits

Do not fabricate performance data. The mock provider may supply clearly labelled scenario data. Live metrics must come from the stream or be labelled as unavailable.

### Settings workspace

Design a serious operational configuration page:

- data mode: Live / Simulation
- connection diagnostics
- map layers
- notification preferences
- read-only safety configuration summary
- user/operator identity
- no unsafe “disable safety” control

## Component, engineering, and interaction rules

- Use React + TypeScript strict mode; no `any`.
- Keep domain behavior in services/stores, visual state in components, and map-layer rendering in map modules.
- Reuse and improve existing primitives (`Button`, `Badge`, `StatTile`, `StatusDot`, `Tooltip`, `Skeleton`).
- Use Framer Motion with typed variants and `prefers-reduced-motion` support.
- Use semantic HTML, labelled buttons, live regions for important alerts, visible focus rings, and WCAG AA contrast.
- Provide loading, empty, error, stale-data, reconnecting, and permission-denied states for every live-data workflow.
- All command actions require clear confirmation affordances and a visible success/failure result.
- Use realistic names, times, and data states. Never invent a production deployment, operator, hospital assignment, or safety certification.
- Avoid giant UI libraries and unnecessary dependencies. Use existing libraries first.
- Keep desktop performance excellent; use memoisation/selectors for high-frequency traffic updates and efficient MapLibre source updates.
- Ensure no visual layout shifts when telemetry updates.
- Build tests for WebSocket mapping, stores, emergency route/corridor status, and important pure utility functions.
- Run TypeScript typecheck, lint, build, and tests before declaring completion.

## Deliverables

Deliver the enhanced `web-app` as a coherent, runnable application, including:

1. Full visual design system and responsive application shell.
2. Public-facing product pages and complete command-centre routes.
3. High-fidelity MapLibre traffic/emergency visualisation using existing network data.
4. Live WebSocket integration preserved, with an explicit in-browser simulation mode.
5. Purposeful animations, empty/loading/error states, accessibility, and performance safeguards.
6. A concise README describing architecture, local run steps, available data modes, and how to demonstrate the anomaly → dispatch → corridor → reroute flow.
7. No placeholder-looking pages. If a backend value is not yet available, create an elegant truthful state rather than fake data.

## Definition of done

The product is done only when it feels like a single exceptional system, not a landing page attached to an unrelated dashboard. A first-time viewer should understand the public-safety mission in under 15 seconds. An operator should be able to understand traffic state, respond to an anomaly, and follow an emergency corridor without needing documentation. A reviewer should see technical depth, visual polish, safety discipline, and research honesty in the same experience.

---
