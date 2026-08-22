"""Real corridor geometry for coordinated-actuated timing [build guide §7
M3]: which order the 7 signal-controlled junctions sit in along the
Benz-Circle-to-PNBS arterial, and how far apart they actually are -- the
"measured," not-guessed input a progression offset needs, the same
standard `coordinated_actuated.py`'s docstring holds Webster's cycle length
to.

Two things come straight from the network's own `.net.xml`, not
guesswork: each signal-controlled `<junction>`'s real `x`/`y` (metres, in
the network's own projected UTM coordinate system per its `<location>`
element -- Euclidean distance between two junctions is already a real
distance in metres, no separate projection step needed), and the corridor
order those coordinates imply. This network's 7 junctions are not
perfectly axis-aligned (MG Road curves slightly over its length), so
"order by x" or "order by y" alone would be an approximation stated as
exact; instead this fits the direction of greatest spread across all 7
points (the dominant axis of a 2D PCA, computed directly from the 2x2
covariance matrix -- small enough not to need numpy) and orders junctions
by their position along *that* axis, which is robust to the corridor's
real, slight curvature.

Importable: `corridor_order(net_path) -> list[str]` (junction ids, ordered
Benz-Circle-end-first by construction of the projection, though the
projection itself has no notion of which physical end that is -- see
`corridor_order`'s own docstring for how a caller should sanity-check
that), `cumulative_distances_m(net_path) -> dict[str, float]` (each
junction's real along-corridor distance from the first junction in that
order, via Euclidean distance summed junction-to-junction, not a straight
line from end to end -- the arterial isn't straight enough for that to be
the same thing).
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT_NET = _HERE / "vijayawada_corridor.net.xml"


def _signal_junction_positions(net_path: str | Path) -> dict[str, tuple[float, float]]:
    tree = ET.parse(net_path)
    root = tree.getroot()
    tls_ids = {tl.get("id") for tl in root.findall("tlLogic")}
    positions: dict[str, tuple[float, float]] = {}
    for junction in root.findall("junction"):
        jid = junction.get("id")
        if jid is not None and jid in tls_ids:
            positions[jid] = (float(junction.get("x", "0")), float(junction.get("y", "0")))
    return positions


def corridor_order(net_path: str | Path = _DEFAULT_NET) -> list[str]:
    """Signal-controlled junction ids ordered along the corridor's own
    dominant axis. Which end is "first" is whatever the PCA projection's
    sign happens to produce -- arbitrary but consistent -- so this only
    matters for computing *relative* offsets along the corridor, not for
    labelling a real-world end. A caller that cares which physical end is
    Benz Circle vs. PNBS needs to check against a map once, not re-derive
    it here every run."""
    positions = _signal_junction_positions(net_path)
    ids = list(positions)
    n = len(ids)
    if n < 2:
        return ids
    mean_x = sum(positions[i][0] for i in ids) / n
    mean_y = sum(positions[i][1] for i in ids) / n
    cxx = sum((positions[i][0] - mean_x) ** 2 for i in ids) / n
    cyy = sum((positions[i][1] - mean_y) ** 2 for i in ids) / n
    cxy = sum((positions[i][0] - mean_x) * (positions[i][1] - mean_y) for i in ids) / n

    trace = cxx + cyy
    disc = math.sqrt(max(trace * trace / 4 - (cxx * cyy - cxy * cxy), 0.0))
    lam1 = trace / 2 + disc
    if abs(cxy) > 1e-9:
        vx, vy = 1.0, -(cxx - lam1) / cxy
    else:
        vx, vy = (1.0, 0.0) if cxx >= cyy else (0.0, 1.0)
    norm = math.hypot(vx, vy) or 1.0
    vx, vy = vx / norm, vy / norm

    def projection(jid: str) -> float:
        return (positions[jid][0] - mean_x) * vx + (positions[jid][1] - mean_y) * vy

    return sorted(ids, key=projection)


def cumulative_distances_m(net_path: str | Path = _DEFAULT_NET) -> dict[str, float]:
    """`{tls_id: metres from the first junction in `corridor_order`}`,
    summing real Euclidean junction-to-junction distances along that
    order -- not a single straight-line distance end to end."""
    positions = _signal_junction_positions(net_path)
    order = corridor_order(net_path)
    distances: dict[str, float] = {}
    running = 0.0
    for i, jid in enumerate(order):
        if i > 0:
            prev = order[i - 1]
            dx = positions[jid][0] - positions[prev][0]
            dy = positions[jid][1] - positions[prev][1]
            running += math.hypot(dx, dy)
        distances[jid] = running
    return distances


def main() -> None:
    order = corridor_order()
    distances = cumulative_distances_m()
    print(f"corridor order ({len(order)} junctions):")
    for jid in order:
        print(f"  {jid}: {distances[jid]:.1f}m from corridor start")


if __name__ == "__main__":
    main()
