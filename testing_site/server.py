#!/usr/bin/env python3
"""ITMS Test Lab -- local control server.

    python3 server.py            # then open http://127.0.0.1:8420

Standard library only, on purpose: this has to be runnable before the repo's
virtualenv exists, so that the first thing it can do is tell you what is
missing. It serves the site, supervises the stack (Redis, api-service, the
simulation, one gate script at a time), generates custom scenarios, keeps the
run history, and proxies the two api-service calls that need an API key.

It is a localhost development tool. It binds 127.0.0.1, and it will start
processes and read files on this machine -- do not expose it to a network.

Nothing under `itms/` is ever written. Everything this tool generates lives in
`testing_site/var/`.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from simlab import catalog, network, paths, procs, runs, scenario  # noqa: E402

DEFAULT_PORT = 8420
DEFAULT_API_PORT = 8000
DEFAULT_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

def _load_or_make_api_key() -> tuple[str, str]:
    """One key per installation, not per process.

    `api-service` checks `X-API-Key` on the two incident actions
    (`POST /v1/incidents/{id}/confirm|reject`) -- and it generates its own
    random key when `API_KEY` is unset. `POST /v1/commands` (the live
    operator-control layer -- anomalies, emergency dispatch, corridor
    activation) is deliberately left unauthenticated in the real service, on
    the same footing as the `/v1/stream` WebSocket; this key is still sent on
    every `/api/commands` relay call below (harmless -- an unauthenticated
    endpoint just ignores a header it doesn't check) in case that changes. If
    this server generated a fresh key on every start, restarting it while
    api-service kept running would silently break confirm/reject -- so the key
    is persisted beside the run history and reused.
    """
    env = os.environ.get("ITMS_API_KEY")
    if env:
        return env, "env"
    paths.ensure_var_dirs()
    key_path = paths.VAR_DIR / "api_key"
    try:
        existing = key_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing, "saved"
    except OSError:
        pass
    key = secrets.token_urlsafe(24)
    try:
        key_path.write_text(key + "\n", encoding="utf-8")
        key_path.chmod(0o600)
    except OSError:
        pass
    return key, "generated"


_API_KEY, _API_KEY_SOURCE = _load_or_make_api_key()
STATE = {
    "api_key": _API_KEY,
    "api_key_source": _API_KEY_SOURCE,
    "active_run": None,  # run id
}


class Lab:
    def __init__(self, *, api_port: int, redis_url: str):
        paths.ensure_var_dirs()
        self.stack = procs.Stack(
            redis_url=redis_url, api_port=api_port, api_key=STATE["api_key"]
        )
        self.store = runs.RunStore()
        self.command_log: list[dict] = []
        self.lock = threading.Lock()

    # -- bootstrap ---------------------------------------------------------
    def bootstrap(self) -> dict:
        net = network.corridor()
        return {
            "repo": paths.repo_status(),
            "network": {
                "edges": net["edges"],
                "edge_order": net["edge_order"],
                "junctions": net["junctions"],
                "traffic_lights": net["traffic_lights"],
                "adjacency": net["adjacency"],
                "bounds": net["bounds"],
                "center": net["center"],
                "counts": {
                    "edges": net["n_edges"],
                    "junctions": net["n_junctions"],
                    "traffic_lights": net["n_traffic_lights"],
                },
            },
            "facilities": network.facilities(),
            "suggested": network.suggest_pair(),
            "milestones": catalog.MILESTONES,
            "gates": catalog.gates(),
            "demos": catalog.demos(),
            "controllers": [
                {
                    "id": "acamp",
                    "label": "A-CA-MP (M5)",
                    "note": "The project's own adaptive controller. Cold-started here: no warmed demand-memory profile.",
                },
                {
                    "id": "webster",
                    "label": "Webster (M3)",
                    "note": "Tuned fixed-time baseline from measured link flows. The thing M5 has to beat.",
                },
                {
                    "id": "camp",
                    "label": "CA-MP (M4)",
                    "note": "Superseded. Kept so its honest negative result is reproducible.",
                },
                {
                    "id": "fixed_time",
                    "label": "Fixed-time (M2)",
                    "note": "Ring at min-green. Proven always-safe by property test; the floor, not a competitor.",
                },
            ],
            "engines": [
                {
                    "id": "testlab",
                    "label": "Test-lab runner",
                    "note": "Repo control stack + KPI scoring, custom demand, live status. Needed for anything on this site's Control screen.",
                },
                {
                    "id": "repo_live",
                    "label": "Repo entrypoint: SIM_MODE=live",
                    "note": "sim_service.main untouched. Webster, no KPI scoring, no custom demand -- use it to confirm the site is not the thing making it work.",
                },
                {
                    "id": "repo_sumo",
                    "label": "Repo entrypoint: SIM_MODE=sumo",
                    "note": "sim_service.main's default A-CA-MP demo path, untouched. No operator command handling.",
                },
            ],
            "config": {
                "redis_url": self.stack.redis_url,
                "api_port": self.stack.api_port,
                "ws_url": f"ws://{{host}}:{self.stack.api_port}/v1/stream",
                "api_key_source": STATE["api_key_source"],
                "site_dir": str(paths.SITE_DIR),
                "var_dir": str(paths.VAR_DIR),
            },
            # All 5 of these are real (contracts/events/anomaly_create_requested.avsc
            # OperatorAnomalyType): sim_service.live.anomaly_control._TYPE_MAP maps
            # every one of them straight onto itms_domain.anomaly.AnomalyType and
            # applies the same lane-max-speed mutation via TraCI, HEAVY_CONGESTION
            # included -- there is no unmapped/rejected case.
            "anomaly_types": [
                "ACCIDENT",
                "VEHICLE_BREAKDOWN",
                "LANE_BLOCKAGE",
                "ROAD_OBSTRUCTION",
                "HEAVY_CONGESTION",
            ],
            # Severity genuinely changes simulation behaviour --
            # AnomalyImpactConfig in sim_service/live/anomaly_control.py sets a
            # lane's max speed to this fraction of its original value (BLOCKED
            # crawls to ~0.1 m/s instead), and estimated_impact is the 0..1
            # number fed into the emergency router's anomaly-cost term.
            "anomaly_severities": [
                {"id": "LOW", "label": "Low", "note": "lane kept at 70% of its normal speed limit (estimated_impact 0.25)"},
                {"id": "MEDIUM", "label": "Medium", "note": "lane kept at 45% of its normal speed limit (estimated_impact 0.50)"},
                {"id": "HIGH", "label": "High", "note": "lane kept at 20% of its normal speed limit (estimated_impact 0.80)"},
                {"id": "BLOCKED", "label": "Blocked", "note": "lane crawls to ~0.1 m/s -- routing treats it as impassable (estimated_impact 1.0)"},
            ],
            # itms_domain.routing.EmergencyRoutingConfig's own field defaults,
            # copied here as plain literals on purpose -- this server is
            # standard-library only so it can run before `make setup` exists,
            # so it cannot import the dataclass itself. Keep these in sync by
            # hand if that dataclass's defaults ever change.
            "route_cost_weights": [
                {"id": "travel_time_weight", "label": "Travel time", "default": 1.0,
                 "note": "raw seconds of free-flow travel time on the edge"},
                {"id": "congestion_weight", "label": "Congestion", "default": 0.6,
                 "note": "how backed-up the edge is right now"},
                {"id": "anomaly_weight", "label": "Anomaly severity", "default": 1.0,
                 "note": "penalty from any active operator-reported anomaly on the edge"},
                {"id": "signal_delay_weight", "label": "Signal delay", "default": 0.4,
                 "note": "expected wait at the junction the edge feeds, by current phase"},
                {"id": "disruption_weight", "label": "Disruption", "default": 0.5,
                 "note": "penalty scaled by how long the edge is (rerouting a long edge costs more)"},
                {"id": "reliability_weight", "label": "Reliability", "default": 0.3,
                 "note": "penalty for an edge whose recent congestion has been volatile"},
            ],
            "vehicle_kinds": ["AMBULANCE", "FIRE_TRUCK", "POLICE"],
            "incident_classes": catalog.INCIDENT_CLASSES,
            "incident_states": catalog.INCIDENT_STATES,
        }

    # -- status ------------------------------------------------------------
    def status(self) -> dict:
        st = self.stack.status()
        active = STATE["active_run"]
        run_status = self.store.live_status(active) if active else None
        if run_status is None and self.stack.sim.meta.get("engine") == "selftest":
            path = paths.VAR_DIR / "selftest" / "status.json"
            if path.exists():
                try:
                    run_status = json.loads(path.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    run_status = None
        if run_status and run_status.get("state") in ("finished", "stopped", "failed"):
            if not self.stack.sim.running:
                STATE["active_run"] = None
        return {
            "stack": st,
            "active_run_id": active,
            "run": run_status,
            "commands_sent": len(self.command_log),
            "now": time.time(),
        }

    # -- runs --------------------------------------------------------------
    def start_run(self, body: dict) -> dict:
        if self.stack.sim.running:
            return {"ok": False, "reason": "a simulation is already running -- stop it first"}
        if not procs.redis_ping(self.stack.redis_url).get("ok"):
            return {
                "ok": False,
                "reason": "Redis is not reachable. Start the bus first (Control > Stack).",
            }

        demand = body.get("demand", "medium")
        controller = body.get("controller", "acamp")
        engine = body.get("engine", "testlab")
        if controller not in ("acamp", "camp", "webster", "fixed_time"):
            return {"ok": False, "reason": f"unknown controller {controller!r}"}

        # Route-cost weights (itms_domain.EmergencyRoutingConfig's six
        # alpha..zeta terms) -- optional per-run override of how the
        # emergency router weighs travel time vs. congestion vs. anomaly
        # severity vs. signal delay vs. disruption vs. reliability. Only the
        # testlab engine's own runner (simlab_run.py) knows how to apply
        # these; the repo's untouched entry points (repo_live/repo_sumo)
        # always use the repo's own defaults, so sending weights there is
        # rejected rather than silently ignored.
        weight_fields = (
            "travel_time_weight", "congestion_weight", "anomaly_weight",
            "signal_delay_weight", "disruption_weight", "reliability_weight",
        )
        weights_in = body.get("weights") or {}
        weights: dict = {}
        for key in weight_fields:
            val = weights_in.get(key)
            if val in (None, ""):
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                return {"ok": False, "reason": f"route-cost weight {key!r} must be a number"}
            if fval < 0:
                return {"ok": False, "reason": f"route-cost weight {key!r} must be >= 0"}
            weights[key] = fval
        if weights and engine != "testlab":
            return {
                "ok": False,
                "reason": "custom route-cost weights only apply to the testlab engine",
            }

        config = {
            "demand": demand,
            "controller": controller,
            "engine": engine,
            "realtime_factor": float(body.get("realtime_factor", 1.0) or 0),
            "step_length": float(body.get("step_length", 1.0) or 1.0),
            "max_steps": int(body.get("max_steps") or 0),
            "seed": (None if body.get("seed") in (None, "", -1) else int(body["seed"])),
            "warmup_s": float(body.get("warmup_s", 600.0) or 0),
            "weights": weights,
        }

        run = self.store.create(config, label=body.get("label", ""))
        run_dir = Path(run["dir"])

        manifest = None
        if demand == "custom":
            od_in = body.get("od") or {}
            if not od_in.get("origin") or not od_in.get("destination"):
                self.store.delete(run["id"])
                return {"ok": False, "reason": "custom demand needs an origin and a destination edge"}
            spec = scenario.ODSpec(
                origin=od_in["origin"],
                destination=od_in["destination"],
                count=int(od_in.get("count", 40)),
                target_arrivals=od_in.get("target_arrivals"),
                depart_window_s=float(od_in.get("depart_window_s", 300)),
                background=od_in.get("background", "light"),
                mix=od_in.get("mix") or dict(scenario.DEFAULT_MIX),
                seed=int(config["seed"] if config["seed"] is not None else 42),
                duration_s=float(od_in.get("duration_s", 1800)),
            )
            try:
                manifest = scenario.write_scenario(spec, run_dir)
            except ValueError as exc:
                self.store.delete(run["id"])
                return {"ok": False, "reason": str(exc)}
            (run_dir / "scenario.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            config["od"] = {
                k: manifest[k]
                for k in ("origin", "destination", "count", "target_arrivals", "route_edges")
            }
            self.store.annotate(run["id"], label=run["label"])

        env = paths.repo_env({"REDIS_URL": self.stack.redis_url})

        if engine in ("repo_live", "repo_sumo"):
            runner_py = paths.runner_python()
            env.update(
                {
                    "SIM_MODE": "live" if engine == "repo_live" else "sumo",
                    "SIM_DEMAND": demand if demand != "custom" else "medium",
                    "SIM_REALTIME_FACTOR": str(config["realtime_factor"] or 1.0),
                    "SIM_STEP_LENGTH": str(config["step_length"]),
                }
            )
            if config["max_steps"]:
                env["SIM_MAX_STEPS"] = str(config["max_steps"])
            argv = [str(runner_py), "-m", "sim_service.main"]
            note = (
                "Repo entrypoint: no KPI scoring and no live status file, so this "
                "screen's counters stay empty. Watch the Live map and the Event log."
            )
            # The repo entrypoint writes no status file; seed one so the UI can
            # still tell that something is running and say why it is sparse.
            (run_dir / "status.json").write_text(
                json.dumps(
                    {
                        "run_id": run["id"],
                        "state": "running",
                        "engine": engine,
                        "demand": demand,
                        "controller": "acamp (sumo mode)" if engine == "repo_sumo" else "webster (live mode)",
                        "note": note,
                        "started_at": time.time(),
                    }
                ),
                encoding="utf-8",
            )
        else:
            argv = [
                str(paths.runner_python()),
                str(paths.RUNNER_DIR / "simlab_run.py"),
                "--status-file",
                str(run_dir / "status.json"),
                "--run-id",
                run["id"],
                "--controller",
                controller,
                "--realtime-factor",
                str(config["realtime_factor"]),
                "--step-length",
                str(config["step_length"]),
                "--redis-url",
                self.stack.redis_url,
                "--tripinfo",
                str(run_dir / "tripinfo.xml"),
                "--warmup-s",
                str(config["warmup_s"]),
            ]
            if config["max_steps"]:
                argv += ["--max-steps", str(config["max_steps"])]
            if config["seed"] is not None:
                argv += ["--seed", str(config["seed"])]
            for key, val in config["weights"].items():
                argv += [f"--{key.replace('_', '-')}", str(val)]
            if manifest:
                argv += [
                    "--demand",
                    "custom",
                    "--sumocfg",
                    manifest["sumocfg"],
                    "--route",
                    manifest["route"],
                    "--od-manifest",
                    str(run_dir / "scenario.json"),
                ]
                if manifest.get("background_route"):
                    argv += ["--background-route", manifest["background_route"]]
            else:
                argv += ["--demand", demand]

        self.stack.sim.clear_logs()
        res = self.stack.sim.start(
            argv, cwd=paths.REPO, env=env, meta={"run_id": run["id"], "engine": engine}
        )
        if not res.get("ok"):
            self.store.annotate(run["id"], notes=res.get("reason", "failed to start"))
            return res
        STATE["active_run"] = run["id"]
        return {"ok": True, "run": self.store.get(run["id"]), "scenario": manifest}

    def stop_run(self) -> dict:
        res = self.stack.sim.stop()
        return res

    def start_selftest(self, seconds: float = 180.0) -> dict:
        """Publish a synthetic stream instead of running a simulation, to tell
        a broken page apart from a broken backend. Deliberately not recorded as
        a run: it has no KPIs and nothing about it is a measurement."""
        if self.stack.sim.running:
            return {"ok": False, "reason": "stop the simulation first -- both would write to the same topics"}
        if not procs.redis_ping(self.stack.redis_url).get("ok"):
            return {"ok": False, "reason": "Redis is not reachable; the self-test publishes onto the real bus"}
        out = paths.VAR_DIR / "selftest"
        out.mkdir(parents=True, exist_ok=True)
        STATE["active_run"] = None
        argv = [
            str(paths.runner_python()),
            str(paths.RUNNER_DIR / "selftest_stream.py"),
            "--redis-url", self.stack.redis_url,
            "--seconds", str(max(20.0, min(1800.0, float(seconds)))),
            "--status-file", str(out / "status.json"),
        ]
        self.stack.sim.clear_logs()
        res = self.stack.sim.start(
            argv, cwd=paths.SITE_DIR, env=paths.repo_env({"REDIS_URL": self.stack.redis_url}),
            meta={"engine": "selftest", "run_id": None},
        )
        if res.get("ok"):
            self.selftest_status = out / "status.json"
        return res

    # -- commands ----------------------------------------------------------
    def post_command(self, body: dict) -> dict:
        event_type = body.get("event_type")
        payload = dict(body.get("payload") or {})
        if not event_type:
            return {"ok": False, "reason": "event_type is required"}
        raw = json.dumps(
            {"event_type": event_type, "payload": payload, "operator": body.get("operator", "operator:testlab")}
        ).encode()
        res = procs.http_json(
            f"http://127.0.0.1:{self.stack.api_port}/v1/commands",
            method="POST",
            body=raw,
            # Requires X-API-Key, same as incident_decision below -- see
            # this module's docstring for why /v1/commands is protected too.
            headers={"Content-Type": "application/json", "X-API-Key": STATE["api_key"]},
            timeout=4.0,
        )
        entry = {
            "at": time.time(),
            "event_type": event_type,
            "payload": payload,
            "ok": res["ok"],
            "status": res["status"],
            "response": res["body"][:400],
        }
        with self.lock:
            self.command_log.append(entry)
            del self.command_log[:-500]
        if not res["ok"]:
            return {
                "ok": False,
                "status": res["status"],
                "reason": _explain_api_failure(res),
                "detail": res["body"][:600],
            }
        try:
            return {"ok": True, "result": json.loads(res["body"])}
        except ValueError:
            return {"ok": True, "result": res["body"]}

    def incidents(self) -> dict:
        res = procs.http_json(f"http://127.0.0.1:{self.stack.api_port}/v1/incidents")
        if not res["ok"]:
            return {"ok": False, "reason": _explain_api_failure(res), "incidents": []}
        try:
            return {"ok": True, "incidents": json.loads(res["body"])}
        except ValueError:
            return {"ok": False, "reason": "unparseable response", "incidents": []}

    def incident_decision(self, incident_id: str, action: str, body: dict) -> dict:
        if action not in ("confirm", "reject"):
            return {"ok": False, "reason": "action must be confirm or reject"}
        payload = {"actor": body.get("actor") or "operator:testlab", "detail": body.get("detail", "")}
        if action == "confirm":
            payload["classification"] = body.get("classification", "unknown")
        res = procs.http_json(
            f"http://127.0.0.1:{self.stack.api_port}/v1/incidents/{urllib.parse.quote(incident_id)}/{action}",
            method="POST",
            body=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-API-Key": STATE["api_key"]},
            timeout=4.0,
        )
        if not res["ok"]:
            reason = _explain_api_failure(res)
            if res["status"] == 422 and "classification" in res["body"]:
                reason = (
                    "api-service rejected that classification. The allowed set is "
                    "itms_domain.incident.IncidentClass: "
                    + ", ".join(catalog.INCIDENT_CLASSES)
                )
            if res["status"] == 401:
                reason = (
                    "api-service rejected the API key, which means it is running with a "
                    "different one than this tool holds. Easiest fix: Settings -> "
                    "\"Restart api-service with this tool's key\". Otherwise paste the key "
                    "api-service logged on startup into Settings."
                )
            return {"ok": False, "status": res["status"], "reason": reason, "detail": res["body"][:600]}
        try:
            return {"ok": True, "incident": json.loads(res["body"])}
        except ValueError:
            return {"ok": True, "incident": res["body"]}

    # -- gates -------------------------------------------------------------
    def start_gate(self, gate_id: str, extra_args: list[str] | None = None) -> dict:
        gate = catalog.gate_by_id(gate_id)
        if gate is None:
            return {"ok": False, "reason": f"unknown gate {gate_id!r}"}
        if not gate["present"]:
            return {"ok": False, "reason": f"{gate['script']} is not in this checkout"}
        if self.stack.gate.running:
            return {"ok": False, "reason": "a gate script is already running"}
        argv = [str(paths.runner_python()), gate["path"], *(extra_args or gate.get("args") or [])]
        self.stack.gate.clear_logs()
        return self.stack.gate.start(
            argv,
            cwd=paths.REPO,
            env=paths.repo_env({"REDIS_URL": self.stack.redis_url}),
            meta={"gate_id": gate_id, "title": gate["title"]},
        )

    def results_index(self) -> dict:
        """Gate output already in the repo. Read-only: the site never writes
        into scripts/results/, which is the repo's own never-hand-edited
        convention."""
        out = []
        if paths.RESULTS_DIR.is_dir():
            for p in sorted(paths.RESULTS_DIR.rglob("*.json")):
                try:
                    stat = p.stat()
                except OSError:
                    continue
                out.append(
                    {
                        "name": str(p.relative_to(paths.RESULTS_DIR)),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                )
        out.sort(key=lambda r: r["mtime"], reverse=True)
        return {"ok": True, "dir": str(paths.RESULTS_DIR), "files": out}

    def result_file(self, name: str) -> dict:
        target = (paths.RESULTS_DIR / name).resolve()
        if not str(target).startswith(str(paths.RESULTS_DIR.resolve())) or not target.is_file():
            return {"ok": False, "reason": "not a result file"}
        if target.stat().st_size > 4_000_000:
            return {"ok": False, "reason": "file is too large to render here"}
        try:
            return {"ok": True, "name": name, "content": json.loads(target.read_text(encoding="utf-8"))}
        except (ValueError, OSError) as exc:
            return {"ok": False, "reason": str(exc)}


def _explain_api_failure(res: dict) -> str:
    if res["status"] == 0:
        return (
            "api-service is not answering on port "
            f"{LAB.stack.api_port}. Start it from Control > Stack."
        )
    if res["status"] == 400:
        return "api-service rejected the command: no schema in contracts/events/ for that event_type."
    if res["status"] == 422:
        return "api-service rejected the payload: it does not match the event's Avro schema."
    return f"api-service returned HTTP {res['status']}."


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "ITMSTestLab/1.0"
    protocol_version = "HTTP/1.1"

    # -- plumbing ----------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:  # quieter than the default
        if os.environ.get("SIMLAB_VERBOSE"):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, default=str).encode(), "application/json")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            return {}

    def _file(self, path: Path, fallback_ctype: str = "application/octet-stream") -> None:
        if not path.is_file():
            self._json({"ok": False, "reason": f"not found: {path.name}"}, 404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or fallback_ctype
        self._send(200, path.read_bytes(), ctype)

    # -- routes ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        route, q = url.path, urllib.parse.parse_qs(url.query)

        if route in ("/", "/index.html"):
            return self._file(paths.STATIC_DIR / "index.html", "text/html")
        if route.startswith("/static/"):
            rel = route[len("/static/") :]
            target = (paths.STATIC_DIR / rel).resolve()
            if not str(target).startswith(str(paths.STATIC_DIR.resolve())):
                return self._json({"ok": False, "reason": "nope"}, 403)
            return self._file(target)
        if route.startswith("/vendor/leaflet/"):
            rel = route[len("/vendor/leaflet/") :]
            target = (paths.LEAFLET_DIR / rel).resolve()
            if not str(target).startswith(str(paths.LEAFLET_DIR.resolve())):
                return self._json({"ok": False, "reason": "nope"}, 403)
            return self._file(target)

        if route == "/api/bootstrap":
            return self._json(LAB.bootstrap())
        if route == "/api/status":
            return self._json(LAB.status())
        if route == "/api/logs":
            name = (q.get("name") or ["sim"])[0]
            since = int((q.get("since") or ["0"])[0])
            managed = LAB.stack.get(name)
            if managed is None:
                return self._json({"ok": False, "reason": f"unknown log {name!r}"}, 404)
            return self._json({"ok": True, **managed.tail(since)})
        if route == "/api/runs":
            return self._json({"ok": True, "runs": LAB.store.list()})
        if route.startswith("/api/runs/"):
            run_id = route[len("/api/runs/") :]
            run = LAB.store.get(run_id)
            if run is None:
                return self._json({"ok": False, "reason": "unknown run"}, 404)
            return self._json({"ok": True, "run": run, "status": LAB.store.live_status(run_id)})
        if route == "/api/incidents":
            return self._json(LAB.incidents())
        if route == "/api/commands":
            return self._json({"ok": True, "commands": LAB.command_log[-200:]})
        if route == "/api/results":
            return self._json(LAB.results_index())
        if route == "/api/result":
            return self._json(LAB.result_file((q.get("name") or [""])[0]))
        if route == "/api/export.csv":
            ids = [i for i in (q.get("ids") or [""])[0].split(",") if i]
            body = LAB.store.export_csv(ids or None).encode()
            return self._send(
                200,
                body,
                "text/csv",
                {"Content-Disposition": 'attachment; filename="itms-runs.csv"'},
            )
        if route == "/api/export.json":
            ids = [i for i in (q.get("ids") or [""])[0].split(",") if i]
            body = json.dumps(LAB.store.export_json(ids or None), indent=2, default=str).encode()
            return self._send(
                200,
                body,
                "application/json",
                {"Content-Disposition": 'attachment; filename="itms-runs.json"'},
            )

        return self._json({"ok": False, "reason": f"no route {route}"}, 404)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_DELETE(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        if url.path.startswith("/api/runs/"):
            run_id = url.path[len("/api/runs/") :]
            return self._json({"ok": LAB.store.delete(run_id)})
        return self._json({"ok": False, "reason": "no route"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        route = url.path
        body = self._body()

        if route == "/api/stack/start":
            what = body.get("what", "all")
            out = {}
            if what in ("redis", "all"):
                out["redis"] = LAB.stack.start_redis()
            if what in ("api", "all"):
                out["api"] = LAB.stack.start_api()
            return self._json({"ok": all(v.get("ok") for v in out.values()), "detail": out})
        if route == "/api/stack/stop":
            what = body.get("what", "all")
            out = {}
            if what in ("sim", "all"):
                out["sim"] = LAB.stack.sim.stop()
            if what in ("api", "all"):
                out["api"] = LAB.stack.stop_api()
            if what in ("redis", "all"):
                out["redis"] = LAB.stack.stop_redis()
            if what == "gate":
                out["gate"] = LAB.stack.gate.stop()
            return self._json({"ok": True, "detail": out})
        if route == "/api/settings":
            if body.get("api_key"):
                STATE["api_key"] = str(body["api_key"]).strip()
                STATE["api_key_source"] = "pasted"
                LAB.stack.api_key = STATE["api_key"]
            return self._json({"ok": True, "api_key_source": STATE["api_key_source"]})
        if route == "/api/api/restart":
            # Deliberately kills whatever holds the port, not just a child of
            # this process: an api-service started by an earlier run of this
            # tool (or by `make dev`) is exactly the case that needs fixing,
            # and it has a different API key. `kill_port` refuses anything that
            # does not look like api-service.
            LAB.stack.api_key = STATE["api_key"]
            LAB.stack.api.stop()
            killed = procs.kill_port(LAB.stack.api_port)
            if not killed.get("ok"):
                return self._json(killed)
            res = LAB.stack.start_api()
            if not res.get("ok"):
                return self._json(res)
            for _ in range(24):
                if LAB.stack.api_health().get("ok"):
                    return self._json({"ok": True, "detail": killed})
                time.sleep(0.4)
            return self._json({"ok": False, "reason": "api-service did not come back up -- see its log"})

        if route == "/api/scenario/validate":
            spec = scenario.ODSpec(
                origin=body.get("origin", ""),
                destination=body.get("destination", ""),
                count=int(body.get("count", 40) or 40),
                target_arrivals=body.get("target_arrivals"),
                depart_window_s=float(body.get("depart_window_s", 300) or 300),
                background=body.get("background", "light"),
            )
            return self._json(scenario.validate(spec))
        if route == "/api/run/start":
            return self._json(LAB.start_run(body))
        if route == "/api/run/stop":
            return self._json(LAB.stop_run())
        if route == "/api/selftest/start":
            return self._json(LAB.start_selftest(body.get("seconds", 180)))
        if route == "/api/runs/compare":
            return self._json({"ok": True, **LAB.store.compare(body.get("ids") or [])})
        if route.startswith("/api/runs/") and route.endswith("/annotate"):
            run_id = route[len("/api/runs/") : -len("/annotate")]
            run = LAB.store.annotate(run_id, **body)
            return self._json({"ok": run is not None, "run": run})
        if route == "/api/commands":
            return self._json(LAB.post_command(body))
        if route.startswith("/api/incidents/"):
            rest = route[len("/api/incidents/") :]
            incident_id, _, action = rest.rpartition("/")
            return self._json(LAB.incident_decision(incident_id, action, body))
        if route.startswith("/api/gates/") and route.endswith("/start"):
            gate_id = route[len("/api/gates/") : -len("/start")]
            return self._json(LAB.start_gate(gate_id, body.get("args")))
        if route == "/api/gates/stop":
            return self._json(LAB.stack.gate.stop())

        return self._json({"ok": False, "reason": f"no route {route}"}, 404)


LAB: Lab


def free_port(preferred: int) -> int:
    for port in [preferred, *range(preferred + 1, preferred + 20)]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred


def main() -> int:
    global LAB
    ap = argparse.ArgumentParser(description="ITMS Test Lab control server")
    ap.add_argument("--port", type=int, default=int(os.environ.get("SIMLAB_PORT", DEFAULT_PORT)))
    ap.add_argument(
        "--api-port", type=int, default=int(os.environ.get("ITMS_API_PORT", DEFAULT_API_PORT))
    )
    ap.add_argument("--redis-url", default=DEFAULT_REDIS_URL)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    LAB = Lab(api_port=args.api_port, redis_url=args.redis_url)
    port = free_port(args.port)

    repo = paths.repo_status()
    # flush explicitly: stdout is block-buffered when start.sh is piped or run
    # from a launcher, and a banner that appears minutes later is useless.
    banner = [
        "=" * 66,
        " ITMS Test Lab",
        f" site      http://127.0.0.1:{port}",
        f" repo      {repo['repo']}{'' if repo['repo_found'] else '   [NOT FOUND]'}",
        f" network   {'ok' if repo['network_found'] else 'MISSING -- build the scenario first'}",
        f" venv      {repo['venv_python'] or repo.get('venv_problem') or 'MISSING -- run `make setup` in the repo'}",
        f" sumo      {repo['sumo_binary'] or 'not found in the venv (needed to run a simulation)'}",
        f" redis     {args.redis_url}   docker={'yes' if repo['docker'] else 'no'}",
        f" api-svc   port {args.api_port}   key={STATE['api_key_source']}",
        " Ctrl+C to stop. Simulations and api-service started here stop with it.",
        "=" * 66,
    ]
    print("\n".join(banner), flush=True)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down...")
    finally:
        LAB.stack.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
