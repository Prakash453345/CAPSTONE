"""M8: switch one piece of the vision estimate off and see what it does -- to
the estimate, and to the controller that runs on it. On TRAIN seeds, so the
answer can be used to choose.

Two kinds of run:

- `estimate`: CC-A-CAMP on SUMO truth drives the traffic (so every variant
  sees the same traffic) while the vision system films it; per link-tick
  `queue_pcu` error against `QueueStateSampler`, split by whether the lane
  was flagged truncated, plus how much traffic the furniture filter kept or
  dropped (real vehicles vs detector ghosts, from SimCam's truth ids).
- `closed`: CC-A-CAMP runs *on* the cameras (`trust`), so the variant
  changes the traffic; person-delay is the answer. `--variant truth` is the
  same controller on SUMO truth.

Variants are JSON overrides: `{"ground": {...GroundConfig}, "est":
{...EstimatorConfig}}`, e.g. `{"est": {"horizon_quantile": 0.9}}`.

    python scripts/m8_estimator_ablation.py estimate --level heavy --seed 101 \\
        --variant '{"est": {"horizon_quantile": 0.9}}'
    python scripts/m8_estimator_ablation.py closed --level heavy --seed 101 --variant '{}'

What it decided is recorded in `baselines/2026-09-25_m8_review/`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m8_harness as M  # noqa: E402
from sim_service.signal_controller.queue_state import QueueStateSampler  # noqa: E402
from vision_service.classes import ClassTable  # noqa: E402
from vision_service.ground import GroundConfig  # noqa: E402
from vision_service.incidents import TraciSignalState  # noqa: E402
from vision_service.sim.closed_loop import VisionLoop, VisionSensor  # noqa: E402
from vision_service.simcam import TraciWorld  # noqa: E402
from vision_service.state import EstimatorConfig  # noqa: E402
from vision_service.state import estimator as E  # noqa: E402


def _factory(preset: str, seed: int, variant: dict):
    return M.vision_factory(preset, seed, 5.0,
                            ground_config=GroundConfig(**variant.get("ground", {})),
                            estimator_config=EstimatorConfig(**variant.get("est", {})))


def estimate(level: str, seed: int, preset: str, variant: dict, steps: int) -> dict:
    furniture: dict[str, float] = defaultdict(float)
    original = E.LinkStateEstimator._is_furniture

    def spy(self, t, g):
        out = original(self, t, g)
        if t >= 300:
            kind = "real" if g.truth_id is not None else "ghost"
            furniture[f"{'dropped' if out else 'kept'}/{kind}"] += g.pcu
        return out

    E.LinkStateEstimator._is_furniture = spy  # type: ignore[method-assign]
    inputs = M.ccacamp_inputs(level)
    vtype_pcu = inputs[2]
    approach, receiving = M.link_maps()
    make = _factory(preset, seed, variant)
    world = TraciWorld()
    signal = TraciSignalState(approach.keys())
    st: dict = {"vs": None, "prev": None}
    acc: dict[str, list[float]] = defaultdict(lambda: [0, 0.0, 0.0])

    def on_tick(step: int, t: float) -> None:
        snap = world.snapshot()
        if st["vs"] is None:
            dims = world.vtype_dimensions()
            vs = make(ClassTable.default().with_dimensions(dims) if dims
                      else ClassTable.default())
            vs.incidents.signal = signal
            st["vs"] = vs
            st["samplers"] = {tls: QueueStateSampler(approach[tls], receiving[tls], vtype_pcu)
                              for tls in approach}
        vs = st["vs"]
        signal.refresh(t)
        vs.step_world(st["prev"], snap)
        vs.tick(t)
        st["prev"] = snap
        if t < 300:
            return
        for tls, sampler in st["samplers"].items():
            truth = sampler.sample_extended().queue_pcu
            for link, lane_id in approach[tls].items():
                e = vs.estimator.links.get((tls, link))
                if e is None:
                    continue
                err = e.queue_pcu - truth[link]
                part = "truncated" if vs.estimator.lanes[lane_id].truncated else "in_view"
                for k in (part, "all"):
                    acc[k][0] += 1
                    acc[k][1] += err
                    acc[k][2] += abs(err)

    M.run_scenario("ccacamp", level, seed, inputs=inputs, on_tick=on_tick, max_steps=steps,
                   tag="ablation")
    n = max(1, acc["all"][0])
    return {"queue": {k: {"share": v[0] / n, "mae": v[2] / n, "bias": v[1] / n}
                      for k, v in acc.items()},
            "furniture_pcu_per_link_tick": {k: v / n for k, v in furniture.items()}}


def closed(level: str, seed: int, preset: str, variant: dict | None) -> dict:
    if variant is None:
        rec = M.run_scenario("ccacamp", level, seed, tag="ablation_truth")
    else:
        inputs = M.ccacamp_inputs(level)
        base = M.build_strategy("ccacamp", inputs)
        approach, _ = M.link_maps()
        loop = VisionLoop(_factory(preset, seed, variant), approach.keys())
        strategy = {tls: VisionSensor(ctrl, loop, tls, "trust") for tls, ctrl in base.items()}
        rec = M.run_scenario("ccacamp", level, seed, inputs=inputs, strategy=strategy,
                             tag="ablation_closed")
    return {"person_delay_s": rec["person_delay_s"], "stops_per_vehicle": rec["stops_per_vehicle"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["estimate", "closed"])
    ap.add_argument("--level", default="heavy")
    ap.add_argument("--seed", type=int, default=101)
    ap.add_argument("--preset", default="finetuned_day")
    ap.add_argument("--variant", default="{}", help="JSON overrides, or 'truth' (closed only)")
    ap.add_argument("--steps", type=int, default=1800)
    args = ap.parse_args()
    if args.seed not in M.TRAIN_SEEDS:
        print(f"note: seed {args.seed} is not a TRAIN seed -- do not choose on it",
              file=sys.stderr)
    t0 = time.time()
    variant = None if args.variant == "truth" else json.loads(args.variant)
    if args.kind == "estimate":
        out = estimate(args.level, args.seed, args.preset, variant or {}, args.steps)
    else:
        out = closed(args.level, args.seed, args.preset, variant)
    print(json.dumps({"kind": args.kind, "level": args.level, "seed": args.seed,
                      "preset": args.preset, "variant": args.variant,
                      "wall_s": round(time.time() - t0), **out}))


if __name__ == "__main__":
    main()
