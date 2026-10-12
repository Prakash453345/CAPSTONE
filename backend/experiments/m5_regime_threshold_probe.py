"""How well does A-CA-MP's own smoothed-load signal (`AdaptiveCamp._load_ewma`,
`AcampConfig.load_halflife_s`) separate medium from heavy demand at this
corridor -- the question that has to be answered before picking a
regime-split threshold, not assumed.

PROGRESS.md's "Fixing heavy demand" section already measured this once,
run-averaged, per-junction, at heavy only: `[0.17, 0.16, 0.18, 0.43, 1.52,
1.55, 22.02]`. This script gets the same quantity at light, medium, and
heavy, and gets the *distribution* over ticks (not just the run mean) at
each junction and level, since a threshold has to be picked against the
distribution a live controller will actually see tick to tick, not a
single summary number.

Instruments the controller exactly as `m5_heavy_diagnostics.py`'s Probe
does -- wraps `AdaptiveCamp`, reads its own already-computed
`smoothed_load` property, changes nothing in `acamp.py` itself.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from itms_domain import JunctionContext, SignalPlan, Tier0Config  # noqa: E402
from sim_service.control.strategies import acamp  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402


class LoadProbe:
    def __init__(self, inner: acamp.AdaptiveCamp, tls_id: str):
        self.inner = inner
        self.tls_id = tls_id
        self.samples: list[float] = []

    def set_sim_time(self, t: float) -> None:
        self.inner.set_sim_time(t)

    @property
    def stats(self):
        return self.inner.stats

    def __call__(self, cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan:
        plan = self.inner(cfg, ctx)
        self.samples.append(self.inner.smoothed_load)
        return plan


def run(level: str, seed: int, cfg_path: str) -> dict:
    inputs = H.scenario_inputs(level)
    configs, flows, _, _ = inputs
    acfg = load_config(cfg_path)
    inner = H.build_acamp(configs, flows, acamp_cfg=acfg)
    probes = {tls: LoadProbe(c, tls) for tls, c in inner.items()}

    original = H.CONTROLLERS["acamp"]
    H.CONTROLLERS["acamp"] = lambda *a, **k: probes
    try:
        H.run_one("acamp", level, seed, tripinfo_dir=Path("/tmp/m5_regime_probe"), inputs=inputs)
    finally:
        H.CONTROLLERS["acamp"] = original

    per_junction = {}
    for tls, p in probes.items():
        if not p.samples:
            continue
        s = sorted(p.samples)
        q = statistics.quantiles(s, n=20, method="inclusive") if len(s) >= 20 else s
        per_junction[tls] = {
            "n": len(s),
            "mean": statistics.mean(s),
            "median": q[9] if len(q) >= 10 else statistics.median(s),
            "p75": q[14] if len(q) >= 15 else max(s),
            "p90": q[17] if len(q) >= 18 else max(s),
            "max": max(s),
        }
    return per_junction


def main() -> None:
    tuned = str(Path(__file__).resolve().parent / "results" / "m5_artifacts" / "acamp_tuned.json")
    out: dict[str, dict] = {}
    for level in ("light", "medium", "heavy"):
        print(f"=== {level} ===", flush=True)
        per_junction = run(level, seed=1, cfg_path=tuned)
        out[level] = per_junction
        for tls, stats in per_junction.items():
            print(
                f"  {tls:45s} mean={stats['mean']:8.2f}  median={stats['median']:8.2f}  "
                f"p75={stats['p75']:8.2f}  p90={stats['p90']:8.2f}  max={stats['max']:8.2f}"
            )
    out_path = Path(__file__).resolve().parent / "results" / "m5_regime_threshold_probe.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
