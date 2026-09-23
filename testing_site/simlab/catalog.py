"""Static catalogues: what to verify, what to benchmark, what to demonstrate.

Three lists the site renders as interactive panels.

**Milestones** mirror the repo's own `README.md` milestone map and its
"Current milestone" section, including the parts that are honestly not done.
The point of showing them here is that the checklist and the tool that tests
them are the same screen: each row says what to run and what you should see,
and records the verdict you observed against the run that produced it.

**Gates** are the repo's own offline scripts. They are not reimplemented --
the site shells out to the exact file under `itms/scripts/`, with the repo's
own interpreter, and streams its output. Times are rough and machine-dependent.

**Demos** are step programs the browser executes against the live stack. They
issue exactly the same commands a person would click, which is the point: a
scripted demo that took a private shortcut would prove nothing.
"""

from __future__ import annotations

from simlab import network, paths

MILESTONES = [
    {
        "id": "M0",
        "title": "Skeleton + event bus",
        "claim": "A producer can publish through the shared bus, a consumer reads it back, and it reaches a browser over the api-service WebSocket.",
        "repo_status": "done",
        "how": "Start Redis and api-service, then watch the Event log. `SystemHeartbeat` and the traffic topics arriving at all is this milestone.",
        "verify": "Stream connects and events tick in.",
        "section": "log",
    },
    {
        "id": "M1",
        "title": "SUMO adapter + traffic state",
        "claim": "Real simulated traffic streams at 1 Hz as VehiclePositionUpdated / ApproachState.",
        "repo_status": "done",
        "how": "Start any run. Open Live map -- vehicles should move. Open Traffic for per-edge occupancy and queue counts.",
        "verify": "Vehicles move on the map; per-edge occupancy is non-zero and changes.",
        "section": "map",
    },
    {
        "id": "M2",
        "title": "Safety kernel (L0 interlocks)",
        "claim": "Every commanded phase passes I1-I7. A plan that would truncate min-green or skip a clearance interval is rejected and the junction falls back.",
        "repo_status": "done",
        "how": "Run with controller = Fixed-time, then watch Signals. `interlock_violations` must stay 0 for the whole run, and every phase change must carry a source. Rejections (if any) appear as `signal.faulted` with `interlock_rejected`.",
        "verify": "interlock_violations = 0 and no unexplained faults.",
        "section": "signals",
    },
    {
        "id": "M3",
        "title": "Baselines + KPI harness (Webster)",
        "claim": "Tuned Webster timings per junction from measured link flows, scored on person-delay / throughput / wait / stops.",
        "repo_status": "done",
        "how": "Run the same demand level under Fixed-time and under Webster, then compare them in KPIs & runs.",
        "verify": "Webster shows lower person-delay than fixed-time on the same demand.",
        "section": "kpis",
    },
    {
        "id": "M4",
        "title": "CA-MP Layer 1",
        "claim": "Max-pressure control. The repo reports this loses to Webster and is superseded by M5.",
        "repo_status": "superseded",
        "how": "Run controller = CA-MP (M4) against Webster on the same demand and seed.",
        "verify": "Reproduces the repo's honest negative result rather than beating Webster.",
        "section": "kpis",
    },
    {
        "id": "M5",
        "title": "A-CA-MP (adaptive, with memory)",
        "claim": "Beats tuned Webster at light demand, ties at medium, and beats it by 12.1% at heavy demand after the protect_allocated_green fix.",
        "repo_status": "done",
        "how": "Run Webster and A-CA-MP at the same demand and the same seed, three times over (light / medium / heavy), and compare. Note that the site's runs are cold-started -- no warmed demand-memory profile -- so expect the gate's numbers to be better than these.",
        "verify": "A-CA-MP <= Webster on person-delay, most clearly at heavy demand.",
        "section": "kpis",
    },
    {
        "id": "M6",
        "title": "Anomaly detection (incident spotting)",
        "claim": "Graph autoencoder + conformal alert threshold + incident state machine, with ADR-006's human gate.",
        "repo_status": "built, model undertrained",
        "how": "The pipeline is wired here and the human gate is live on the Incidents screen, but no trained model ships in this checkout -- so the detector is a documented no-op and raises nothing. The run's status reports exactly that. To exercise the gate itself, use the repo's own `m6_incident_injection_gate` under Gates.",
        "verify": "Detector status reads 'inactive (no trained model)' -- which is the honest state, not a site bug. Confirm/reject buttons work the moment a candidate exists.",
        "section": "incidents",
    },
    {
        "id": "M7",
        "title": "Green corridor + dispatch",
        "claim": "EV travel time -3.5% to -4.3%, time loss -25% to -31%, stops -31% to -46% against reactive preemption, with no measurable cost to cross traffic. Contribution-1 pressure terms are an honest negative result.",
        "repo_status": "done, verified",
        "how": "Emergency screen: dispatch a unit, calculate a route, activate the green corridor. Watch Signals for phase changes with source `corridor_preemption`, and the corridor chips releasing as the vehicle clears each junction.",
        "verify": "Corridor arms, EV drives, `corridor_preemption` appears in the signal source column, junctions release in route order, request reaches Completed.",
        "section": "emergency",
    },
    {
        "id": "M7+",
        "title": "Interactive closed loop",
        "claim": "Operator anomaly injection actually changes SUMO; the emergency router is anomaly-aware; a moving vehicle re-routes continuously with cooldown and minimum-progress gates.",
        "repo_status": "done",
        "how": "Run the 'Closed loop' guided demo, or do it by hand: inject a High lane blockage, watch traffic slow on that edge in Traffic, then drop a Blocked anomaly ahead of a moving EV.",
        "verify": "Edge mean speed drops after injection; the request shows an auto-reroute within ~3 s and the route redraws from the vehicle's position.",
        "section": "emergency",
    },
    {
        "id": "M8",
        "title": "Vision on real footage",
        "claim": "YOLO detection on CCTV, homography to the ground plane.",
        "repo_status": "not started",
        "how": "Nothing to test. The VISION anomaly source exists in the domain model; nothing produces it.",
        "verify": "N/A -- expected to be absent.",
        "section": None,
    },
    {
        "id": "API",
        "title": "api-service catching up to M6/M7",
        "claim": "M1 streaming and M6 incidents are implemented. M7 corridor/dispatch REST endpoints are not built.",
        "repo_status": "partial",
        "how": "Everything the site drives goes through `POST /v1/commands` onto the bus, because the dedicated dispatch/routing/corridor endpoints do not exist yet. Incidents use the real `GET /v1/incidents` and `POST /v1/incidents/{id}/confirm|reject`.",
        "verify": "Commands publish and are drained (see the run's commands_drained counter); incident confirm/reject return 200.",
        "section": "incidents",
    },
]

