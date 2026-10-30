"""Trace one closed-loop run junction by junction (M8 jam investigation).

The heavy closed-loop gate jams in about one camera-driven run in five
(itms6_640 seed 5: 729k s person delay against 454k for truth). This runs
one arm of `m8_closed_loop_gate.py` with a recorder around every junction's
strategy and writes, every `--every` seconds:

* per junction: the phase and its age, and per link the queue and receiving
  occupancy the runner measured (truth) next to what the controller was fed
  (the camera's, in a vision arm);
* network-wide: vehicles running, vehicles waiting to enter, teleports.

    python scripts/m8_jam_trace.py --arm vision:itms6_640:failsafe --level heavy --seed 5 \\
        --out results/jam/itms6_640_s5.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m8_harness as M  # noqa: E402
import traci  # noqa: E402

FIELDS = ("queue_pcu", "approaching_pcu", "receiving_occupancy", "receiving_queue_pcu")


class Recorder:
    """Wraps a strategy; logs what the runner measured and what the inner
    strategy decided on. For a VisionSensor it logs the swapped context too."""

    def __init__(self, inner, tls: str, log: list, every: float):
        self.inner, self.tls, self.log, self.every = inner, tls, log, every
        self._t = 0.0
        self._next = 0.0

    def set_sim_time(self, t: float) -> None:
        self._t = t
        self.inner.set_sim_time(t)

    @property
    def stats(self):
        return self.inner.stats

    def __call__(self, cfg, ctx):
        seen = {}
        inner = self.inner
        if hasattr(inner, "loop"):  # VisionSensor: capture what it hands the controller
            real = inner.inner

            def spy(c, new):
                seen["ctx"] = new
                return real(c, new)

            inner.inner = spy
            try:
                dec = inner(cfg, ctx)
            finally:
                inner.inner = real
        else:
            dec = inner(cfg, ctx)
        if self._t >= self._next:
            self._next = self._t + self.every
            fed = seen.get("ctx", ctx)
            row = {"t": self._t, "tls": self.tls, "phase": ctx.current_phase_id,
                   "age": round(ctx.current_phase_elapsed_s, 1),
                   "plan": [(s.phase_id, round(s.green_s, 1))
                            for s in getattr(dec, "steps", ())][:2],
                   "conf": {k: round(v, 2) for k, v in (fed.confidence or {}).items()}}
            for f in FIELDS:
                row["truth_" + f] = {k: round(v, 2) for k, v in getattr(ctx, f).items()}
                row["fed_" + f] = {k: round(v, 2) for k, v in getattr(fed, f).items()}
            self.log.append(row)
        return dec


class _OracleHidden:
    """Adds the true out-of-view halted PCU to the (camera) queue it is handed."""

    def __init__(self, inner, hidden: dict, links: dict):
        self.inner, self.hidden, self.links = inner, hidden, links

    def set_sim_time(self, t: float) -> None:
        self.inner.set_sim_time(t)

    @property
    def stats(self):
        return self.inner.stats

    def __call__(self, cfg, ctx):
        from dataclasses import replace  # noqa: PLC0415

        q = {m: v + self.hidden.get(self.links.get(m, ""), 0.0) for m, v in ctx.queue_pcu.items()}
        return self.inner(cfg, replace(ctx, queue_pcu=q))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    ap.add_argument("--level", default="heavy")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--fps", type=float, default=5.0)
    ap.add_argument("--every", type=float, default=10.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--oracle-hidden", action="store_true",
                    help="add the true halted PCU beyond each camera's near view to the "
                         "camera queue (what a perfect estimate of the hidden part would give)")
    args = ap.parse_args()

    import m8_closed_loop_gate as G  # noqa: PLC0415

    log: list = []
    net: list = []
    hidden: dict[str, float] = {}
    arm = args.arm
    inputs = M.ccacamp_inputs(args.level)
    if arm == "truth":
        base = M.build_strategy("ccacamp", inputs)
    else:
        from vision_service.sim.closed_loop import VisionLoop, VisionSensor  # noqa: PLC0415

        _, preset, mode, *extra = arm.split(":")
        base0 = M.build_strategy("ccacamp", inputs)
        approach, _ = M.link_maps()
        kw = {}
        if "nogap" in extra:
            from vision_service.state import EstimatorConfig  # noqa: PLC0415

            kw["estimator_config"] = EstimatorConfig(gap_counting=False)
        factory = M.vision_factory(preset, args.seed, args.fps, **kw)
        if "outage" in extra:
            factory = G._with_fault(factory, "offline")  # noqa: SLF001
        loop = VisionLoop(factory, approach.keys())
        if args.oracle_hidden:
            base0 = {tls: _OracleHidden(ctrl, hidden, approach[tls]) for tls, ctrl in base0.items()}
        base = {tls: VisionSensor(ctrl, loop, tls, mode) for tls, ctrl in base0.items()}
    strategy = {tls: Recorder(s, tls, log, args.every) for tls, s in base.items()}
    tele = [0]

    vtype_pcu = inputs[2]
    approach_all, _ = M.link_maps()
    rig = M.rig()
    view_start = {lid: rig.network.lanes[lid].length - rig.coverage(lid).covered_from_end_m
                  for links in approach_all.values() for lid in links.values()}

    def on_tick(step: int, t: float) -> None:
        tele[0] += traci.simulation.getStartingTeleportNumber()
        if args.oracle_hidden:
            for lid, v0 in view_start.items():
                hidden[lid] = sum(
                    vtype_pcu.get(traci.vehicle.getTypeID(v), 1.0)
                    for v in traci.lane.getLastStepVehicleIDs(lid)
                    if traci.vehicle.getSpeed(v) < 0.1 and traci.vehicle.getLanePosition(v) < v0)
        if step % int(args.every) == 0:
            net.append({"t": t, "running": traci.vehicle.getIDCount(),
                        "pending": len(traci.simulation.getPendingVehicles()),
                        "teleports": tele[0], "arrived": traci.simulation.getArrivedNumber()})

    t0 = time.time()
    rec = M.run_scenario("ccacamp", args.level, args.seed, inputs=inputs, strategy=strategy,
                         tag="trace_" + arm.replace(":", "_"), on_tick=on_tick)
    rec["arm"] = arm
    rec["wall_s"] = round(time.time() - t0, 1)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"record": rec, "net": net, "junctions": log}))
    print(f"{arm} {args.level} seed {args.seed}: delay {rec['person_delay_s']:,.0f} "
          f"steps {rec['steps']} teleports {tele[0]} ({rec['wall_s']}s) -> {args.out}")


if __name__ == "__main__":
    main()
