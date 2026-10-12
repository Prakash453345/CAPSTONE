# TRAFFIX — Intelligent Traffic Management & Emergency Response

Adaptive signal control, incident detection and emergency-vehicle green
corridors for Vijayawada, run against a SUMO digital twin, with an operator
console on top.

## Structure

```
CAPSTONE/
├── frontend/      React + TypeScript + Vite operator console (TRAFFIX Command Center)
├── backend/       Python services, shared libraries, event contracts, data, ML, experiments
│   ├── services/  api-gateway · simulation-service · vision-service
│   ├── libs/      domain · common · geo
│   └── ...        contracts/, data/, ml/, experiments/, infra/, scripts/
├── docs/          progress log, design write-ups, plans, reports, research, archive
└── .github/       CI: frontend.yml, backend.yml
```

The services talk only through the event bus (Redis Streams) using the Avro
contracts in `backend/contracts/events/`; the console talks only to the
api-gateway (REST + one WebSocket). Details: [backend/README.md](backend/README.md),
[frontend/README.md](frontend/README.md).

## Run it locally

```powershell
# backend (from backend/, first time: see backend/README.md for the venv setup)
powershell -File scripts\dev-local.ps1 -WithVision
# console (from frontend/)
npm install
npm run dev        # http://localhost:5173
```

API: http://localhost:8000 (interactive docs at `/docs`).

## Documentation

| | |
|---|---|
| [docs/PROGRESS.md](docs/PROGRESS.md) | the full build log, milestone by milestone, negative results included |
| [docs/project_status_report.md](docs/project_status_report.md) | plain-language status of every milestone |
| [docs/](docs/) | design write-ups: green corridor, hazard catalogue, dispatch, vision, incident pipeline |
| [docs/plans/](docs/plans/) | M6 anomaly-detection plans |
| [docs/reports/](docs/reports/), [docs/research/](docs/research/) | reports and research notes |
| [docs/archive/](docs/archive/) | superseded tools kept for reference: the static web demo, the sim test lab |

## Where things moved (October 2026 restructure)

Everything used to live under `itms/`. File history follows the moves
(`git log --follow`).

| Before | Now |
|---|---|
| `itms/web-app/` | `frontend/` |
| `itms/services/api-service/` (`api_service`) | `backend/services/api-gateway/` (`api_gateway`) |
| `itms/services/sim-service/` | `backend/services/simulation-service/` (package still `sim_service`) |
| `itms/services/vision-service/` | `backend/services/vision-service/` |
| `itms/packages/{common,domain,geo}/` | `backend/libs/{common,domain,geo}/` |
| `itms/contracts/` | `backend/contracts/` |
| `itms/scenarios/` | `backend/data/scenarios/` |
| `itms/data/models/` | `backend/data/models/` |
| `itms/notebooks/` | `backend/ml/notebooks/` |
| `itms/scripts/` (experiments) | `backend/experiments/` |
| `itms/scripts/{dev.sh,dev-local.ps1,wait-for-healthy.sh}` | `backend/scripts/` |
| `itms/baselines/`, `bench/`, `cases/` | `backend/experiments/` |
| `itms/docker-compose.yml`, `infra/` | `backend/infra/` |
| `itms/docs/`, `PROGRESS.md`, `*.docx` | `docs/`, `docs/plans/` |
| `reports/`, `research_notes/` | `docs/reports/`, `docs/research/` |
| `itms/web/`, `testing_site/`, `astra-handoff/` | `docs/archive/` |

Older documents and notebooks still mention the old paths; they are
historical records and were left as written. Use the table above to translate.