GATES = [
    {
        "id": "m5_gate_comparison",
        "script": "m5_gate_comparison.py",
        "title": "M5 gate -- A-CA-MP vs Webster",
        "blurb": "The headline comparison across demand levels with paired seeds. This is the run behind the 12.1% heavy-demand claim.",
        "runtime": "several minutes, many SUMO processes",
        "heavy": True,
    },
    {
        "id": "m4_gate_comparison",
        "script": "m4_gate_comparison.py",
        "title": "M4 gate -- CA-MP vs baselines",
        "blurb": "M4's own gate. Reproduces the negative result that motivated M5.",
        "runtime": "several minutes",
        "heavy": True,
    },
    {
        "id": "m7_corridor_benchmark",
        "script": "m7_corridor_benchmark.py",
        "title": "M7 corridor benchmark",
        "blurb": "Green corridor vs field-standard reactive preemption: EV travel time, time loss, stops, and cross-street cost.",
        "runtime": "several minutes",
        "heavy": True,
    },
    {
        "id": "m6_incident_injection_gate",
        "script": "m6_incident_injection_gate.py",
        "title": "M6 incident-injection gate",
        "blurb": "Injects incidents on a schedule and measures detection recall and latency. Needs the [anomaly] extra and a trained model; reports honestly when they are missing.",
        "runtime": "minutes",
        "heavy": True,
    },
    {
        "id": "bench",
        "script": "bench.py",
        "title": "M3 baseline bench",
        "blurb": "Three tuned baseline controllers x 10 seeds with 95% confidence intervals.",
        "runtime": "30 SUMO runs, a few minutes",
        "heavy": True,
    },
    {
        "id": "smoke_live_anomaly",
        "script": "smoke_live_anomaly.py",
        "title": "Smoke -- operator anomaly path",
        "blurb": "Publishes an anomaly command, runs the live loop briefly, reads the stream back and asserts the expected events. Fast sanity check that the command path works end to end.",
        "runtime": "under a minute",
        "args": ["light"],
        "heavy": False,
    },
    {
        "id": "smoke_live_corridor",
        "script": "smoke_live_corridor.py",
        "title": "Smoke -- emergency + green corridor",
        "blurb": "Same idea for the dispatch path: asserts corridor_preemption decisions, vehicle movement and GREEN_CORRIDOR_ACTIVE.",
        "runtime": "under a minute",
        "args": ["light"],
        "heavy": False,
    },
    {
        "id": "smoke_live_reroute",
        "script": "smoke_live_reroute.py",
        "title": "Smoke -- continuous re-routing",
        "blurb": "Drops a blocking anomaly ahead of a moving EV and asserts the automatic re-route fires.",
        "runtime": "under a minute",
        "args": ["light"],
        "heavy": False,
    },
    {
        "id": "smoke_full_e2e",
        "script": "smoke_full_e2e.py",
        "title": "Smoke -- full end to end",
        "blurb": "The broadest smoke script in the repo.",
        "runtime": "a minute or two",
        "heavy": False,
    },
]


