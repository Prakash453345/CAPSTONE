"""sim-service entrypoint.

M1 default: run the real SUMO/TraCI simulation against the Vijayawada
corridor scenario (scenarios/demand/vijayawada/vijayawada_corridor.sumocfg),
publishing VehiclePositionUpdated and ApproachState at 1 Hz. This replaces
M0's heartbeat as the default -- the heartbeat loop still exists
(sim_service.heartbeat) for bus-plumbing sanity checks, but `make dev` now
shows real simulated traffic, which is the actual point of M1.

Env vars:
  SIM_MODE           "sumo" (default, M1) | "live" | "heartbeat"
                       sumo:  adapters/sumo/traci_loop.run -- one-way SUMO -> Redis
                              stream, no controller, no commands. The M1-gate path.
                       live:  sim_service.live.run_live -- the arbitration ladder
                              governs every junction, the SAME M1 stream is
                              published, and a `commands.*` topic is drained each
                              tick so an operator can act on the running sim.
  SUMOCFG_PATH        path to a .sumocfg (default: the Vijayawada corridor scenario) -- sumo mode
  SIM_DEMAND          "light" | "medium" (default) | "heavy" -- live mode's demand level
  SIM_REALTIME_FACTOR  pacing for the demo loop (default 1.0 -- see traci_loop.run / run_live)
  SIM_STEP_LENGTH      seconds of sim time per step (default 1.0, matches the M1 gate's "1 Hz")
  SIM_MAX_STEPS         stop after N steps (unset = run to scenario end); mainly for tests
  REDIS_URL
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s sim-service %(message)s")
log = logging.getLogger("sim-service.main")

# services/sim-service/sim_service/main.py -> repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SUMOCFG = (
    _REPO_ROOT / "scenarios" / "demand" / "vijayawada" / "vijayawada_corridor.sumocfg"
)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _run_sumo() -> None:
    from itms_common import RedisStreamsSyncBus

    from sim_service.adapters.sumo import traci_loop

    sumocfg = os.environ.get("SUMOCFG_PATH", str(_DEFAULT_SUMOCFG))
    if not Path(sumocfg).exists():
        raise SystemExit(
            f"no scenario at {sumocfg} -- run scenarios/networks/vijayawada/build.sh "
            f"and scenarios/demand/vijayawada/build.sh first, or set SUMOCFG_PATH"
        )

    realtime_factor = float(os.environ.get("SIM_REALTIME_FACTOR", "1.0"))
    step_length = float(os.environ.get("SIM_STEP_LENGTH", "1.0"))
    max_steps_env = os.environ.get("SIM_MAX_STEPS")
    max_steps = int(max_steps_env) if max_steps_env else None

    bus = RedisStreamsSyncBus(REDIS_URL)
    log.info("starting SUMO scenario %s via %s", sumocfg, REDIS_URL)
    try:
        summary = traci_loop.run(
            sumocfg,
            bus,
            step_length=step_length,
            realtime_factor=realtime_factor,
            max_steps=max_steps,
        )
        log.info("scenario finished: %s", summary)
    finally:
        bus.close()


def _run_live() -> None:
    from sim_service.live.service import run_live

    demand = os.environ.get("SIM_DEMAND", "medium")
    realtime_factor = float(os.environ.get("SIM_REALTIME_FACTOR", "1.0"))
    step_length = float(os.environ.get("SIM_STEP_LENGTH", "1.0"))
    max_steps_env = os.environ.get("SIM_MAX_STEPS")
    max_steps = int(max_steps_env) if max_steps_env else None

    log.info("starting LIVE corridor (demand=%s) via %s", demand, REDIS_URL)
    run_live(
        redis_url=REDIS_URL,
        demand=demand,
        realtime_factor=realtime_factor,
        step_length=step_length,
        max_steps=max_steps,
    )


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
