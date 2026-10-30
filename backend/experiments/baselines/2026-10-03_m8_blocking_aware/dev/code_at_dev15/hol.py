"""Head-of-line blocking: one vehicle waiting to turn across oncoming traffic
holds up every vehicle behind it in the same lane.

A max-pressure controller assumes a lane with a green drains at its
saturation flow. On a lane shared by several movements that is false whenever
the vehicle at the front cannot go: a right-turner (left-hand traffic) on a
permissive green waits inside the junction for a gap in the oncoming stream,
its tail still in the lane, and the through traffic behind it stands under a
green that does nothing. Traced on a 3x3 grid of single-lane roads
(`scenarios/generated/narrow_lh`, TRAIN seed 101, medium): before the grid
locks, about half of the lane-samples whose front vehicle is stopped on its
own green have a stopped vehicle in the junction box directly ahead of it.
The lanes behind then fill, spill into the junctions upstream, and both
Webster and CC-A-CAMP end in gridlock.

This module holds what is static about the remedy:

- `split_variants`: for a phase that serves two or more approaches with a
  conflict between them (a permissive turn), one *variant* per single-lane
  approach: that approach alone, every movement protected. Running the
  variant lets the turner go without yielding. A variant is not in the
  ring; it is a way of realising its base phase.
- `internal_links`: which junction-internal lane belongs to which signal
  link, so a vehicle seen waiting inside the box can be attributed to its
  movement (`QueueStateSampler` uses it to report `blocked_by`).

The decision logic is `HolAwareCamp` in `hol_camp.py`.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from itms_domain import Phase, Tier0Config

VARIANT_SEP = "@"


def edge_of(lane_id: str) -> str:
    return lane_id.rsplit("_", 1)[0]


def split_variants(
    cfg: Tier0Config, lane_of: Mapping[str, str], *, single_lane_only: bool = True
) -> tuple[dict[str, Phase], dict[str, str]]:
    """`(variant phases, {variant id: base phase id})` for one junction.

    `lane_of` is `{movement: approach lane}` (`link_lanes.link_to_lane_map`).
    A variant `P0@1` is the movements of base phase `P0` that come from one
    approach edge, all protected. One is made for an approach only when

    - the base phase serves at least two approach edges,
    - some movement of this approach conflicts with a movement of another
      approach that is green in the same phase (so something yields),
    - no two movements of the approach conflict with each other, and
    - (`single_lane_only`, the default) every movement of the approach
      leaves from the same lane.

    The last condition is the difference between a lane that is blocked and
    an approach that is stalled. On a single shared lane a waiting turner
    holds up everything the approach has. With a second lane the approach
    keeps discharging, vehicles change lanes around the turner, and stopping
    the opposite approach for the blocked lane's sake buys one flowing lane
    with another at the price of a change interval: on the two-lane grid
    (`grid3_lh`, heavy demand, TRAIN seeds 101-103) variants for any blocked
    lane cost 30 % more delay than CC-A-CAMP on every seed, and 7 % with the
    variant allowed only while no other lane of the approach had a queue
    (`HolConfig.whole_approach`). False makes variants for multi-lane
    approaches too -- those two arms.
    """
    phases: dict[str, Phase] = {}
    base_of: dict[str, str] = {}
    for pid in cfg.ring_order:
        phase = cfg.phases[pid]
        if phase.is_pedestrian:
            continue
        by_edge: dict[str, set[str]] = {}
        for m in phase.green_movements:
            lane = lane_of.get(m)
            if lane is not None:
                by_edge.setdefault(edge_of(lane), set()).add(m)
        if len(by_edge) < 2:
            continue
        for k, edge in enumerate(sorted(by_edge)):
            own = by_edge[edge]
            others = phase.green_movements - own
            opposed = any(cfg.conflict_matrix.get(m, frozenset()) & others for m in own)
            internal = any(cfg.conflict_matrix.get(m, frozenset()) & own for m in own)
            if not opposed or internal:
                continue
            if single_lane_only and len({lane_of[m] for m in own}) != 1:
                continue
            # A ring phase that already is this approach alone, all protected:
            # the variant would show the same signal state, and the cabinet
            # tells phases apart by their state.
            if any(p.green_movements == frozenset(own)
                   and (p.protected_movements or frozenset()) >= frozenset(own)
                   for p in cfg.phases.values()):
                continue
            vid = f"{pid}{VARIANT_SEP}{k}"
            phases[vid] = Phase(vid, frozenset(own), protected_movements=frozenset(own))
            base_of[vid] = pid
    return phases, base_of


def with_split_variants(
    cfg: Tier0Config, lane_of: Mapping[str, str], *, single_lane_only: bool = True
) -> tuple[Tier0Config, dict[str, str]]:
    """`cfg` with its split variants added to `phases` (not to the ring),
    each with its base phase's green bounds, and `{variant: base}`."""
    extra, base_of = split_variants(cfg, lane_of, single_lane_only=single_lane_only)
    if not extra:
        return cfg, {}
    return replace(
        cfg,
        alternates={**cfg.alternates, **base_of},
        phases={**cfg.phases, **extra},
        min_green_s={**cfg.min_green_s, **{v: cfg.min_green_s[b] for v, b in base_of.items()}},
        max_green_s={**cfg.max_green_s,
                     **{v: cfg.max_green_s[b] for v, b in base_of.items()
                        if b in cfg.max_green_s}},
    ), base_of


def as_split_ring(cfg: Tier0Config, lane_of: Mapping[str, str]) -> Tier0Config:
    """A probe, not a controller: every base phase that has variants is
    replaced in the ring by them (one approach at a time, all protected).
    The upper bound on what removing permissive blocking can do, at the
    price of serving opposing approaches one after the other."""
    extra, base_of = split_variants(cfg, lane_of, single_lane_only=False)
    if not extra:
        return cfg
    ring: list[str] = []
    for pid in cfg.ring_order:
        mine = sorted(v for v, b in base_of.items() if b == pid)
        ring.extend(mine or [pid])
    phases = {p: (extra[p] if p in extra else cfg.phases[p]) for p in ring}
    bound = lambda table: {p: table[base_of.get(p, p)] for p in ring  # noqa: E731
                           if base_of.get(p, p) in table}
    return replace(cfg, phases=phases, ring_order=tuple(ring),
                   min_green_s=bound(cfg.min_green_s), max_green_s=bound(cfg.max_green_s))


def internal_links(net_path: str | Path) -> dict[str, dict[str, str]]:
    """`{tls id: {junction-internal lane id: "L{i}"}}`: the signal link each
    internal lane carries, following a link through its internal junction
    (`via` chains), so a vehicle inside the box is attributed to its movement."""
    root = ET.parse(net_path).getroot()
    first: dict[str, tuple[str, str]] = {}      # first internal lane -> (tls, link)
    nxt: dict[str, list[str]] = {}              # internal lane -> following internal lanes
    for c in root.findall("connection"):
        via = c.get("via")
        if not via:
            continue
        frm = c.get("from", "")
        if frm.startswith(":"):
            nxt.setdefault(f"{frm}_{c.get('fromLane')}", []).append(via)
        elif c.get("tl") and c.get("linkIndex") is not None:
            first[via] = (c.get("tl", ""), f"L{c.get('linkIndex')}")
    out: dict[str, dict[str, str]] = {}
    for lane, (tls, link) in first.items():
        stack, seen = [lane], set()
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            out.setdefault(tls, {})[cur] = link
            stack.extend(nxt.get(cur, []))
    return out