# `itms_domain.incident.IncidentClass` / `IncidentState`, mirrored rather than
# imported: this module has to work before the repo's virtualenv exists, and
# importing the domain package would need it. If the enum ever gains a member,
# api-service rejects an unknown one with an explicit 422 that the site shows
# verbatim, so a drift here is loud rather than silent.
INCIDENT_CLASSES = ["stall", "lane_block", "debris", "wrong_way", "queue_spillback", "unknown"]
INCIDENT_STATES = ["candidate", "confirmed", "rejected", "expired", "cleared"]


def gate_by_id(gate_id: str) -> dict | None:
    for g in GATES:
        if g["id"] == gate_id:
            path = paths.SCRIPTS_DIR / g["script"]
            return {**g, "path": str(path), "present": path.exists()}
    return None


def gates() -> list[dict]:
    out = []
    for g in GATES:
        path = paths.SCRIPTS_DIR / g["script"]
        out.append({**g, "path": str(path), "present": path.exists()})
    return out


def demos() -> list[dict]:
    """Guided sequences, with edges resolved from the actual network so they
    keep working if the corridor is ever rebuilt."""
    pair = network.suggest_pair()
    origin, destination = pair["origin"], pair["destination"]
    mid = pair["mid_edge"] or destination
    ahead = pair["ahead_edge"] or mid

    return [
        {
            "id": "first-light",
            "title": "First light -- is anything alive?",
            "summary": "Bring the stack up, run light traffic for a minute, and confirm the three things everything else depends on: vehicles move, signals are being commanded by the controller, and no interlock was violated.",
            "duration": "~2 min",
            "steps": [
                {"kind": "note", "text": "Starting Redis and api-service.", "wait_s": 1},
                {"kind": "ensure_stack"},
                {
                    "kind": "start_run",
                    "label": "demo: first light",
                    "config": {
                        "demand": "light",
                        "controller": "acamp",
                        "realtime_factor": 3.0,
                        "max_steps": 400,
                    },
                },
                {"kind": "goto", "section": "map"},
                {
                    "kind": "wait_until",
                    "what": "vehicles_moving",
                    "timeout_s": 90,
                    "text": "Waiting for the first vehicles to enter the corridor.",
                },
                {"kind": "note", "text": "Vehicles are moving. That is M1.", "wait_s": 3},
                {"kind": "goto", "section": "signals"},
                {
                    "kind": "wait_until",
                    "what": "signal_changed",
                    "timeout_s": 60,
                    "text": "Waiting for the first commanded phase change.",
                },
                {
                    "kind": "note",
                    "text": "Phase changes are arriving with a source. The arbitration ladder is live and the safety kernel is checking every plan -- that is M2 plus the controller you picked.",
                    "wait_s": 5,
                },
                {"kind": "goto", "section": "kpis"},
                {"kind": "note", "text": "Let it finish; KPIs are scored from tripinfo at the end.", "wait_s": 2},
            ],
        },
        {
            "id": "closed-loop",
            "title": "The closed loop -- accident, reroute, green corridor",
            "summary": "The documented end-to-end story: live traffic, an operator anomaly that actually changes the simulation, an anomaly-aware route, a green corridor through real signal preemption, a forced re-route, and a clean arrival.",
            "duration": "~5 min",
            "steps": [
                {"kind": "ensure_stack"},
                {
                    "kind": "start_run",
                    "label": "demo: closed loop",
                    "config": {"demand": "light", "controller": "acamp", "realtime_factor": 2.0},
                },
                {"kind": "goto", "section": "map"},
                {"kind": "wait_until", "what": "vehicles_moving", "timeout_s": 90},
                {
                    "kind": "note",
                    "text": "Step 2 of the loop: an operator marks an anomaly. This is not a map decoration -- it changes the lane's max speed in SUMO through TraCI, so traffic really slows and the router really sees it.",
                    "wait_s": 5,
                },
                {
                    "kind": "anomaly",
                    "payload": {
                        "edge_id": mid,
                        "anomaly_type": "LANE_BLOCKAGE",
                        "severity": "HIGH",
                        "duration_s": 600,
                    },
                },
                {"kind": "goto", "section": "anomalies"},
                {"kind": "wait_until", "what": "anomaly_active", "timeout_s": 30},
                {"kind": "note", "text": "Anomaly ACTIVE. Watch the edge's mean speed fall in Traffic.", "wait_s": 6},
                {
                    "kind": "note",
                    "text": "Step 3: dispatch. The route is scored by the six-term cost model -- travel time, congestion, anomaly, signal delay, disruption, reliability -- and it can explain itself.",
                    "wait_s": 5,
                },
                {"kind": "goto", "section": "emergency"},
                {
                    "kind": "dispatch",
                    "payload": {
                        "vehicle_kind": "AMBULANCE",
                        "source_edge": origin,
                        "destination_edge": destination,
                    },
                },
                {"kind": "wait_until", "what": "route_ready", "timeout_s": 60},
                {"kind": "note", "text": "Route ready, with its cost breakdown. Now the green corridor.", "wait_s": 4},
                {"kind": "corridor"},
                {"kind": "wait_until", "what": "corridor_active", "timeout_s": 60},
                {
                    "kind": "note",
                    "text": "Corridor armed and the vehicle spawned. Signal plans with source corridor_preemption are being proposed at rung 3 -- and still checked by the same interlocks, so a plan that would truncate min-green is rejected rather than forced.",
                    "wait_s": 8,
                },
                {
                    "kind": "note",
                    "text": "Step 5: force a re-route. Dropping a Blocked anomaly on a road ahead of the moving vehicle.",
                    "wait_s": 4,
                },
                {
                    "kind": "anomaly",
                    "payload": {
                        "edge_id": ahead,
                        "anomaly_type": "ACCIDENT",
                        "severity": "BLOCKED",
                        "duration_s": 300,
                    },
                },
                {"kind": "wait_until", "what": "reroute", "timeout_s": 60, "optional": True},
                {
                    "kind": "note",
                    "text": "If the blocked road was on the remaining route, the request shows an auto-reroute and the corridor re-arms around the new path. If it was not, nothing should happen -- which is also correct.",
                    "wait_s": 8,
                },
                {"kind": "wait_until", "what": "request_completed", "timeout_s": 300, "optional": True},
                {"kind": "note", "text": "Arrival: corridor terminated, signals back to normal control, request Completed, audit chain intact.", "wait_s": 4},
            ],
        },
        {
            "id": "controller-ab",
            "title": "A/B -- Webster vs A-CA-MP at heavy demand",
            "summary": "Runs the same heavy-demand scenario twice on the same seed, once under the tuned M3 baseline and once under the project's own M5 controller, then opens the comparison.",
            "duration": "~6 min at 20x",
            "steps": [
                {"kind": "ensure_stack"},
                {
                    "kind": "note",
                    "text": "Run 1 of 2: tuned Webster, heavy demand, seed 42, no live map pacing so it finishes quickly.",
                    "wait_s": 3,
                },
                {
                    "kind": "start_run",
                    "label": "A/B: webster heavy",
                    "config": {
                        "demand": "heavy",
                        "controller": "webster",
                        "realtime_factor": 0,
                        "seed": 42,
                        "max_steps": 1800,
                    },
                },
                {"kind": "goto", "section": "kpis"},
                {"kind": "wait_until", "what": "run_finished", "timeout_s": 1800},
                {"kind": "note", "text": "Run 2 of 2: A-CA-MP, identical scenario and seed.", "wait_s": 3},
                {
                    "kind": "start_run",
                    "label": "A/B: acamp heavy",
                    "config": {
                        "demand": "heavy",
                        "controller": "acamp",
                        "realtime_factor": 0,
                        "seed": 42,
                        "max_steps": 1800,
                    },
                },
                {"kind": "wait_until", "what": "run_finished", "timeout_s": 1800},
                {"kind": "compare_last", "n": 2},
                {
                    "kind": "note",
                    "text": "Two runs on one seed are two samples, not a result -- the repo's gate does 30 paired seeds with confidence intervals. Use Gates for a number worth defending.",
                    "wait_s": 6,
                },
            ],
        },
        {
            "id": "od-throughput",
            "title": "Manual demand -- can 60 vehicles get through?",
            "summary": "Puts a specific number of vehicles on one road, sends them all to another, and measures how many actually arrive against the target you set. Then repeats it with an accident in the way.",
            "duration": "~4 min",
            "steps": [
                {"kind": "ensure_stack"},
                {
                    "kind": "start_run",
                    "label": "OD: 60 clean",
                    "config": {
                        "demand": "custom",
                        "controller": "acamp",
                        "realtime_factor": 5.0,
                        "seed": 42,
                        "od": {
                            "origin": origin,
                            "destination": destination,
                            "count": 60,
                            "target_arrivals": 60,
                            "depart_window_s": 240,
                            "background": "light",
                        },
                    },
                },
                {"kind": "goto", "section": "control"},
                {
                    "kind": "note",
                    "text": "The arrivals-vs-target counter on this screen is the answer. It counts vehicles that actually reached the destination edge in SUMO.",
                    "wait_s": 6,
                },
                {"kind": "wait_until", "what": "run_finished", "timeout_s": 1200},
                {"kind": "note", "text": "Clean baseline recorded. Now the same demand with the corridor obstructed.", "wait_s": 4},
                {
                    "kind": "start_run",
                    "label": "OD: 60 with accident",
                    "config": {
                        "demand": "custom",
                        "controller": "acamp",
                        "realtime_factor": 5.0,
                        "seed": 42,
                        "od": {
                            "origin": origin,
                            "destination": destination,
                            "count": 60,
                            "target_arrivals": 60,
                            "depart_window_s": 240,
                            "background": "light",
                        },
                    },
                },
                {"kind": "wait_until", "what": "vehicles_moving", "timeout_s": 90},
                {
                    "kind": "anomaly",
                    "payload": {
                        "edge_id": mid,
                        "anomaly_type": "ACCIDENT",
                        "severity": "HIGH",
                        "duration_s": 900,
                    },
                },
                {"kind": "wait_until", "what": "run_finished", "timeout_s": 1200},
                {"kind": "compare_last", "n": 2},
                {
                    "kind": "note",
                    "text": "Same demand, same seed, one obstruction. The delta in arrivals and person-delay is what the accident cost.",
                    "wait_s": 6,
                },
            ],
        },
    ]
