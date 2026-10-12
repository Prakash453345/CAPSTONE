"""The test-lab simulation runner.

This is `sim_service.live.service.run_live` with four additions the test site
needs and the repo's own entry point has no reason to carry:

1. **A controller choice.** `run_live` is hard-wired to tuned Webster;
   `sim_service.main`'s default `sumo` mode is hard-wired to A-CA-MP. Being
   able to run *the same scenario* under fixed-time, Webster and A-CA-MP is
   the whole point of a comparison, so the strategy is a flag here.
2. **Custom demand.** A generated `.sumocfg` can be passed straight in, which
   `run_live` cannot do (it resolves one of three fixed demand files).
3. **A live status file.** One small JSON, rewritten atomically a couple of
   times a second, carrying simulation ground truth: step, active vehicles,
   departures, arrivals, and -- for a custom origin/destination run -- how many
   of the requested vehicles have actually reached the destination.
4. **tripinfo + scored KPIs.** `--tripinfo-output` is handed to SUMO and the
   run is scored through the repo's own `control.metrics` at the end, so a run
   here produces the same person-delay / throughput / wait-distribution /
   stops numbers the gate scripts report.

Everything that matters is the repo's, imported not reimplemented: the
arbitration ladder, the Layer-0 interlocks, `run_controlled_scenario`, the
operator-anomaly controller, the emergency controller and its dynamic router,
the green-corridor controller, the M6 live detector, and the event contracts.
This file wires them; it does not reinterpret them. Nothing under `itms/` is
written or modified.

Usage (the site does this for you):

    python simlab_run.py --status-file var/runs/<id>/status.json \\
        --demand light --controller acamp --realtime-factor 1.0
    python simlab_run.py --status-file ... --sumocfg var/runs/<id>/custom.sumocfg \\
        --route var/runs/<id>/od.rou.xml --od-manifest var/runs/<id>/scenario.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

# testing_site/runner/simlab_run.py -> runner -> testing_site -> CAPSTONE
SITE_DIR = Path(__file__).resolve().parents[1]
CAPSTONE_DIR = SITE_DIR.parent
REPO = Path(os.environ.get("ITMS_REPO") or (CAPSTONE_DIR / "itms")).resolve()
NET_DIR = REPO / "scenarios" / "networks" / "vijayawada"
NET_PATH = NET_DIR / "vijayawada_corridor.net.xml"

for p in (
    REPO / "libs" / "common",
    REPO / "libs" / "domain",
    REPO / "services" / "simulation-service",
    NET_DIR,
):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s simlab-runner %(levelname)s %(message)s"
)
log = logging.getLogger("simlab.runner")

# Matches itms_common.live_events' topic constants exactly -- kept as plain
# literals rather than imported, on purpose: everything that actually touches
# the repo's packages is deferred into main()'s own try/except below, so a
# checkout without `make setup` run yet fails there with one clear message
# instead of an ImportError before argparse even runs. These four strings
# carry no such risk.
ANOMALY_TOPIC = "anomaly.updated"
EMERGENCY_REQUEST_TOPIC = "emergency.request-updated"
EMERGENCY_VEHICLE_TOPIC = "emergency.vehicle-updated"
GREEN_CORRIDOR_TOPIC = "emergency.corridor-updated"
COMMAND_TOPICS = ["commands.operator"]
CONSUMER_GROUP = "simlab-runner"

CONTROLLERS = ("acamp", "camp", "webster", "fixed_time")


# --------------------------------------------------------------------------
# status file
# --------------------------------------------------------------------------
class Status:
    """A tiny atomic JSON writer. The site polls the file; nothing depends on
    a partial write never being observed, but a torn read would be an
    annoying class of phantom bug, so the write is rename-based."""

    def __init__(self, path: Path, initial: dict):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = dict(initial)
        self._last_write = 0.0
        self.write(force=True)

    def write_due(self, min_interval_s: float = 0.5) -> bool:
        """True when the expensive half of the per-tick sampler is worth
        running again. Keeps a 50x-realtime run from spending most of its
        time in TraCI getters feeding a file nobody reads that fast."""
        return time.monotonic() - self._last_write >= min_interval_s

    def write(self, *, force: bool = False, min_interval_s: float = 0.4) -> None:
        now = time.monotonic()
        if not force and now - self._last_write < min_interval_s:
            return
        self._last_write = now
        self.data["updated_at"] = time.time()
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.data, default=str), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            log.exception("could not write status file")


# --------------------------------------------------------------------------
# strategy selection
# --------------------------------------------------------------------------
def build_strategy(name: str, configs, flows, step_length: float):
    """One strategy per junction, built the way the repo's own harnesses build
    it: Webster timings from that junction's measured link flows, A-CA-MP
    seeded with the Webster cycle as its nominal, fixed-time straight off the
    Tier-0 minimums."""
    from functools import partial

    from sim_service.control.strategies import acamp, camp, fixed_time, webster

    if name == "fixed_time":
        # M2's always-safe floor: ring at min-green, proven by property test.
        return {tls_id: partial(fixed_time.propose, tick_s=step_length) for tls_id in configs}
    if name == "webster":
        # M3's tuned baseline, built exactly as scripts/m5_harness.build_webster
        # builds it, so a number measured here is comparable to the gate's.
        return {
            tls_id: partial(
                webster.propose,
                timing=webster.compute_timing(cfg, flows.get(tls_id, {})),
                tick_s=step_length,
            )
            for tls_id, cfg in configs.items()
        }
    if name == "camp":
        # M4's CA-MP, its own defaults, blocking on -- m5_harness.build_camp.
        return {
            tls_id: partial(
                camp.propose,
                camp_cfg=camp.CampConfig(enable_blocking=True),
                nominal_cycle_s=webster.compute_timing(cfg, flows.get(tls_id, {})).cycle_s,
                tick_s=step_length,
            )
            for tls_id, cfg in configs.items()
        }
    # A-CA-MP: the project's own contribution, cold-started (no warmed demand
    # memory / calibration profile), exactly as `sim_service.main` runs it for
    # the live demo.
    return {
        tls_id: acamp.AdaptiveCamp(
            nominal_cycle_s=webster.compute_timing(cfg, flows.get(tls_id, {})).cycle_s,
            tick_s=step_length,
        )
        for tls_id, cfg in configs.items()
    }


def merged_flows(net_path: Path, route_paths: list[Path]):
    """Link flows summed across every route file in the scenario. The repo's
    `compute_link_flows` takes one file; a custom run has two (background +
    the generated origin/destination demand), and Webster needs to see the
    total demand on each movement, not half of it."""
    from measure_flows import compute_link_flows  # type: ignore[import-not-found]

    total: dict[str, dict[str, float]] = {}
    for rp in route_paths:
        if not rp or not Path(rp).exists():
            continue
        try:
            part = compute_link_flows(net_path, Path(rp))
        except Exception:
            log.exception("could not measure flows from %s -- treated as zero", rp)
            continue
        for tls_id, links in part.items():
            bucket = total.setdefault(tls_id, {})
            for link_id, v in links.items():
                bucket[link_id] = bucket.get(link_id, 0.0) + float(v)
    return total


def merged_vtype_params(route_paths: list[Path]):
    from sim_service.control.metrics import load_vtype_occupancy
    from sim_service.signal_controller.queue_state import load_vtype_pcu

    pcu: dict[str, float] = {}
    occ: dict[str, float] = {}
    for rp in route_paths:
        if not rp or not Path(rp).exists():
            continue
        try:
            pcu.update(load_vtype_pcu(Path(rp)))
            occ.update(load_vtype_occupancy(Path(rp)))
        except Exception:
            log.exception("could not read vType params from %s", rp)
    return pcu, occ


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="ITMS test-lab simulation runner")
    ap.add_argument("--status-file", required=True)
    ap.add_argument("--run-id", default="")
    ap.add_argument("--demand", default="medium", choices=["light", "medium", "heavy", "custom"])
    ap.add_argument("--sumocfg", default="", help="custom scenario (overrides --demand)")
    ap.add_argument("--route", default="", help="route file matching --sumocfg")
    ap.add_argument("--background-route", default="")
    ap.add_argument("--od-manifest", default="")
    ap.add_argument("--controller", default="acamp", choices=list(CONTROLLERS))
    ap.add_argument("--realtime-factor", type=float, default=1.0)
    ap.add_argument("--step-length", type=float, default=1.0)
    ap.add_argument("--max-steps", type=int, default=0)
    ap.add_argument("--seed", type=int, default=-1, help="-1 = SUMO --random")
    ap.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    ap.add_argument("--tripinfo", default="")
    ap.add_argument("--warmup-s", type=float, default=600.0)
    ap.add_argument("--no-incident-detector", action="store_true")
    # Route-cost weights (itms_domain.EmergencyRoutingConfig's alpha..zeta
    # terms). Each is optional and left at the repo's own default (shown in
    # `--help`) unless the site's Control screen sends one -- so a run that
    # doesn't touch this panel behaves exactly as it always has.
    ap.add_argument("--travel-time-weight", type=float, default=None)
    ap.add_argument("--congestion-weight", type=float, default=None)
    ap.add_argument("--anomaly-weight", type=float, default=None)
    ap.add_argument("--signal-delay-weight", type=float, default=None)
    ap.add_argument("--disruption-weight", type=float, default=None)
    ap.add_argument("--reliability-weight", type=float, default=None)
    args = ap.parse_args()

    status_path = Path(args.status_file)
    run_dir = status_path.parent

    # Resolve the scenario before importing anything heavy, so a bad path is a
    # clean message in the run log rather than a traceback from inside TraCI.
    if args.sumocfg:
        sumocfg = Path(args.sumocfg)
        route = Path(args.route) if args.route else sumocfg.with_suffix(".rou.xml")
        demand_label = "custom"
    else:
        suffix = {"light": "_light", "medium": "", "heavy": "_heavy"}[args.demand]
        base = REPO / "scenarios" / "demand" / "vijayawada"
        sumocfg = base / f"vijayawada_corridor{suffix}.sumocfg"
        route = base / f"vijayawada_corridor{suffix}.rou.xml"
        demand_label = args.demand

    od = {}
    if args.od_manifest and Path(args.od_manifest).exists():
        od = json.loads(Path(args.od_manifest).read_text(encoding="utf-8"))

    route_paths = [p for p in (Path(args.background_route) if args.background_route else None, route) if p]

    status = Status(
        status_path,
        {
            "run_id": args.run_id,
            "pid": os.getpid(),
            "state": "starting",
            "started_at": time.time(),
            "demand": demand_label,
            "controller": args.controller,
            "sumocfg": str(sumocfg),
            "route": str(route),
            "realtime_factor": args.realtime_factor,
            "step_length": args.step_length,
            "max_steps": args.max_steps or None,
            "seed": None if args.seed < 0 else args.seed,
            "step": 0,
            "sim_time_s": 0.0,
            "error": None,
            "route_cost_weights": None,
        },
    )

    for label, path in (("scenario", sumocfg), ("route file", route), ("network", NET_PATH)):
        if not Path(path).exists():
            msg = f"no {label} at {path}"
            log.error(msg)
            status.data.update(state="failed", error=msg)
            status.write(force=True)
            return 2

    # --- the repo's own machinery ----------------------------------------
    try:
        import traci
        from extract_tier0_config import load_configs  # type: ignore[import-not-found]
        from itms_common.bus import RedisStreamsSyncBus, RedisStreamsSyncConsumer
        from itms_common.events import decode_envelope, encode_envelope
        from itms_domain import EmergencyRoutingConfig
        from link_lanes import (  # type: ignore[import-not-found]
            link_to_lane_map,
            link_to_receiving_lane_map,
        )
        from sim_service.control.runner import run_controlled_scenario
        from sim_service.live.anomaly_control import OperatorAnomalyController
        from sim_service.live.emergency_control import EmergencyController
        from sim_service.live.green_corridor import CorridorController
        from sim_service.routing import RoadGraph
    except Exception as exc:  # pragma: no cover - environment problem, not logic
        msg = (
            f"could not import the ITMS packages ({exc}). Run `make setup` in "
            f"{REPO} so .venv exists with traci and the services installed."
        )
        log.error(msg)
        status.data.update(state="failed", error=msg)
        status.write(force=True)
        return 3

    # Route-cost weights: only the six the Control screen's panel sends
    # override the repo's own EmergencyRoutingConfig defaults (see the
    # dataclass in itms_domain.routing for what each one does and what it
    # defaults to). Validated the same way the repo validates its own config
    # (EmergencyRoutingConfig.validate) so a bad value -- negative, or every
    # weight zeroed out -- fails the run with one clear message instead of
    # silently routing on nonsense.
    weight_overrides = {
        k: v
        for k, v in {
            "travel_time_weight": args.travel_time_weight,
            "congestion_weight": args.congestion_weight,
            "anomaly_weight": args.anomaly_weight,
            "signal_delay_weight": args.signal_delay_weight,
            "disruption_weight": args.disruption_weight,
            "reliability_weight": args.reliability_weight,
        }.items()
        if v is not None
    }
    routing_config = EmergencyRoutingConfig(**weight_overrides)
    weight_problems = routing_config.validate()
    if weight_problems:
        msg = "invalid route-cost weights: " + "; ".join(weight_problems)
        log.error(msg)
        status.data.update(state="failed", error=msg)
        status.write(force=True)
        return 2
    status.data["route_cost_weights"] = routing_config.as_dict()
    status.write(force=True)

    configs = load_configs(NET_PATH)
    flows = merged_flows(NET_PATH, route_paths)
    vtype_pcu, vtype_occ = merged_vtype_params(route_paths)
    link_lanes = link_to_lane_map(NET_PATH)
    receiving_lanes = link_to_receiving_lane_map(NET_PATH)
    strategy = build_strategy(args.controller, configs, flows, args.step_length)

    bus = RedisStreamsSyncBus(args.redis_url)
    consumer = RedisStreamsSyncConsumer(
        COMMAND_TOPICS, group=CONSUMER_GROUP, consumer=f"simlab-{os.getpid()}", url=args.redis_url
    )
    # CorridorController and EmergencyController both take the routable
    # RoadGraph built once from the network's .net.xml (sim_service.routing.
    # RoadGraph.from_network) -- this replaces an earlier guess at their
    # constructor (link_lanes/receiving_lanes/configs), which does not match
    # the real `komal` branch signature and raised a TypeError on every run.
    # link_lanes/receiving_lanes/configs are still used below, for
    # run_controlled_scenario's own strategy wiring.
    graph = RoadGraph.from_network(NET_PATH)
    corridor = CorridorController(graph, config=routing_config)
    anomalies = OperatorAnomalyController()
    emergency = EmergencyController(graph, anomalies, corridor_controller=corridor, config=routing_config)
    # A-CA-MP's own anticipation/debt pressure terms (A(p)/D(p)) can lean on
    # a `sim_service.control.corridor` engine (scripts/m7_corridor_benchmark.py's
    # offline build_arm wires one up) -- but that is a different object from
    # this module's `corridor` (sim_service.live.green_corridor.
    # CorridorController, the M8 operator-driven one keyed by emergency
    # request, with no `.engine` attribute). The real live entrypoint
    # (sim_service/live/service.py's run_live) does not wire this either --
    # junction-level preemption through the arbiter's rung 3 (below,
    # `preempt_source=corridor.preemption_plan`) does not need it. So this
    # intentionally does NOT attach anything to `junction_strategy.corridor`
    # for A-CA-MP: green-corridor preemption still works the same regardless
    # of which controller is running, just without A-CA-MP's own pressure
    # term leaning into an approaching request ahead of time. A prior
    # version of this line referenced `corridor.engine`, which does not
    # exist on the real CorridorController and crashed every run.

    # M6's live detector: real code, a documented no-op until a trained model
    # exists under scripts/results/m6_artifacts/. Wired so that when one does,
    # incident candidates show up in the site's human-gate panel with no
    # further work.
    live_detector = None
    anomaly_graph = None
    if not args.no_incident_detector:
        try:
            from sim_service.control.anomaly.graph_features import AnomalyGraph
            from sim_service.control.anomaly.live import LiveIncidentDetector

            anomaly_graph = AnomalyGraph.from_network(NET_PATH)
            live_detector = LiveIncidentDetector(anomaly_graph, bus)
            status.data["incident_detector"] = (
                "enabled"
                if getattr(live_detector, "available", False)
                else f"inactive ({getattr(live_detector, 'unavailable_reason', 'no trained model')})"
            )
        except Exception as exc:
            status.data["incident_detector"] = f"unavailable ({exc})"
            log.warning("M6 detector not wired: %s", exc)

    edge_ids = sorted(e for e in traci_edge_ids_from_net(NET_PATH))
    od_prefix = od.get("vehicle_ids_prefix", "od_")
    od_target = od.get("target_arrivals")
    od_count = od.get("count")
    od_destination = od.get("destination")

    counters = {
        "departed_total": 0,
        "arrived_total": 0,
        "teleports": 0,
        "od_departed": 0,
        "od_arrived": 0,
        "commands_drained": 0,
        "anomaly_events": 0,
        "emergency_events": 0,
        "corridor_events": 0,
    }
    od_depart_time: dict[str, float] = {}
    od_travel_times: list[float] = []
    anomalies_seen: dict[str, dict] = {}
    requests_seen: dict[str, dict] = {}
    corridors_seen: dict[str, dict] = {}
    stopping = {"flag": False}

    def _on_signal(_signum, _frame):
        stopping["flag"] = True
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            pass

    def publish(topic: str, event_type: str, payload: dict, key: str) -> None:
        bus.publish(
            topic,
            encode_envelope(
                event_type=event_type, source="sim-service", payload=payload, partition_key=key
            ),
        )

    def dispatch(envelope: dict, step: int, sim_time: float) -> None:
        etype = envelope.get("event_type")
        payload = envelope.get("payload", {})
        if etype == "AnomalyCreateRequested":
            anomalies.handle_create(payload, step=step, sim_time_s=sim_time)
        elif etype == "AnomalyClearRequested":
            anomalies.handle_clear(payload, step=step, sim_time_s=sim_time)
        elif etype == "EmergencyRequestCreated":
            emergency.handle_create(payload, step=step, sim_time_s=sim_time)
        elif etype == "EmergencyCommand":
            emergency.handle_command(payload, step=step, sim_time_s=sim_time)
        else:
            log.info("no handler for command %s (step %d) -- ignored", etype, step)

    wall_start = time.monotonic()

    def on_tick(step: int, sim_time: float) -> None:
        # 1. operator commands, exactly as run_live drains them
        for msg in consumer.drain():
            try:
                envelope = decode_envelope(msg.raw)
            except Exception:
                log.exception("undecodable command on %s -- acking to skip", msg.topic)
                consumer.ack(msg.topic, msg.message_id)
                continue
            try:
                dispatch(envelope, step, sim_time)
            except Exception:
                log.exception("command handler raised for %s", envelope.get("event_type"))
            finally:
                consumer.ack(msg.topic, msg.message_id)
                counters["commands_drained"] += 1

        anomalies.tick(step, sim_time)
        emergency.tick(step, sim_time)

        for p in anomalies.drain_events():
            counters["anomaly_events"] += 1
            # Field names match anomaly_updated.avsc / OperatorAnomalyController's
            # actual payload -- no "source" field exists there (the earlier
            # version of this dict read one that was never produced, always
            # silently None).
            anomalies_seen[p["anomaly_id"]] = {
                "id": p["anomaly_id"],
                "status": p.get("status"),
                "type": p.get("anomaly_type"),
                "severity": p.get("severity"),
                "edge": p.get("edge_id"),
                "vehicle": p.get("vehicle_id"),
                "detail": p.get("detail"),
            }
            publish(ANOMALY_TOPIC, "AnomalyUpdated", p, p["edge_id"])
        for p in emergency.drain_events():
            counters["emergency_events"] += 1
            # Matches emergency_request_updated.avsc (verified against the
            # real `komal` branch, contracts/events/ + sim_service/live/
            # emergency_control.py): vehicle_kind/destination_edge/eta_s are
            # the real fields -- capability/facility_name/
            # free_flow_travel_time_s (an earlier assumption from a stale,
            # disconnected checkout) were never part of this payload.
            requests_seen[p["request_id"]] = {
                "id": p["request_id"],
                "state": p.get("state"),
                "vehicle": p.get("vehicle_id"),
                "vehicle_kind": p.get("vehicle_kind"),
                "destination_edge": p.get("destination_edge"),
                "eta_s": p.get("eta_s"),
                "chain_hash": p.get("chain_hash"),
                "detail": p.get("detail"),
            }
            publish(EMERGENCY_REQUEST_TOPIC, "EmergencyRequestUpdated", p, p["request_id"])
        for p in emergency.drain_vehicle_events():
            publish(EMERGENCY_VEHICLE_TOPIC, "EmergencyVehicleUpdated", p, p["vehicle_id"])
        for p in corridor.drain_events():
            counters["corridor_events"] += 1
            # Matches green_corridor_updated.avsc (verified against the real
            # `komal` branch): each event is a full current snapshot --
            # status + reservations + peak_concurrency -- not a per-junction
            # granted/released delta, so a plain overwrite per corridor_id is
            # correct (an earlier assumption, from the same stale checkout as
            # above, aggregated junction ids by hand because it thought no
            # snapshot existed).
            key = p["corridor_id"]
            corridors_seen[key] = {
                "id": key,
                "request": p.get("request_id"),
                "status": p.get("status"),
                "event": p.get("event"),
                "junctions_active": [r["intersection_id"] for r in p.get("reservations", [])],
                "peak_concurrency": p.get("peak_concurrency"),
            }
            publish(GREEN_CORRIDOR_TOPIC, "GreenCorridorUpdated", p, p["request_id"])

        # 2. simulation ground truth for the status file
        departed = traci.simulation.getDepartedIDList()
        arrived = traci.simulation.getArrivedIDList()
        counters["departed_total"] += len(departed)
        counters["arrived_total"] += len(arrived)
        counters["teleports"] += len(traci.simulation.getStartingTeleportIDList())
        for vid in departed:
            if vid.startswith(od_prefix):
                counters["od_departed"] += 1
                od_depart_time[vid] = sim_time
        for vid in arrived:
            if vid.startswith(od_prefix):
                counters["od_arrived"] += 1
                t0 = od_depart_time.pop(vid, None)
                if t0 is not None:
                    od_travel_times.append(sim_time - t0)

        status.data["step"] = step
        status.data["sim_time_s"] = round(sim_time, 1)
        status.data["state"] = "running"
        status.data["wall_s"] = round(time.monotonic() - wall_start, 1)
        status.data["steps_per_s"] = round(step / max(0.001, time.monotonic() - wall_start), 2)

        if status.write_due():
            n_active = traci.vehicle.getIDCount()
            edge_rows = {}
            speeds = []
            for eid in edge_ids:
                try:
                    n = traci.edge.getLastStepVehicleNumber(eid)
                    occ = traci.edge.getLastStepOccupancy(eid)
                    spd = traci.edge.getLastStepMeanSpeed(eid)
                    halt = traci.edge.getLastStepHaltingNumber(eid)
                except traci.TraCIException:
                    continue
                if n:
                    speeds.append(spd)
                edge_rows[eid] = {
                    "n": n,
                    "occ": round(occ, 4),
                    "speed": round(spd, 2),
                    "halting": halt,
                }
            status.data["vehicles"] = {
                "active": n_active,
                "departed_total": counters["departed_total"],
                "arrived_total": counters["arrived_total"],
                "teleports": counters["teleports"],
            }
            status.data["network"] = {
                "mean_speed_mps": round(sum(speeds) / len(speeds), 2) if speeds else 0.0,
                "total_halting": sum(r["halting"] for r in edge_rows.values()),
                "max_occupancy": round(max((r["occ"] for r in edge_rows.values()), default=0.0), 4),
                "edges": edge_rows,
            }
            if od:
                in_transit = counters["od_departed"] - counters["od_arrived"]
                status.data["od"] = {
                    "origin": od.get("origin"),
                    "destination": od_destination,
                    "requested": od_count,
                    "target_arrivals": od_target,
                    "departed": counters["od_departed"],
                    "arrived": counters["od_arrived"],
                    "in_transit": max(0, in_transit),
                    "not_yet_departed": max(0, (od_count or 0) - counters["od_departed"]),
                    "target_met": (od_target is not None and counters["od_arrived"] >= od_target),
                    "mean_travel_s": round(sum(od_travel_times) / len(od_travel_times), 1)
                    if od_travel_times
                    else None,
                    "route_edges": od.get("route_edges", []),
                }
            status.data["counters"] = dict(counters)
            status.data["anomalies"] = list(anomalies_seen.values())
            status.data["emergency_requests"] = list(requests_seen.values())
            status.data["corridors"] = list(corridors_seen.values())
            status.write(force=True)

    tripinfo = args.tripinfo or str(run_dir / "tripinfo.xml")
    summary: dict = {}
    exit_code = 0
    try:
        log.info(
            "starting: demand=%s controller=%s scenario=%s rt=%.2f step=%.2f redis=%s",
            demand_label,
            args.controller,
            sumocfg,
            args.realtime_factor,
            args.step_length,
            args.redis_url,
        )
        summary = run_controlled_scenario(
            str(sumocfg),
            configs,
            strategy,
            seed=None if args.seed < 0 else args.seed,
            step_length=args.step_length,
            max_steps=args.max_steps or None,
            tripinfo_output=tripinfo,
            link_lanes=link_lanes,
            receiving_lanes=receiving_lanes,
            vtype_pcu=vtype_pcu,
            bus=bus,
            anomaly_graph=anomaly_graph,
            anomaly_feature_sink=live_detector.on_tick if live_detector is not None else None,
            # `corridor=` (arbiter.CorridorPort) and `ev_reporter=` are a
            # different, older rung-3 requester shape that CorridorController
            # doesn't implement (no .engine, no .on_tick) -- the real live
            # entrypoint (sim_service/live/service.py's run_live) wires green
            # corridor preemption through `preempt_source`, a plain callable
            # (arbiter.PreemptSource), and never sets `corridor=`/`ev_reporter=`
            # at all; corridor ticking already happens above, inside
            # emergency.tick() -> CorridorController.tick(). Matched here.
            preempt_source=corridor.preemption_plan,
            publish_traffic_state=True,
            on_tick=on_tick,
            realtime_factor=args.realtime_factor if args.realtime_factor > 0 else None,
        )
        status.data["state"] = "finished"
    except KeyboardInterrupt:
        log.info("stopped by request at step %s", status.data.get("step"))
        status.data["state"] = "stopped"
    except Exception as exc:
        log.exception("run failed")
        status.data.update(state="failed", error=f"{type(exc).__name__}: {exc}")
        exit_code = 1
    finally:
        try:
            anomalies.restore_all()
        except Exception:
            log.exception("could not restore lane speeds")
        consumer.close()
        bus.close()

    status.data["summary"] = {
        k: v for k, v in summary.items() if k in ("steps", "interlock_violations", "spillback_events")
    }
    status.data["fault_events"] = (summary.get("fault_events") or [])[-50:]
    status.data["corridor_stats"] = summary.get("corridor")
    status.data["counters"] = dict(counters)

    # --- score the run through the repo's own metrics ---------------------
    metrics = None
    if Path(tripinfo).exists():
        try:
            from sim_service.control.metrics import parse_tripinfo, score_trips

            trips = parse_tripinfo(tripinfo)
            scenario_duration = float(status.data.get("sim_time_s") or 0.0) or 1800.0
            rm = score_trips(
                trips,
                vtype_occ or {},
                warmup_s=args.warmup_s,
                scenario_duration_s=scenario_duration,
            )
            metrics = {
                "n_trips_total": rm.n_trips_total,
                "n_trips_scored": rm.n_trips_scored,
                "person_delay_s": round(rm.person_delay_s, 1),
                "person_throughput_per_hour": round(rm.person_throughput_per_hour, 1),
                "wait_mean_s": round(rm.wait_time_s.mean_s, 2),
                "wait_p50_s": round(rm.wait_time_s.p50_s, 2),
                "wait_p95_s": round(rm.wait_time_s.p95_s, 2),
                "wait_p99_s": round(rm.wait_time_s.p99_s, 2),
                "wait_max_s": round(rm.wait_time_s.max_s, 2),
                "stops_per_vehicle": round(rm.stops_per_vehicle, 3),
                "warmup_s": args.warmup_s,
                "scenario_duration_s": scenario_duration,
            }
        except Exception as exc:
            log.exception("could not score the run")
            metrics = {"error": f"{type(exc).__name__}: {exc}"}
    status.data["metrics"] = metrics
    status.data["finished_at"] = time.time()
    status.write(force=True)

    (run_dir / "result.json").write_text(
        json.dumps(status.data, indent=2, default=str), encoding="utf-8"
    )
    log.info("done: %s", {k: status.data.get(k) for k in ("state", "step", "metrics")})
    return exit_code


def traci_edge_ids_from_net(net_path: Path) -> list[str]:
    """Real (non-internal) edge ids, read straight from the net file so the
    per-edge sampler does not have to ask TraCI for the list every run."""
    import xml.etree.ElementTree as ET

    root = ET.parse(net_path).getroot()
    return [
        e.get("id", "")
        for e in root.findall("edge")
        if e.get("function") != "internal" and e.get("id")
    ]


if __name__ == "__main__":
    sys.exit(main())
