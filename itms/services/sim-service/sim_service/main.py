"""sim-service entrypoint.

Default: run the real SUMO/TraCI simulation against the Vijayawada corridor
scenario, with A-CA-MP (M5's adaptive signal controller) actually governing
every junction and M6's anomaly detector watching every link -- not just the
raw traffic replay M1 through M4 shipped. `traci_loop.run` (M1's original,
control-free loop -- SUMO's own default signal program, no arbitration ladder,
no safety kernel, no anomaly detection) is kept as `sim_service.adapters.sumo.
traci_loop` for anything that only wants the traffic-state stream, but is no
longer what `make dev` runs: until this milestone, the live demo and the
gate/benchmark scripts were two different code paths, and only the scripts
ever exercised M2-M7's actual control logic (see PROGRESS.md and README's
"Current milestone" for the full history of that gap). `run_controlled_
scenario` -- the same function scripts/m5_gate_comparison.py and every other
gate script call -- is now that one path for both, via `publish_traffic_state`
and `realtime_factor` (kept exactly so the live map keeps working while real
control also runs).

The live demo runs A-CA-MP with its out-of-the-box tuned defaults (no warmed
DemandMemory/OnlineCalibration profile, no corridor/EV preemption) -- a
deliberately simpler configuration than the gate's best-measured setup, so
`make dev` never depends on a warm-start artifact that may not exist in a
given checkout. `LiveIncidentDetector` (M6) is wired in unconditionally; it
is a safe, documented no-op (see its own module docstring) until a trained
model is dropped into scripts/results/m6_artifacts/, which is not part of a
fresh checkout.

Env vars:
  SIM_MODE             "sumo" (default) | "live" | "heartbeat"
                       sumo:  the A-CA-MP-controlled demo above -- every junction
                              actually governed, M6 watching every link.
                       live:  sim_service.live.service.run_live -- the interactive
                              emergency-response layer (operator anomaly injection,
                              dynamic router, green corridor, continuous re-routing)
                              on top of the same arbitration ladder.
  ITMS_SCENARIO        a scenario directory from scenarios/build_scenario.py (any road
                       network); unset = the Vijayawada network SIM_NETWORK names. Both modes.
  SUMOCFG_PATH         path to a .sumocfg (default: the scenario's SIM_DEMAND level) -- sumo mode
  SIM_ROUTE_PATH       path to the matching .rou.xml (default: SUMOCFG_PATH with a
                       .rou.xml suffix -- true for all three shipped demand levels) -- sumo mode
  SIM_DEMAND           "light" | "medium" (default) | "heavy" -- the demand level
  SIM_NETWORK          "corridor" (default) | "district" -- which Vijayawada network, when
                       ITMS_SCENARIO is unset (setting both is an error): the single MG
                       Road arterial, or the surrounding arterial grid where emergency
                       routes have real alternatives. Both modes.
  SIM_REALTIME_FACTOR  pacing for the demo loop (default 1.0 -- see traci_loop.run / run_live)
  SIM_STEP_LENGTH      seconds of sim time per step (default 1.0, matches the M1 gate's "1 Hz")
  SIM_MAX_STEPS         stop after N steps (unset = run to scenario end); mainly for tests
  CONTROL_SENSOR       "sumo" (default) | "vision" -- sumo mode: where A-CA-MP's queue
                       state comes from. "vision" takes it from the vision service's
                       vision.link-state stream (run `make vision-dev` alongside);
                       see sim_service/control/vision_feed.py
  VISION_CONFIDENCE    "failsafe" (default) | "honest" | "trust" -- with CONTROL_SENSOR=vision:
                       which camera confidence the controller is told about
  VISION_BLIND_CHECK   "1" (default except in trust mode) | "0" -- with CONTROL_SENSOR=vision:
                       treat a link whose stop-bar loop keeps seeing vehicles the camera
                       does not as a failed camera (itms_domain.camera.BlindCameraCheck)
  REDIS_URL
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s sim-service %(message)s")
log = logging.getLogger("sim-service.main")

# services/sim-service/sim_service/main.py -> repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
# the generic network parsers (extract_tier0_config, link_lanes,
# measure_flows) live beside the corridor they were written for
_NET_DIR = _REPO_ROOT / "scenarios" / "networks" / "vijayawada"


def _scenario():
    from itms_domain.scenario import current  # noqa: PLC0415

    return current()

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _run_sumo() -> None:
    """A-CA-MP-controlled live demo: the same `run_controlled_scenario`
    every gate script uses, with `publish_traffic_state=True` so the demo
    page keeps getting `VehiclePositionUpdated`/`ApproachState` exactly as
    before, plus real `SignalChanged`/`SignalFaulted` events and (once a
    trained model exists) live `IncidentCandidate` events."""
    from itms_common import RedisStreamsSyncBus

    from sim_service.control.anomaly.graph_features import AnomalyGraph
    from sim_service.control.anomaly.live import LiveIncidentDetector
    from sim_service.control.runner import run_controlled_scenario
    from sim_service.control.strategies import acamp, webster
    from sim_service.signal_controller.queue_state import load_vtype_pcu

    scenario = _scenario()
    net_path = scenario.net
    default_cfg, default_route = scenario.level(os.environ.get("SIM_DEMAND", "medium"))
    sumocfg = os.environ.get("SUMOCFG_PATH", str(default_cfg))
    route = os.environ.get("SIM_ROUTE_PATH",
                           str(default_route) if "SUMOCFG_PATH" not in os.environ
                           else str(Path(sumocfg).with_suffix(".rou.xml")))
    for label, path in (("scenario", sumocfg), ("route file", route), ("network", str(net_path))):
        if not Path(path).exists():
            raise SystemExit(
                f"no {label} at {path} -- build the scenario first (scenarios/build_scenario.py, "
                f"or the Vijayawada corridor's build.sh scripts), or set ITMS_SCENARIO/"
                f"SUMOCFG_PATH/SIM_ROUTE_PATH"
            )
    log.info("scenario %s: %s", scenario.name, sumocfg)

    realtime_factor = float(os.environ.get("SIM_REALTIME_FACTOR", "1.0"))
    step_length = float(os.environ.get("SIM_STEP_LENGTH", "1.0"))
    max_steps_env = os.environ.get("SIM_MAX_STEPS")
    max_steps = int(max_steps_env) if max_steps_env else None

    # extract_tier0_config/link_lanes/measure_flows live beside the network
    # data they parse, not in an installed package -- every gate/bench
    # script reaches them the same way (scripts/m5_harness.py, etc.).
    sys.path.insert(0, str(_NET_DIR))
    from extract_tier0_config import load_configs  # noqa: E402
    from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
    from measure_flows import compute_link_flows  # noqa: E402

    configs = load_configs(net_path)
    flows = compute_link_flows(net_path, Path(route))
    vtype_pcu = load_vtype_pcu(Path(route))
    link_lanes = link_to_lane_map(net_path)
    receiving_lanes = link_to_receiving_lane_map(net_path)
    # a road split into several edges (turn bays, OSM tag changes) measured
    # as the whole road -- see itms_domain.lane_chains
    from itms_domain.lane_chains import from_sumo_net as chains_from_net  # noqa: PLC0415

    chains = chains_from_net(net_path)

    # One AdaptiveCamp per junction, cold-started (no warmed memory/
    # calibration profile) -- see this module's docstring for why.
    strategy = {
        tls_id: acamp.AdaptiveCamp(
            nominal_cycle_s=webster.compute_timing(cfg, flows.get(tls_id, {})).cycle_s,
            tick_s=step_length,
        )
        for tls_id, cfg in configs.items()
    }

    if os.environ.get("CONTROL_SENSOR", "sumo") == "vision":
        from sim_service.control.vision_feed import (
            VisionFedStrategy,
            VisionFeed,
            start_feed_thread,
        )
        from sim_service.signal_controller.detectors import StopBarLoops

        mode = os.environ.get("VISION_CONFIDENCE", "failsafe")
        feed = VisionFeed()
        start_feed_thread(feed, REDIS_URL)
        blind_env = os.environ.get("VISION_BLIND_CHECK")
        blind_check = None if blind_env is None else blind_env not in ("0", "false", "no")
        strategy = {tls: VisionFedStrategy(  # type: ignore[misc]
                        s, feed, tls, mode, blind_check=blind_check,
                        stopbar=StopBarLoops(link_lanes[tls]).sample if tls in link_lanes else None)
                    for tls, s in strategy.items()}
        log.info("A-CA-MP queue state from the cameras (vision.link-state, confidence=%s)", mode)

    anomaly_graph: AnomalyGraph | None = None
    try:
        anomaly_graph = AnomalyGraph.from_network(net_path)
    except Exception:
        log.exception(
            "could not build the anomaly graph from %s -- incident detection disabled for this run",
            net_path,
        )

    bus = RedisStreamsSyncBus(REDIS_URL)
    live_detector: LiveIncidentDetector | None = None
    if anomaly_graph is not None:
        live_detector = LiveIncidentDetector(anomaly_graph, bus)
        log.info(
            "M6 incident detection: %s",
            "enabled"
            if live_detector.available
            else f"inactive ({live_detector.unavailable_reason})",
        )

    log.info("starting A-CA-MP-controlled SUMO scenario %s via %s", sumocfg, REDIS_URL)
    try:
        summary = run_controlled_scenario(
            sumocfg,
            configs,
            strategy=strategy,
            seed=None,
            step_length=step_length,
            max_steps=max_steps,
            link_lanes=link_lanes,
            receiving_lanes=receiving_lanes,
            vtype_pcu=vtype_pcu,
            lane_chains=chains if (chains[0] or chains[1]) else None,
            bus=bus,
            anomaly_graph=anomaly_graph,
            anomaly_feature_sink=live_detector.on_tick if live_detector is not None else None,
            publish_traffic_state=True,
            realtime_factor=realtime_factor,
        )
        log.info("scenario finished: %s", summary)
    finally:
        bus.close()


def _run_live() -> None:
    from sim_service.live.service import run_live

    demand = os.environ.get("SIM_DEMAND", "medium")
    scenario_name = _scenario().name  # ITMS_SCENARIO / SIM_NETWORK
    realtime_factor = float(os.environ.get("SIM_REALTIME_FACTOR", "1.0"))
    step_length = float(os.environ.get("SIM_STEP_LENGTH", "1.0"))
    max_steps_env = os.environ.get("SIM_MAX_STEPS")
    max_steps = int(max_steps_env) if max_steps_env else None

    log.info("starting LIVE %s (demand=%s) via %s", scenario_name, demand, REDIS_URL)
    run_number = 0
    while True:
        run_number += 1
        # A run ends when the corridor's demand clears, but the live service is
        # meant to outlive it -- otherwise the command center goes dark. A run
        # that *fails* is left to propagate so the container restarts it.
        summary = run_live(
            redis_url=REDIS_URL,
            demand=demand,
            realtime_factor=realtime_factor,
            step_length=step_length,
            max_steps=max_steps,
        )
        log.info("live corridor run #%d finished (%s) -- restarting", run_number, summary)


def _run_heartbeat() -> None:
    from sim_service import heartbeat

    heartbeat.main()


def main() -> None:
    mode = os.environ.get("SIM_MODE", "sumo")
    try:
        if mode == "heartbeat":
            _run_heartbeat()
        elif mode == "live":
            _run_live()
        else:
            _run_sumo()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
