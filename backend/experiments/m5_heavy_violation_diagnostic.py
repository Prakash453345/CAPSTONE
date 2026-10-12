"""Which interlock is A-CA-MP tripping at heavy demand, and why?

The corrected gate records 2-4 `failsafe_interlock_rejected` events per
ten heavy runs in the A-CA-MP arm, against **zero** for Webster at every
demand level. The runner keeps only `(junction, step, mode)`, so the
*rule* -- I1 through I7 -- is discarded before it reaches any artefact,
and the account of these violations in `PROGRESS.md` has therefore always
been "they are in the strategy, not the corridor" and nothing finer.

A rejection is not a collision: `interlocks.check` refusing a plan is the
kernel doing exactly its job. But the arbiter's response to a rejection
is to command the failsafe, and on this corridor that means all-red at a
junction under heavy load -- which is both a large delay event and,
repeated, the thing that produced M4's 10,235-rejection starvation
deadlock at `cluster_1880441740_4393296791`. Knowing which invariant is
being violated is the difference between a tuning problem and a
structural one.

Instruments by wrapping `arbiter.tick`, not by editing it or `acamp.py`:
the decision object already carries `events` with the rule and message
(`"I5: ..."`), and the runner simply does not persist them. This captures
them on the way past, so the thing measured is the shipped control path.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
from sim_service.signal_controller import arbiter as arbiter_mod  # noqa: E402

_RULE = re.compile(r"\b(I[1-7])\b")

captured: list[dict] = []


def install_probe() -> None:
    """Wrap `arbiter.tick` so every non-success decision is recorded with
    its full event text. Idempotent."""
    if getattr(arbiter_mod.tick, "_probed", False):
        return
    original = arbiter_mod.tick

    def probed(cfg, ctx, cabinet, **kwargs):
        decision = original(cfg, ctx, cabinet, **kwargs)
        if decision.mode not in arbiter_mod.SUCCESS_MODES:
            text = " | ".join(str(e) for e in (decision.events or []))
            captured.append(
                {
                    "junction": cfg.intersection_id,
                    "mode": decision.mode,
                    "rules": sorted(set(_RULE.findall(text))),
                    "current_phase": ctx.current_phase_id,
                    "elapsed_s": getattr(ctx, "current_phase_elapsed_s", None),
                    "movements": sorted(decision.violated_movements or ()),
                    "text": text[:400],
                }
            )
        return decision

    probed._probed = True  # type: ignore[attr-defined]
    arbiter_mod.tick = probed  # type: ignore[assignment]
    # `runner` imported `arbiter` as a module, so rebinding the attribute
    # is enough -- it resolves `arbiter.tick` at call time, not import.


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", default="heavy")
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument(
        "--out",
        default=str(
            Path(__file__).resolve().parent / "m5_artifacts" / "m5_heavy_violations.json"
        ),
    )
    args = parser.parse_args()

    install_probe()
    per_seed = {}
    for seed in args.seeds:
        captured.clear()
        record = H.run_one(
            "acamp",
            args.level,
            seed,
            tripinfo_dir=Path("/tmp/m5_viol_tripinfo"),
            record_memory=False,
        )
        events = list(captured)
        per_seed[seed] = {
            "interlock_violations": record["interlock_violations"],
            "events": events,
        }
        print(
            f"seed {seed:3d}  delay={record['person_delay_s']:>12,.0f}  "
            f"violations={record['interlock_violations']}  captured={len(events)}",
            flush=True,
        )
        for e in events:
            print(f"    {e['junction'][:34]:34s} {e['mode']:28s} "
                  f"rules={e['rules']} phase={e['current_phase']} "
                  f"elapsed={e['elapsed_s']}")
            if e["text"]:
                print(f"      {e['text'][:200]}")

    allev = [e for v in per_seed.values() for e in v["events"]]
    print(f"\n{'=' * 70}\n{len(allev)} non-success decisions over {len(args.seeds)} seeds")
    print("by mode:      ", Counter(e["mode"] for e in allev).most_common())
    print("by rule:      ", Counter(r for e in allev for r in e["rules"]).most_common())
    print("by junction:  ", Counter(e["junction"][:30] for e in allev).most_common())
    print("by phase:     ", Counter(str(e["current_phase"]) for e in allev).most_common())

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(per_seed, indent=1, default=str))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
