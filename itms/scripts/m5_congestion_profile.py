"""Where does this corridor's own congestion signal actually sit at each
demand level? `protect_allocated_green`'s gate (`congestion >= 0.5`,
hard-coded in `acamp.py`, reusing `switch_cost_bias`'s already-tuned
Hill-curve) was discovered and verified entirely on heavy-demand data.
`m5_heavy_diagnostics.py --level medium` found medium demand wastes about
38% of its own allocated green (35.9s allocated vs 22.2s served) --
proportionally worse than light's ~15% and approaching heavy's ~61% --
which is exactly the defect `protect_allocated_green` exists to fix, yet
the verified gate (`m5_protect_allocated_green_verify.py`) found the
mechanism fires zero times at medium demand. This script checks the
obvious explanation directly: does medium demand's own smoothed load ever
actually cross the 0.5 congestion threshold, or does it plateau below it?

Wraps each junction's `AdaptiveCamp` (not editing `acamp.py`) to sample
`congestion_weight(_load_ewma, switch_scale_ref, switch_scale_exponent)`
every tick -- the identical computation `__call__` does internally --
so this is an observation of the real quantity the gate checks, not a
proxy for it.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from itms_domain import JunctionContext, Tier0Config  # noqa: E402
from sim_service.control import memory as memory_mod  # noqa: E402
from sim_service.control.runner import run_controlled_scenario  # noqa: E402
from sim_service.control.strategies import acamp  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402


class CongestionProbe:
    """Wraps one junction's controller; records the congestion signal
    `protect_allocated_green`'s gate reads, every tick, without touching
    `acamp.py` itself."""

    def __init__(self, inner: acamp.AdaptiveCamp):
        self.inner = inner
        self.samples: list[float] = []

    def set_sim_time(self, t: float) -> None:
        self.inner.set_sim_time(t)

    @property
    def stats(self):
        return self.inner.stats

    def __call__(self, cfg: Tier0Config, ctx: JunctionContext):
        plan = self.inner(cfg, ctx)
        acfg = self.inner.cfg
        self.samples.append(
            memory_mod.congestion_weight(
                self.inner._load_ewma, acfg.switch_scale_ref, acfg.switch_scale_exponent
            )
        )
        return plan


def run(level: str, seed: int, tuned_path: str) -> None:
    inputs = H.scenario_inputs(level)
    configs, flows, vtype_pcu, paths = inputs
    link_lanes = H.link_to_lane_map(H.NET_PATH)
    receiving_lanes = H.link_to_receiving_lane_map(H.NET_PATH)
    acfg = load_config(tuned_path)

    inner = H.build_acamp(configs, flows, acamp_cfg=acfg)
    probes = {tls: CongestionProbe(c) for tls, c in inner.items()}

    tripinfo_path = Path(f"/tmp/m5_congestion_profile/{level}_seed{seed}.xml")
    tripinfo_path.parent.mkdir(parents=True, exist_ok=True)
    run_controlled_scenario(
        str(paths["sumocfg"]),
        configs,
        strategy=probes,
        seed=seed,
        link_lanes=link_lanes,
        receiving_lanes=receiving_lanes,
        vtype_pcu=vtype_pcu,
        tripinfo_output=str(tripinfo_path),
        max_steps=H.MAX_STEPS_SAFETY_CAP,
    )

    all_samples = [s for p in probes.values() for s in p.samples]
    print(f"\n=== {level} seed {seed} ===")
    print(f"  ticks (all junctions pooled)  {len(all_samples):>8d}")
    print(f"  mean congestion                {statistics.mean(all_samples):>8.3f}")
    print(f"  median congestion               {statistics.median(all_samples):>8.3f}")
    print(f"  max congestion                  {max(all_samples):>8.3f}")
    pct_over = 100.0 * sum(1 for s in all_samples if s >= 0.5) / len(all_samples)
    print(f"  % ticks >= 0.5 (gate threshold) {pct_over:>7.1f}%")
    print("  per-junction max congestion:")
    for tls, p in sorted(probes.items(), key=lambda kv: -max(kv[1].samples, default=0.0)):
        mean_congestion = statistics.mean(p.samples) if p.samples else 0.0
        print(f"    {tls:45s} max={max(p.samples, default=0.0):.3f}  mean={mean_congestion:.3f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--tuned-config", default=str(H.ARTIFACT_DIR / "acamp_tuned.json"))
    args = ap.parse_args()
    for level in ["light", "medium", "heavy"]:
        run(level, args.seed, args.tuned_config)


if __name__ == "__main__":
    main()
