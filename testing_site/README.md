# ITMS Test Lab

A manual test harness for the platform in `../itms/`. You set up the traffic,
press start, and watch every feature the system is supposed to perform — with
the numbers coming out of the project's own KPI code rather than out of this
tool.

```bash
cd testing_site
./start.sh            # opens http://127.0.0.1:8420
```

Nothing to install for the site itself: the control server is Python standard
library only, so it runs before `itms/.venv` exists and its first job is to
tell you what is missing.

---

## It does not touch `itms/`

`itms/` is read-only to this tool. It parses the network, the demand files, the
facilities list and the gate results; it imports the packages; it runs the
scripts. It never writes a byte inside it.

Everything generated lives in `testing_site/var/` — per-run scenario files,
`tripinfo.xml`, run history, logs, the saved API key. Deleting `var/` loses your
run history and nothing else.

## What is yours and what is this tool's

This matters more than anything else here, because a test harness that quietly
does the work itself proves nothing.

**Yours, imported and not reimplemented:** the arbitration ladder
(`signal_controller/arbiter.py`), the Layer-0 interlocks, `run_controlled_scenario`,
all four controllers (fixed-time, Webster, CA-MP, A-CA-MP), the operator-anomaly
controller, the dynamic emergency router and its six-term cost model, the green
corridor engine, the M6 live detector, `control.metrics` for the KPIs, the Avro
event contracts, `api-service` itself.

**This tool's:** process supervision, the custom origin→destination scenario
generator, a per-tick status file, the screens, and the run history. Plus one
pre-flight shortest-path routine used only to check an origin/destination pair
before a run starts, so the form can refuse an impossible pair without needing
the virtualenv; the routing *in* the simulation is always yours.

Every operator action goes through `POST /v1/commands` on `api-service` — the
one way into the simulation. There is no private channel. If a command works
here it works from `curl`, and if it fails, the Avro schema rejected it.

---

## The five minutes that answer "how far has it come"

1. **Control room → Stack:** *Start bus + API*.
2. Pick **Light traffic**, controller **A-CA-MP**, press **Start run**.
3. **Live corridor:** vehicles should be moving within a few seconds. That is M1.
4. **Signals & safety:** phase changes arriving with a source rung, and
   `interlock violations` at 0. That is M2 plus your controller.
5. **Anomaly injection:** drop a *High* lane blockage; watch that edge's mean
   speed fall in **Traffic state**. The anomaly is applied to the lane in SUMO
   over TraCI — it is not a marker.
6. **Emergency response:** dispatch, read the route explanation, activate the
   green corridor. `corridor_preemption` appears in the Signals source column
   and the junction chips release in route order. That is M7.
7. **KPIs & runs:** run the same thing under **Webster** and compare.

**Milestone check** has all of this as a checklist, one row per milestone,
including the ones the repo honestly reports as unfinished.

---

## The screens

| Screen | What it is for |
|---|---|
| **Control room** | Start/stop Redis, `api-service` and the simulation. Choose the traffic, the controller, the speed and the seed. Live counters while it runs, scored KPIs when it ends. |
| **Guided demos** | Scripted sequences that click the same buttons you would — including the full closed loop (accident → auto-reroute → green corridor → arrival) and a Webster vs A-CA-MP A/B. |
| **Gates & benchmarks** | Runs the repo's own scripts under `itms/scripts/` with the repo's own interpreter, streaming their output. Also browses the JSON already in `scripts/results/`. |
| **Live corridor** | The map: roads coloured by load, vehicles by class, signals by which rung commanded them, anomalies, the emergency route, corridor reservations and the moving unit. Click a road to use it in any form. |
| **Signals & safety** | Per-junction live phase and source rung, the arbitration ladder with live decision counts, preemptions granted, plans the interlocks rejected, and faults. |
| **Traffic state** | Per-edge vehicles, occupancy, halted count, mean speed and arrival rate. Sortable. |
| **Event stream** | Every event `api-service` relays, decoded. Filter by type, search, click a line for the full payload. Vehicle positions and approach state are hidden by default because they are a firehose. |
| **Anomaly injection** | Create and clear operator anomalies, with the severity → SUMO-effect mapping spelled out. |
| **Emergency response** | Dispatch a unit, read *why* the router chose that path (weighted cost breakdown, alternatives, reliability), arm the corridor, force a recalculation, watch automatic re-routes. |
| **Incident gate** | ADR-006's human-in-the-loop gate: confirm or reject a raised candidate. |
| **KPIs & runs** | Run history, side-by-side comparison, JSON/CSV export. |
| **Milestone check** | M0–M8 against what the repo claims, how to test each one here, and your own recorded verdict. |
| **Settings** | What was found on this machine, the API key, and the site self-test. |

---

## Manual traffic

**Light / Medium / Heavy** are the repo's own checked-in demand files
(`randomTrips.py` at period 5.0 / 2.5 / 1.25, roughly 354 / 708 / 1416 vehicles
over 30 minutes). Nothing is regenerated.

