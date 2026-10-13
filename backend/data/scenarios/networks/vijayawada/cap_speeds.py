"""Clamp this corridor's speed limits to an urban-arterial design speed.

**Why this exists.** `netconvert` takes its speed limits from the OSM
`highway=` type map, and for this extract that means **22.2 m/s (80 km/h) and
27.8 m/s (100 km/h)** on every approach -- the typemap's defaults for
`primary`/`trunk`, not anything surveyed. Those are inter-urban values. The
corridor they are attached to is Benz Circle to PNBS in Vijayawada: a signalised
urban arterial with junctions roughly every 400 m, mixed two-wheeler, auto,
bus and car traffic, and frontage access throughout. IRC:86 puts the design
speed for an urban arterial at 50-60 km/h and IRC:106's urban-road capacity
work uses the same band; 50 km/h is the value this corridor's own signal
spacing implies.

**Why it matters beyond realism.** Two things in this build read the speed
limit directly:

1. `extract_tier0_config.kinematic_yellow_s` sizes the change interval from the
   approach speed (`y = t_r + v/2a`). At 27.8 m/s the rule asks for 5.6 s and
   is clamped to its 5 s ceiling; at 13.9 m/s it returns 3.5 s. A yellow is a
   *safety* interval -- it must match the speed vehicles actually approach at,
   which is why this script and the kinematic rule have to agree, and why the
   3 s yellow measured as attractive in `docs/algorithm_improvement_research.md`
   is only defensible once the limit is corrected too.
2. SUMO scores `timeLoss` against each vehicle's own free-flow speed, so the
   declared limit is also the reference the person-delay metric is measured
   from. Changing it moves every arm's absolute numbers together -- which is
   why this lands with a fresh baseline rather than as a comparison against
   the old one.

Usage (also step 4 of `build.sh`):

    python3 cap_speeds.py vijayawada_corridor.net.xml --max-speed 13.89
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

_DEFAULT_NET = Path(__file__).resolve().parent / "vijayawada_corridor.net.xml"
URBAN_ARTERIAL_MPS = 13.89  # 50 km/h -- IRC:86 urban arterial design speed


def cap_speeds(net_path: Path, max_speed_mps: float = URBAN_ARTERIAL_MPS) -> int:
    """Clamp every lane's `speed` (and each edge's, where declared) in place.
    Returns how many lanes were changed. Idempotent: running it twice is a
    no-op, so `build.sh` can call it unconditionally."""
    tree = ET.parse(net_path)
    root = tree.getroot()
    changed = 0
    for element in root.iter():
        if element.tag not in ("lane", "edge"):
            continue
        raw = element.get("speed")
        if raw is None:
            continue
        if float(raw) > max_speed_mps:
            element.set("speed", f"{max_speed_mps:.2f}")
            changed += element.tag == "lane"
    if changed:
        tree.write(net_path, encoding="UTF-8", xml_declaration=True)
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("net", nargs="?", default=str(_DEFAULT_NET))
    ap.add_argument("--max-speed", type=float, default=URBAN_ARTERIAL_MPS,
                    help="m/s (default 13.89 = 50 km/h)")
    args = ap.parse_args()
    changed = cap_speeds(Path(args.net), args.max_speed)
    print(f"capped {changed} lanes at {args.max_speed:.2f} m/s in {args.net}")


if __name__ == "__main__":
    main()
