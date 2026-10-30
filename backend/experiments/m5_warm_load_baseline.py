"""Build a genuinely cross-run-warmed `LoadBaseline`, sequentially --
Phase A.5 of the training pipeline, sitting between `train_acamp.py`'s
demand-memory phase and `m5_relative_congestion_sweep.py`'s parameter
search.

**Why this exists.** `AcampConfig.use_relative_congestion_gate`'s
docstring diagnosed why turning the ratio gate on did not help: each
`AdaptiveCamp` is built fresh per run, so `_baseline_load_ewma` starts
cold every time, and a single demand-level run (a few thousand simulated
seconds) is far too short for a `baseline_halflife_s` of 3600s to climb
from 0 to this junction's real long-run normal. `memory.LoadBaseline`
gives the value somewhere to live *between* runs; this script is what
actually chains runs together to warm it, the way `DemandMemory` gets
warmed by `train_acamp.py`'s Phase A.

**Why sequential, not parallel -- the one hard constraint this script
exists to respect.** `LoadBaseline.update` overwrites: the point is that
run N+1 starts exactly where run N ended. Running two seeds in parallel
from the same starting point and keeping whichever result lands last
would silently discard one run's contribution instead of chaining both --
so this script runs one scenario at a time, unlike every other M5 script
in this package, and is correspondingly slower.

**Why levels are interleaved rather than run in three separate blocks.**
A real corridor experiences light, medium and heavy periods in an
ongoing rotation, not ten light days followed by ten heavy ones -- and
with `baseline_halflife_s = 3600s` against a single run's ~2,500-3,700
simulated seconds, the choice of order is not free: ending a warm-up on
a run of one level leaves the baseline visibly biased toward that
level's scale for a while into whatever runs next. Interleaving
light -> medium -> heavy, repeated once per training seed, is this
script's explicit, documented assumption about what "this junction's
long-run normal traffic mix" looks like -- not a measured fact about
Vijayawada's real day-of-week pattern, which this project has no data
for. Recorded here so the next person extending this starts from an
assumption stated in the open, not one buried in loop order.

**Seed discipline, unchanged from every other M5 training script.** Runs
on `TRAIN_SEEDS` (101-110) only. `EVAL_SEEDS` (1-10) must never
contribute to the warmed baseline that a gate result is then measured
against -- exactly the obligation `memory.py`'s own module docstring
states for `DemandMemory`.

Usage:
    python scripts/m5_warm_load_baseline.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from sim_service.control.memory import LoadBaseline  # noqa: E402
from sim_service.control.tuning import load_config  # noqa: E402

_TUNED_PATH = H.ARTIFACT_DIR / "acamp_tuned.json"
_OUT = H.ARTIFACT_DIR / "load_baseline.json"

LEVELS = ["light", "medium", "heavy"]


def main() -> None:
    cfg = load_config(str(_TUNED_PATH))
    store = LoadBaseline()
    jobs = [(seed, level) for seed in H.TRAIN_SEEDS for level in LEVELS]
    print(
        f"Warming load baseline sequentially over {len(jobs)} runs "
        f"(seeds {H.TRAIN_SEEDS} x {LEVELS}, interleaved per seed)\n",
        flush=True,
    )
    started = time.time()
    for i, (seed, level) in enumerate(jobs, start=1):
        H.run_one(
            "acamp",
            level,
            seed,
            tripinfo_dir=Path("/tmp/m5_warm_load_baseline"),
            acamp_cfg=cfg,
            load_baseline=store,
            record_baseline=True,
        )
        elapsed = (time.time() - started) / 60
        # A representative sample, not all seven junctions every line --
        # this corridor's heaviest junction, named throughout PROGRESS.md,
        # is the one whose absolute-threshold defect started this whole
        # investigation, so it is the most informative one to watch warm.
        sample = store.get("cluster_1880441740_4393296791")
        print(
            f"[{i}/{len(jobs)}] seed={seed:3d} {level:6s} "
            f"heaviest_junction_baseline={sample:8.3f} ({elapsed:.1f}m)",
            flush=True,
        )
    store.save(_OUT)
    print(f"\nwrote {_OUT}")
    print("\nfinal per-junction baseline (this corridor's 7 signal-controlled junctions):")
    for tls_id in sorted(store._values):  # noqa: SLF001
        print(f"  {tls_id:40s} {store.get(tls_id):8.3f}  ({store.runs(tls_id)} runs)")


if __name__ == "__main__":
    main()
