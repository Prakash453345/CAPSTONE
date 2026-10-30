"""Overlaps: a movement shown green in every phase it conflicts with nothing in.

A signal program from netconvert gives each movement one phase. On a junction
built from several OpenStreetMap nodes it often gives each *approach* its own
phase, so a movement that could run beside most of the others waits through
all of them. Traffic engineers call a movement green in more than one phase an
overlap (a left turn in left-hand traffic that crosses nothing, a right turn
alongside the opposite left). `with_overlaps` adds every such movement to every
phase it fits in.

"Fits" is read off the junction's own conflict matrix (SUMO's `foes`), in both
directions, against every movement the phase already shows (protected or
permissive) and every movement already added. An added movement is protected,
so the kernel's I1 check covers it like any other; it cannot add a conflict
I1 would not catch. Pedestrian phases are left as they are, and only movements
some phase of the original program shows are ever added.

The cabinet still puts the whole junction through yellow and all-red between
phases (an overlap is not carried through a change), so this only ever adds
green time; it never shortens a clearance.

Pedestrian signals are never added (`exclude`, from `pedestrian_links`): a
walk shown beside other traffic would end on a vehicle phase's yellow, with no
pedestrian clearance worked out for it.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Collection
from dataclasses import replace
from pathlib import Path

from itms_domain.signal import Phase, Tier0Config


def _index(m: str) -> tuple[int, str]:
    tail = m[1:]
    return (int(tail), m) if tail.isdigit() else (1 << 30, m)


def pedestrian_links(net_path: str | Path) -> dict[str, frozenset[str]]:
    """`{light id: its link labels ("L<i>") that are pedestrian signals}` --
    connections into or out of a crossing or walking area."""
    root = ET.parse(net_path).getroot()
    walk = {e.get("id") for e in root.findall("edge")
            if e.get("function") in ("crossing", "walkingarea")}
    out: dict[str, set[str]] = {}
    for c in root.findall("connection"):
        tl, i = c.get("tl"), c.get("linkIndex")
        if tl and i is not None and (c.get("from") in walk or c.get("to") in walk):
            out.setdefault(tl, set()).add(f"L{i}")
    return {tl: frozenset(v) for tl, v in out.items()}


def turnaround_links(net_path: str | Path) -> dict[str, frozenset[str]]:
    """`{light id: its link labels that are U-turns}` (SUMO `dir` "t", or "T"
    in left-hand traffic). Kept out of overlaps: a U-turn's conflicts with the
    opposite direction and the median are modelled only loosely, and on the
    Vijayawada district eight of its ten overlaps were U-turns into lanes as
    short as 0-22 m (+7 % person-delay at medium demand on training seeds,
    2026-10-11)."""
    root = ET.parse(net_path).getroot()
    out: dict[str, set[str]] = {}
    for c in root.findall("connection"):
        tl, i = c.get("tl"), c.get("linkIndex")
        if tl and i is not None and c.get("dir") in ("t", "T"):
            out.setdefault(tl, set()).add(f"L{i}")
    return {tl: frozenset(v) for tl, v in out.items()}


def with_overlaps(cfg: Tier0Config, exclude: Collection[str] = (), owned: bool = True
                  ) -> Tier0Config:
    """`owned=False`: the added movements go into `Phase.overlap_movements`
    (shown and checked, invisible to the controller and to timing plans)
    instead of `green_movements`. Owned overlaps make every phase carry the
    free turns' queues: on arterial_lh at heavy demand no phase could gap out
    and person-delay rose 45-70 % on training seeds (2026-10-11)."""
    cm = cfg.conflict_matrix

    def clash(a: str, b: str) -> bool:
        return b in cm.get(a, frozenset()) or a in cm.get(b, frozenset())

    signalled = sorted({m for p in cfg.phases.values() for m in p.green_movements}, key=_index)
    phases: dict[str, Phase] = {}
    for pid, ph in cfg.phases.items():
        if ph.is_pedestrian:
            phases[pid] = ph
            continue
        shown = set(ph.green_movements)
        added: set[str] = set()
        for m in signalled:
            if m in shown or m in exclude or any(clash(m, x) for x in shown | added):
                continue
            added.add(m)
        if not owned:
            phases[pid] = replace(ph, overlap_movements=frozenset(added))
            continue
        if not added:
            phases[pid] = ph
            continue
        protected = ph.protected_movements or ph.green_movements
        phases[pid] = replace(ph, green_movements=frozenset(shown | added),
                              protected_movements=frozenset(protected | added))
    return replace(cfg, phases=phases)
