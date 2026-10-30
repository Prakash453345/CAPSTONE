"""Phase layouts built from a junction's own geometry and conflict map.

A program from netconvert can give every *approach* its own phase ("split"
phasing): four changes per cycle at a four-way junction, each one a yellow and
an all-red during which nothing moves. Where two approaches face each other,
their movements can usually run together: straight-ahead traffic and the turn
that crosses nothing run protected, and the turn that crosses the oncoming
stream (the right turn in left-hand traffic, the left turn in right-hand
traffic, and any U-turn) runs *permissive* -- shown green but yielding, the
way SUMO's lowercase 'g' and every real "turn on green, give way" junction
work. The 2026-10-13 check-up found 22-38 % of every signal's time spent in
change intervals, and every phase of arterial_lh and the right-hand
turn-lane grid serving a single approach.

`paired_layout` rebuilds a split junction that way. With `turn_phases`, each
pair also gets a phase in which its crossing turns run protected (with every
movement of the pair that crosses none of them), so a controller can clear a
turn queue that never finds a gap; a controller that skips empty phases pays
for it only when someone is waiting there.

Only junctions where every vehicle phase serves exactly one approach are
changed, and never one with pedestrian signals or alternates. Pairs are
approaches whose headings differ by 180 degrees give or take `tolerance_deg`.
If two movements of a pair conflict and neither is a crossing turn (two
straight streams), the junction is left as it is.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from itms_domain.signal import Phase, Tier0Config

LinkInfo = Mapping[str, tuple[str, str]]  # {"L<i>": (from edge, SUMO dir)}


def net_links(net_path: str | Path
              ) -> tuple[dict[str, dict[str, tuple[str, str]]], dict[str, float], bool]:
    """`({light: {"L<i>": (from edge, dir)}}, {edge: heading at its end, degrees},
    lefthand)` read from a SUMO network."""
    root = ET.parse(net_path).getroot()
    links: dict[str, dict[str, tuple[str, str]]] = {}
    used: set[str] = set()
    for c in root.findall("connection"):
        tl, i, fe = c.get("tl"), c.get("linkIndex"), c.get("from")
        if tl and i is not None and fe and not fe.startswith(":"):
            links.setdefault(tl, {})[f"L{i}"] = (fe, c.get("dir") or "")
            used.add(fe)
    heading: dict[str, float] = {}
    for e in root.findall("edge"):
        if e.get("id") not in used:
            continue
        lane = e.find("lane")
        pts = [tuple(map(float, p.split(","))) for p in (lane.get("shape") or "").split()]  # type: ignore[union-attr]
        if len(pts) >= 2:
            (x0, y0), (x1, y1) = pts[-2], pts[-1]
            heading[e.get("id")] = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 360.0  # type: ignore[index]
    return links, heading, root.get("lefthand") == "true"


def _crossing(direction: str, lefthand: bool) -> bool:
    """The turn that crosses the oncoming stream, or a U-turn."""
    return direction in ("t", "T") or direction in (("r", "R") if lefthand else ("l", "L"))


def paired_layout(cfg: Tier0Config, links: LinkInfo, heading: Mapping[str, float],
                  lefthand: bool, turn_phases: bool = False,
                  tolerance_deg: float = 35.0) -> Tier0Config:
    vehicle = [p for p in cfg.phases.values() if not p.is_pedestrian]
    if (len(vehicle) != len(cfg.phases) or cfg.alternates or len(vehicle) < 3
            or any(m not in links for p in vehicle for m in p.green_movements)):
        return cfg
    by_approach: dict[str, set[str]] = {}
    for p in vehicle:
        approaches = {links[m][0] for m in p.green_movements}
        if len(approaches) != 1:
            return cfg  # already grouped some other way
        by_approach.setdefault(approaches.pop(), set()).update(p.green_movements)
    if any(a not in heading for a in by_approach):
        return cfg

    # pair approaches that face each other, nearest to 180 degrees first
    def gap(a: str, b: str) -> float:
        d = abs(heading[a] - heading[b]) % 360.0
        return abs(180.0 - min(d, 360.0 - d))

    pairs = sorted((gap(a, b), a, b) for a in by_approach for b in by_approach if a < b)
    groups: list[tuple[str, ...]] = []
    taken: set[str] = set()
    for g, a, b in pairs:
        if g <= tolerance_deg and a not in taken and b not in taken:
            groups.append((a, b))
            taken |= {a, b}
    if not groups:
        return cfg
    groups += [(a,) for a in sorted(by_approach) if a not in taken]

    cm = cfg.conflict_matrix

    def clash(a: str, b: str) -> bool:
        return b in cm.get(a, frozenset()) or a in cm.get(b, frozenset())

    min_g = min(cfg.min_green_s.get(p.id, 0.0) for p in vehicle)
    max_g = max(cfg.max_green_s.get(p.id, 0.0) for p in vehicle)
    phases: dict[str, Phase] = {}
    order: list[str] = []
    for k, group in enumerate(groups):
        moves = sorted(set().union(*(by_approach[a] for a in group)))
        permissive: set[str] = set()
        for i, a in enumerate(moves):
            for b in moves[i + 1:]:
                if not clash(a, b):
                    continue
                ca, cb = _crossing(links[a][1], lefthand), _crossing(links[b][1], lefthand)
                if not (ca or cb):
                    return cfg  # two straight streams cross: these cannot share a phase
                if ca:
                    permissive.add(a)
                if cb:
                    permissive.add(b)
        protected = frozenset(m for m in moves if m not in permissive)
        if any(clash(a, b) for a in protected for b in protected if a < b):
            return cfg
        pid = f"G{k}"
        phases[pid] = Phase(pid, frozenset(moves), protected_movements=protected)
        order.append(pid)
        if turn_phases and permissive:
            turns = sorted(permissive)
            if any(clash(a, b) for a in turns for b in turns if a < b):
                continue
            extra = [m for m in protected if not any(clash(m, t) for t in turns)]
            tid = f"G{k}t"
            shown = frozenset(turns + extra)
            phases[tid] = Phase(tid, shown, protected_movements=shown)
            order.append(tid)
    if set().union(*(p.green_movements for p in phases.values())) != set().union(
            *(p.green_movements for p in vehicle)):
        return cfg
    new = replace(cfg, phases=phases, ring_order=tuple(order),
                  min_green_s=dict.fromkeys(phases, min_g),
                  max_green_s=dict.fromkeys(phases, max_g))
    return new if not new.validate() else cfg


def compact_layout(cfg: Tier0Config, links: LinkInfo, heading: Mapping[str, float],
                   lefthand: bool, tolerance_deg: float = 35.0) -> Tier0Config:
    """The fewest phases that serve every movement of any junction, not only a
    split-phased one: two movements may share a phase if they cross nothing of
    each other, or if one is a crossing turn and the other comes from the
    facing approach (the turn then gives way). Two crossing turns that cross
    each other never share a phase. Phases are found by colouring the
    "cannot share" graph (DSatur). The junction is changed only if this needs
    fewer phases than it has; pedestrian signals and alternates leave it
    alone."""
    vehicle = [p for p in cfg.phases.values() if not p.is_pedestrian]
    if len(vehicle) != len(cfg.phases) or cfg.alternates or len(vehicle) < 3:
        return cfg
    moves = sorted(set().union(*(p.green_movements for p in vehicle)),
                   key=lambda m: (len(m), m))
    if any(m not in links or links[m][0] not in heading for m in moves):
        return cfg
    cm = cfg.conflict_matrix

    def clash(a: str, b: str) -> bool:
        return b in cm.get(a, frozenset()) or a in cm.get(b, frozenset())

    def facing(a: str, b: str) -> bool:
        d = abs(heading[links[a][0]] - heading[links[b][0]]) % 360.0
        return abs(180.0 - min(d, 360.0 - d)) <= tolerance_deg

    def crossing(m: str) -> bool:
        return _crossing(links[m][1], lefthand)

    def compatible(a: str, b: str) -> bool:
        if not clash(a, b):
            return True
        if crossing(a) and crossing(b):
            return False
        return (crossing(a) or crossing(b)) and facing(a, b)

    banned = {m: {o for o in moves if o != m and not compatible(m, o)} for m in moves}
    colour: dict[str, int] = {}
    while len(colour) < len(moves):
        # DSatur: the uncoloured movement with the most differently coloured
        # neighbours, then the most neighbours
        m = max((x for x in moves if x not in colour),
                key=lambda x: (len({colour[o] for o in banned[x] if o in colour}),
                               len(banned[x]), -moves.index(x)))
        used = {colour[o] for o in banned[m] if o in colour}
        colour[m] = next(c for c in range(len(moves)) if c not in used)
    n = max(colour.values()) + 1
    if n >= len(vehicle):
        return cfg
    phases: dict[str, Phase] = {}
    for c in range(n):
        members = [m for m in moves if colour[m] == c]
        permissive = {m for m in members if crossing(m)
                      and any(clash(m, o) for o in members if o != m)}
        protected = frozenset(m for m in members if m not in permissive)
        if any(clash(a, b) for a in protected for b in protected if a < b):
            return cfg
        pid = f"C{c}"
        phases[pid] = Phase(pid, frozenset(members), protected_movements=protected)
    min_g = min(cfg.min_green_s.get(p.id, 0.0) for p in vehicle)
    max_g = max(cfg.max_green_s.get(p.id, 0.0) for p in vehicle)
    new = replace(cfg, phases=phases, ring_order=tuple(phases),
                  min_green_s=dict.fromkeys(phases, min_g),
                  max_green_s=dict.fromkeys(phases, max_g))
    return new if not new.validate() else cfg
