"""Custom origin -> destination demand, generated per run.

The repo ships three demand levels (light / medium / heavy) as checked-in
`randomTrips.py` output. This module adds the fourth thing the test site
needs and the repo has no file for: "put N vehicles on road A and send them
to road B", with an explicit target for how many should arrive.

Generated files land in `testing_site/var/runs/<run_id>/` and reference the
repo's network and (optionally) one of its shipped demand files as background
traffic by absolute path. Nothing in `itms/` is written or modified.

The four vTypes mirror `scenarios/demand/vijayawada/assign_vtypes.py`
field-for-field -- same vClass, same `occupancy` and `pcu` params, same
colours -- under an `od_` prefix so they can coexist in the same SUMO run as
the background file's `veh_*` types. Keeping the params identical is what
makes a custom run's person-delay comparable to a preset run's: the metrics
collector reads occupancy off the vType, so a different number there would
silently change the headline KPI.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import quoteattr

from simlab import network, paths

# id -> (vClass, guiShape, color, occupancy, pcu) -- see assign_vtypes.py
VTYPES = {
    "od_car": ("passenger", "passenger/sedan", "127,209,255", 1.5, 1.0),
    "od_motorcycle": ("motorcycle", "motorcycle", "87,201,123", 1.3, 0.3),
    "od_auto": ("taxi", "moped", "232,178,58", 2.5, 0.6),
    "od_bus": ("bus", "bus", "226,112,58", 40.0, 3.0),
}

DEFAULT_MIX = {"od_motorcycle": 0.35, "od_car": 0.40, "od_auto": 0.20, "od_bus": 0.05}

BACKGROUND_CHOICES = ("none", "light", "medium", "heavy")


@dataclass
class ODSpec:
    origin: str
    destination: str
    count: int = 40
    target_arrivals: int | None = None
    depart_window_s: float = 300.0
    depart_start_s: float = 0.0
    background: str = "light"
    mix: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_MIX))
    seed: int = 42
    duration_s: float = 1800.0

    def normalised(self) -> ODSpec:
        count = max(1, min(int(self.count), 5000))
        target = self.target_arrivals
        target = count if target is None else max(0, min(int(target), count))
        mix = {k: float(v) for k, v in (self.mix or {}).items() if k in VTYPES and float(v) > 0}
        total = sum(mix.values())
        mix = {k: v / total for k, v in mix.items()} if total > 0 else dict(DEFAULT_MIX)
        background = self.background if self.background in BACKGROUND_CHOICES else "light"
        return ODSpec(
            origin=self.origin,
            destination=self.destination,
            count=count,
            target_arrivals=target,
            depart_window_s=max(1.0, float(self.depart_window_s)),
            depart_start_s=max(0.0, float(self.depart_start_s)),
            background=background,
            mix=mix,
            seed=int(self.seed),
            duration_s=max(60.0, float(self.duration_s)),
        )


def validate(spec: ODSpec) -> dict:
    """Pre-flight: is the pair routable, and how long is the trip? Returned to
    the browser before a run starts so an impossible pair is a message in the
    form, not a dead simulation."""
    spec = spec.normalised()
    path = network.shortest_path(spec.origin, spec.destination)
    if not path.get("ok"):
        return {"ok": False, "reason": path.get("reason", "unroutable pair")}
    return {
        "ok": True,
        "route": path["edges"],
        "length_m": path["length_m"],
        "free_flow_s": path["free_flow_s"],
        "n_signals": path["n_signals"],
        "signals": path.get("signals", []),
        "count": spec.count,
        "target_arrivals": spec.target_arrivals,
        # A vehicle every `headway` seconds down one corridor; flagged when it
        # exceeds what a single-lane approach can physically discharge (~1800
        # veh/h saturation, i.e. one vehicle per 2 s) so an unachievable target
        # is visible before the run rather than read as a failed test.
        "headway_s": round(spec.depart_window_s / spec.count, 2),
        "oversaturated": (spec.depart_window_s / spec.count) < 2.0,
    }


def _vtype_xml() -> str:
    rows = []
    for tid, (vclass, shape, color, occ, pcu) in VTYPES.items():
        rows.append(
            f'    <vType id="{tid}" vClass="{vclass}" guiShape="{shape}" color="{color}">\n'
            f'        <param key="occupancy" value="{occ}"/>\n'
            f'        <param key="pcu" value="{pcu}"/>\n'
            f"    </vType>"
        )
    return "\n".join(rows)


def write_scenario(spec: ODSpec, out_dir: Path) -> dict:
    """Write `od.rou.xml` + `custom.sumocfg` into `out_dir` and return the
    manifest the runner and the UI both read."""
    spec = spec.normalised()
    out_dir.mkdir(parents=True, exist_ok=True)

    path = network.shortest_path(spec.origin, spec.destination)
    if not path.get("ok"):
        raise ValueError(path.get("reason", "unroutable origin/destination pair"))
    route_edges = path["edges"]

    rng = random.Random(spec.seed)
    type_ids = list(spec.mix)
    weights = [spec.mix[t] for t in type_ids]

    # Evenly spaced departures with a small deterministic jitter: a perfectly
    # periodic platoon is an unrealistically easy case for any signal
    # controller, and the jitter is seeded so the run is still reproducible.
    step = spec.depart_window_s / spec.count
    vehicles = []
    counts = dict.fromkeys(VTYPES, 0)
    for i in range(spec.count):
        depart = spec.depart_start_s + i * step + rng.uniform(0, step * 0.6)
        vtype = rng.choices(type_ids, weights=weights, k=1)[0]
        counts[vtype] += 1
        vehicles.append((f"od_{i}", vtype, depart))
    vehicles.sort(key=lambda v: v[2])

    edges_attr = quoteattr(" ".join(route_edges))
    body = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Generated by testing_site/simlab/scenario.py for one manual test run.",
        f"     {spec.count} vehicles: {spec.origin} -> {spec.destination}",
        f"     target arrivals: {spec.target_arrivals} | seed {spec.seed}",
        "     Disposable: regenerated on every run, never part of the repo. -->",
        '<routes xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/routes_file.xsd">',
        _vtype_xml(),
        f'    <route id="od_route" edges={edges_attr}/>',
    ]
    for vid, vtype, depart in vehicles:
        body.append(
            f'    <vehicle id="{vid}" type="{vtype}" route="od_route"'
            f' depart="{depart:.2f}" departLane="best" departSpeed="max"/>'
        )
    body.append("</routes>")

    rou_path = out_dir / "od.rou.xml"
    rou_path.write_text("\n".join(body) + "\n", encoding="UTF-8")

    route_files = [str(rou_path)]
    background_route = None
    if spec.background != "none":
        _, bg_rou = paths.demand_paths(spec.background)
        if bg_rou.exists():
            background_route = str(bg_rou)
            # Background first so its `veh_*` vTypes are defined before any
            # vehicle references them; SUMO reads route files left to right.
            route_files = [background_route, str(rou_path)]

    cfg_path = out_dir / "custom.sumocfg"
    cfg_path.write_text(
        "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                "<!-- Generated per run by testing_site. Absolute paths on purpose:",
                "     the network and any background demand are read straight out of",
                "     the repo, and nothing is copied or modified there. -->",
                '<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
                ' xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">',
                "    <input>",
                f'        <net-file value={quoteattr(str(paths.NET_PATH))}/>',
                f'        <route-files value={quoteattr(",".join(route_files))}/>',
                "    </input>",
                "    <time>",
                '        <begin value="0"/>',
                f'        <end value="{spec.duration_s:.0f}"/>',
                "    </time>",
                "    <processing>",
                '        <ignore-route-errors value="true"/>',
                "    </processing>",
                "    <report>",
                '        <no-step-log value="true"/>',
                '        <duration-log.statistics value="true"/>',
                "    </report>",
                "</configuration>",
            ]
        )
        + "\n",
        encoding="UTF-8",
    )

    return {
        "sumocfg": str(cfg_path),
        "route": str(rou_path),
        "background_route": background_route,
        "route_edges": route_edges,
        "origin": spec.origin,
        "destination": spec.destination,
        "count": spec.count,
        "target_arrivals": spec.target_arrivals,
        "vehicle_ids_prefix": "od_",
        "mix_counts": {k: v for k, v in counts.items() if v},
        "depart_window_s": spec.depart_window_s,
        "duration_s": spec.duration_s,
        "length_m": path["length_m"],
        "free_flow_s": path["free_flow_s"],
        "n_signals": path["n_signals"],
    }
