"""Post-process `vijayawada_corridor.rou.xml` (built by `build.sh`) to
replace its single `veh_passenger` vType with a heterogeneous mix -- car,
motorcycle, auto-rickshaw, bus -- so "person-delay" (build guide §8.1's
primary metric: vehicle delay weighted by occupancy) is a real weighted
computation instead of relabeled vehicle-delay on an all-cars fleet.

Two kinds of numbers go into each new vType, and they carry different
weight:

- **vClass** and the physical dynamics that follow from it (accel, decel,
  length, speed factor) are SUMO's own maintained defaults for
  `motorcycle`/`bus`/`taxi`/`passenger` -- not invented here. Checked
  against `vijayawada_corridor.net.xml`'s lane `disallow` lists first
  (only rail/ship/pedestrian/bicycle classes are ever disallowed on this
  network, so all four vClasses route identically to the original
  all-`passenger` demand -- no vehicle needs a different route than the
  one `duarouter` already computed for it).
- **The traffic-mix split and the occupancy-per-type assumption are not
  measured for this corridor.** They're commonly-cited approximate
  figures for a mixed Indian urban arterial (two-wheeler-heavy, a
  meaningful auto-rickshaw share, a small bus share carrying a large
  share of person-trips) -- the same honesty level the demand's own
  README already applies to the trip generation itself ("not calibrated
  demand... real fieldwork, done once there's a reason to defend the
  numbers"). Treat MIX and OCCUPANCY below as documented assumptions to
  revisit alongside that fieldwork, not as ground truth.

Occupancy is stored as a `<param key="occupancy">` on each `<vType>`
rather than in a separate constants table, so the metrics collector reads
it from the same file that defines the vType, instead of two places that
could drift apart. `<param key="pcu">` (added alongside it) is the same
idea for M4's CA-MP strategy [build guide §3.2.1]: passenger-car-unit
equivalence, IRC SP:41's indicative prior (two-wheeler 0.3, auto-rickshaw
0.6, car 1.0, bus 3.0) -- a different physical quantity from occupancy
(roadway space consumed, not people carried) that the guide happens to
tabulate from the same per-class source. `signal_controller/queue_state.py`
reads it the same way `metrics.py.load_vtype_occupancy` reads occupancy.

Deliberately does NOT touch which route or depart time any vehicle has --
only the `type=` attribute changes, assigned by a seeded weighted draw in
vehicle order. That means every existing measured flow
(`measure_flows.py`) and every Webster/coordination tuning number already
verified against this demand stays exactly as measured; only per-vehicle
physical dynamics (and therefore realistic queuing/gap behaviour under
actuated strategies) change. Run once, checked in like the rest of the
demand -- not run automatically by `build.sh`, since `build.sh` alone must
still reproduce a valid (if homogeneous) demand file on its own.
"""

from __future__ import annotations

import random
import xml.etree.ElementTree as ET
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROU_PATH = _HERE / "vijayawada_corridor.rou.xml"

# Not measured for Vijayawada -- see module docstring. Broadly consistent
# with commonly-cited mode-share ranges for mixed Indian urban arterials
# (two-wheeler-dominant, a substantial auto-rickshaw share, a small but
# high-occupancy bus share).
_MIX = {
    "veh_motorcycle": 0.35,
    "veh_car": 0.40,
    "veh_auto": 0.20,
    "veh_bus": 0.05,
}
assert abs(sum(_MIX.values()) - 1.0) < 1e-9

# Average persons per vehicle, including the driver -- also not measured;
# the bus figure (a loaded urban city bus) is deliberately the same order
# of magnitude the build guide's own person-delay example uses ("a bus
# with 40 people").
_OCCUPANCY = {
    "veh_motorcycle": 1.3,
    "veh_car": 1.5,
    "veh_auto": 2.5,
    "veh_bus": 40.0,
}

# IRC SP:41 indicative PCU prior [build guide §3.2.1] -- "a prior, not a
# constant"; real recalibration from this corridor's own discharge
# headways is future work (§8.5), same caveat as MIX/OCCUPANCY above.
_PCU = {
    "veh_motorcycle": 0.3,
    "veh_car": 1.0,
    "veh_auto": 0.6,
    "veh_bus": 3.0,
}

# vClass chosen per type from what's actually permitted on every lane of
# this network (checked against the net.xml's `disallow` lists, which
# only ever exclude rail/ship/pedestrian/bicycle) -- physical dynamics
# (accel/decel/length/speed factor) are left at SUMO's own defaults for
# that vClass, not invented here. `taxi` is the closest built-in vClass to
# a shared auto-rickshaw; there is no dedicated SUMO auto-rickshaw class.
_VCLASS = {
    "veh_motorcycle": "motorcycle",
    "veh_car": "passenger",
    "veh_auto": "taxi",
    "veh_bus": "bus",
}

_SEED = 7  # fixed, documented, like every other seed in this project


def assign_vtypes(rou_path: Path = _ROU_PATH, *, seed: int = _SEED) -> None:
    # `xml.etree.ElementTree` silently drops comments -- and this file's
    # top-of-file `<!-- generated on ... -->` blocks are real provenance
    # (how the trips were built, by which tool, with what seed), not
    # boilerplate. Preserve them verbatim by keeping the raw header text
    # (everything before the `<routes` opening tag) and only round-
    # tripping the `<routes>` element itself through ElementTree.
    original_text = rou_path.read_text(encoding="UTF-8")
    split_at = original_text.index("<routes")
    header = original_text[:split_at]

    root = ET.fromstring(original_text[split_at:])

    for old_vtype in root.findall("vType"):
        root.remove(old_vtype)

    # Insert new vType definitions at the top, in the same fixed order
    # every run, so the diff is stable across regenerations.
    for type_id in ("veh_car", "veh_motorcycle", "veh_auto", "veh_bus"):
        vtype_el = ET.Element(
            "vType", {"id": type_id, "vClass": _VCLASS[type_id]}
        )
        ET.SubElement(
            vtype_el, "param", {"key": "occupancy", "value": str(_OCCUPANCY[type_id])}
        )
        ET.SubElement(vtype_el, "param", {"key": "pcu", "value": str(_PCU[type_id])})
        root.insert(0, vtype_el)

    rng = random.Random(seed)
    type_ids = list(_MIX.keys())
    weights = [_MIX[t] for t in type_ids]
    n_reassigned = 0
    for vehicle in root.findall("vehicle"):
        vehicle.set("type", rng.choices(type_ids, weights=weights, k=1)[0])
        n_reassigned += 1

    ET.indent(root, space="    ")
    rou_path.write_text(header + ET.tostring(root, encoding="unicode") + "\n", encoding="UTF-8")
    print(f"reassigned {n_reassigned} vehicles across {len(type_ids)} vTypes in {rou_path}")


if __name__ == "__main__":
    import sys

    # Optional path arg -- lets `build_demand_levels.sh`'s light/heavy
    # route files (and any future one) go through the exact same vType
    # assignment as the original medium file, without a second script.
    if len(sys.argv) > 1:
        assign_vtypes(Path(sys.argv[1]))
    else:
        assign_vtypes()