**Custom O→D** is the fourth option the repo has no file for: *N vehicles on
this road, all heading for that one, over this background level*. It writes a
fresh SUMO route file into the run's own directory, referencing the repo's
network by absolute path, with the same four vehicle types and the same
`occupancy` / `pcu` parameters as `assign_vtypes.py` — which is what keeps a
custom run's person-delay comparable to a preset run's.

You also set a **target arrivals** number. The runner counts, tick by tick, how
many of those vehicles actually reached the destination edge, and the Control
room shows arrived-vs-target with a verdict. If your release rate is above what
one approach can physically discharge, the form says so before you start rather
than letting you read a queue as a failure.

## Controllers

| Option | What it is |
|---|---|
| **A-CA-MP (M5)** | Your adaptive controller. Cold-started here — no warmed demand-memory or calibration profile — so expect the gate's numbers to be better than these. |
| **Webster (M3)** | The tuned baseline, built exactly as `scripts/m5_harness.build_webster` builds it. |
| **CA-MP (M4)** | Superseded, kept so its honest negative result stays reproducible. |
| **Fixed-time (M2)** | Ring at min-green. The proven-safe floor, not a competitor. |

## Engines

- **Test-lab runner** (default) — `runner/simlab_run.py`. Your control stack plus
  four things the repo's entry point has no reason to carry: a controller flag,
  custom demand, a live status file, and `tripinfo` KPI scoring.
- **Repo entrypoint: `SIM_MODE=live`** — `sim_service.main`, untouched. Webster,
  no KPI scoring, no custom demand. Use it to confirm the site is not the thing
  making it work.
- **Repo entrypoint: `SIM_MODE=sumo`** — the default A-CA-MP demo path, untouched.
  No operator command handling.

The repo entry points write no status file, so the Control room counters stay
empty on those runs. The map and the event stream still work.

---

## Reading the numbers honestly

- Live counters are the simulation's own ground truth, read over TraCI each tick.
- End-of-run KPIs are scored from SUMO's `tripinfo` through the repo's
  `control.metrics`, with the same 600 s warm-up the gate scripts use.
- **Two runs are two samples, not a result.** Different seeds move these numbers
  on their own. For a claim worth defending, use **Gates** — those scripts run
  paired seeds with confidence intervals.
- **M6 raises nothing**, because no trained model ships in this checkout. The
  pipeline is wired and the human gate is live, and the run status says exactly
  that. It is the repo's own reported state, not a fault in the site.
- **M7's corridor engine is not in the repo's own live demo.** It is reachable
  here because this runner wires `CorridorController` as the arbiter's rung-3
  proposal source, the same way `sim_service.live.service` does.

---

## When something does not start

The Control room banner lists what is missing before you can run. In practice
it is one of:

| Symptom | Fix |
|---|---|
| "No virtualenv in the repo" | `cd ../itms && make setup` |
| "Demand files missing" | `scenarios/demand/vijayawada/build_demand_levels.sh`, then `assign_vtypes.py` on each new `.rou.xml` |
| Bus will not start | Docker Desktop is not running, or install nothing and start your own `redis-server` |
| Confirm/reject returns 401 | `api-service` is running with a different key. **Settings → Restart api-service with this tool's key** |
| A screen stays empty and you cannot tell whose fault it is | **Settings → Run a 3-minute self-test.** It publishes a synthetic stream through the real schemas onto the real bus and answers operator commands. If the screens fill in, the page and `api-service` are fine and the problem is in the simulation. It runs no SUMO and no control logic and produces no KPIs — never read a number off it. |

The simulation's own log is at the bottom of the Control room; `api-service` and
Redis logs are on the Settings screen.

---

## Layout

```
testing_site/
├── start.sh                  # ./start.sh
├── server.py                 # control server: static files, API, process supervision
├── simlab/
│   ├── paths.py              # where everything is; what this checkout can and cannot do
│   ├── network.py            # the corridor, parsed from the repo's GeoJSON + net.xml
│   ├── scenario.py           # custom origin→destination demand generation
│   ├── procs.py              # process supervision + health probes
│   ├── runs.py               # run history, comparison, export
│   └── catalog.py            # milestones, gate scripts, demo programs
├── runner/
│   ├── simlab_run.py         # the real simulation runner (imports itms/)
│   └── selftest_stream.py    # synthetic stream — tests this site, not your platform
├── static/                   # the site (vanilla ES modules, no build step)
└── var/                      # generated: runs, logs, scenarios, saved API key
```

### Options

`./start.sh` passes flags through to `server.py`:

```
--port 8420          # the site
--api-port 8000      # where api-service listens
--redis-url redis://localhost:6379/0
--no-browser         # do not open a browser window
```

Environment: `ITMS_REPO` points the site at a checkout somewhere other than
`../itms` (handy if your working copy lives elsewhere). `ITMS_API_KEY` fixes the
`X-API-Key` value. `SIMLAB_VERBOSE=1` logs every HTTP request.

It binds `127.0.0.1` and it starts processes and reads files on this machine.
It is a local development tool — do not expose it to a network.
