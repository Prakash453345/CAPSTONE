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

- `split_variants`: for a phase that serves two or more approaches, one
  *variant* per single-lane approach whose turn yields to another
  approach's protected stream: the base phase with exactly those streams
  stopped, and nothing else changed. With the stream it was yielding to
  stopped, the turner goes. A variant is not in the ring; it is a way of
  realising its base phase.
- `internal_links`: which junction-internal lane belongs to which signal
  link, so a vehicle seen waiting inside the box can be attributed to its
  movement (`QueueStateSampler` uses it to report `blocked_by`).

The decision logic is `HolAwareCamp` in `hol_camp.py`.

**Why a variant is the base phase with streams taken away, and nothing
added.** Two earlier designs gave the blocked approach a green of its own
with every movement protected, and each failed an independent review:

1. *All of the other approach stopped, this approach's green kept through
   the change.* The other approach's yielding turner, waiting in the box,
   gets a yellow while the oncoming through keeps its green, takes the
   oncoming stream to be stopping too, and turns into it: the yellow trap.
   (Entered by an ordinary change instead -- everything through yellow and
   all-red -- the trap is gone and so, on training seeds, is the gain at
   moderate demand: `dev13`, `dev15`.)
2. *The other approach's yielding turn left permissive, this approach's
   turn made protected.* No yellow trap; but a protected green is a promise
   that nothing conflicting moves without yielding to it, and the kept
   turn's obligation to yield (the network's right-of-way relation) did not
   always run that way: at some junctions of the district and Berlin
   networks it merged into the same exit lane as the newly protected turn,
   and neither would yield.

A variant now shows every movement exactly as its base phase shows it
(protected stays protected, permissive stays permissive) or not at all, and
the only movements it takes away are protected ones. So:

- every pair of movements green together in a variant is green together,
  in the same way, in the base phase -- a variant cannot contain a conflict
  the base phase does not;
- no permissive movement is ever stopped by entering one, so nobody waiting
  in the box is shown a yellow while the stream they yield to runs on.

`Tier0Config.alternate_problems` checks both for every alternate; the runner
refuses a junction that fails and the kernel refuses a plan that steps into
an alternate that fails. The runner carries a green through a change only
when the cabinet confirms, from the two signal states, that the change stops
protected links and does nothing else (`TraCICabinet.can_carry`). The
approach's turn stays permissive in the variant: it still yields to an
opposing turner, as it did. A base phase with a pedestrian crossing gets no
variants (a crossing's clearance is not a vehicle's).

**The way out of a variant is an ordinary change.** Going back to the base
phase starts the stopped through again. A third review pointed out what
carrying the greens through *that* would mean: turners who have had a free
run through the box, their signal unchanged, meet an oncoming stream that
starts with no warning to them ("late release", which signal practice
avoids for that reason). So everything that starts, starts from an all-red:
leaving a variant, for its base phase or for any other phase, puts the
whole junction through yellow and all-red. Only the change *in* -- an early
cut-off of the opposing stream -- keeps its greens.

What this asks of the street: the other approach's turn must be able to
keep its permissive indication while its through shows red, i.e. a separate
turn face on each approach (a flashing-yellow-arrow head or its
equivalent). With one shared face the turner would be shown the yellow
after all.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Collection, Mapping
from dataclasses import replace
from pathlib import Path

from itms_domain import Phase, Tier0Config

VARIANT_SEP = "@"


def edge_of(lane_id: str) -> str:
    return lane_id.rsplit("_", 1)[0]


def _no_vehicle_lane(lane: str | None) -> bool:
    """A movement that does not come from a road lane: a pedestrian crossing
    (some lane maps leave it out, some give its walking area, whose id, like
    every junction-internal lane's, starts with a colon)."""
    return lane is None or lane.startswith(":")


def _by_approach(phase: Phase, lane_of: Mapping[str, str]) -> dict[str, set[str]]:
    """`{approach edge: its movements in this phase}`."""
    by_edge: dict[str, set[str]] = {}
    for m in phase.green_movements:
        lane = lane_of.get(m)
        if not _no_vehicle_lane(lane):
            by_edge.setdefault(edge_of(lane), set()).add(m)  # type: ignore[arg-type]
    return by_edge


def split_variants(
    cfg: Tier0Config, lane_of: Mapping[str, str], *, single_lane_only: bool = True,
    pedestrian: Collection[str] = (),
) -> tuple[dict[str, Phase], dict[str, str]]:
    """`(variant phases, {variant id: base phase id})` for one junction.

    `lane_of` is `{movement: approach lane}` (`link_lanes.link_to_lane_map`).
    A variant `P0@1` is base phase `P0` without the protected movements of
    other approaches that a permissive movement of approach 1 conflicts
    with (the streams its turn yields to); every other movement is shown as
    `P0` shows it (module docstring). One is made for an approach only when

    - the base phase serves at least two approach edges and has no
      pedestrian crossing: none of its movements is in `pedestrian`
      (`pedestrian_links`, the signal links the network gives to a crossing
      -- one index can carry a crossing *and* a vehicle connection, which a
      lane map alone would hide) or lacks a road lane in `lane_of`,
    - there is something to stop: the approach has a permissive movement
      that conflicts with a protected movement of another approach,
    - a protected movement remains once it is stopped,
    - the result is not a signal state the ring already has, and
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
    (`HolConfig.whole_approach`; both measured with the first design of the
    variant). False makes variants for multi-lane approaches too.
    """
    phases: dict[str, Phase] = {}
    base_of: dict[str, str] = {}
    for pid in cfg.ring_order:
        phase = cfg.phases[pid]
        if phase.is_pedestrian or any(m in pedestrian or _no_vehicle_lane(lane_of.get(m))
                                      for m in phase.green_movements):
            continue
        by_edge = _by_approach(phase, lane_of)
        if len(by_edge) < 2:
            continue
        protected = phase.protected_movements or frozenset()
        for k, edge in enumerate(sorted(by_edge)):
            own = by_edge[edge]
            yielding = own - protected
            stop = frozenset(
                o for o in (phase.green_movements - own) & protected
                if any(o in cfg.conflict_matrix.get(m, frozenset())
                       or m in cfg.conflict_matrix.get(o, frozenset()) for m in yielding))
            if not stop:
                continue
            if single_lane_only and len({lane_of[m] for m in own}) != 1:
                continue
            green = phase.green_movements - stop
            if not protected & green:
                # nothing protected would be left, and a phase with no
                # protected movement is read as "all protected" by the
                # cabinet and the kernel (`protected_movements or
                # green_movements`): it would be shown as what it is not
                continue
            vid = f"{pid}{VARIANT_SEP}{k}"
            variant = Phase(vid, green, protected_movements=protected & green)
            # A phase that already shows exactly this (a ring phase, or the
            # variant just built for another approach): the cabinet tells
            # phases apart by their signal state.
            if any(p.green_movements == variant.green_movements
                   and (p.protected_movements or frozenset()) == variant.protected_movements
                   for p in (*cfg.phases.values(), *phases.values())):
                continue
            phases[vid] = variant
            base_of[vid] = pid
    return phases, base_of


def own_movements(cfg: Tier0Config, lane_of: Mapping[str, str], variant_id: str,
                  base_id: str) -> frozenset[str]:
    """The movements of the approach variant `variant_id` exists for (its
    index after the separator is the approach's place among the base
    phase's approach edges, sorted)."""
    by_edge = _by_approach(cfg.phases[base_id], lane_of)
    k = int(variant_id.rsplit(VARIANT_SEP, 1)[1])
    return frozenset(by_edge[sorted(by_edge)[k]])


def with_split_variants(
    cfg: Tier0Config, lane_of: Mapping[str, str], *, single_lane_only: bool = True,
    pedestrian: Collection[str] = (),
) -> tuple[Tier0Config, dict[str, str]]:
    """`cfg` with its split variants added to `phases` (not to the ring),
    each with its base phase's green bounds, and `{variant: base}`."""
    extra, base_of = split_variants(cfg, lane_of, single_lane_only=single_lane_only,
                                    pedestrian=pedestrian)
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
    """A probe, not a controller: every ring phase that serves two or more
    approaches with a conflict between them is replaced in the ring by one
    phase per approach, that approach alone with every movement protected.
    The upper bound on what removing permissive blocking can do, at the
    price of serving opposing approaches one after the other."""
    phases: dict[str, Phase] = {}
    ring: list[str] = []
    base_of: dict[str, str] = {}
    for pid in cfg.ring_order:
        phase = cfg.phases[pid]
        by_edge = {} if phase.is_pedestrian else _by_approach(phase, lane_of)
        split = []
        if len(by_edge) >= 2:
            for k, edge in enumerate(sorted(by_edge)):
                own = by_edge[edge]
                others = phase.green_movements - own
                if any(cfg.conflict_matrix.get(m, frozenset()) & others for m in own) and not any(
                        cfg.conflict_matrix.get(m, frozenset()) & own for m in own):
                    vid = f"{pid}{VARIANT_SEP}{k}"
                    split.append(Phase(vid, frozenset(own), protected_movements=frozenset(own)))
        for p in split or [phase]:
            phases[p.id] = p
            ring.append(p.id)
            base_of[p.id] = pid
    if len(ring) == len(cfg.ring_order):
        return cfg
    bound = lambda table: {p: table[base_of[p]] for p in ring if base_of[p] in table}  # noqa: E731
    return replace(cfg, phases=phases, ring_order=tuple(ring),
                   min_green_s=bound(cfg.min_green_s), max_green_s=bound(cfg.max_green_s))


def pedestrian_links(net_path: str | Path) -> dict[str, frozenset[str]]:
    """`{tls id: the signal links that control a pedestrian crossing}`, read
    from the network: a signalled connection that starts on a junction's own
    edge (a crossing or a walking area; their ids start with a colon)."""
    out: dict[str, set[str]] = {}
    for c in ET.parse(net_path).getroot().findall("connection"):
        tls = c.get("tl")
        if not tls or not c.get("from", "").startswith(":"):
            continue
        for key in ("linkIndex", "linkIndex2"):
            if c.get(key) is not None:
                out.setdefault(tls, set()).add(f"L{c.get(key)}")
    return {tls: frozenset(v) for tls, v in out.items()}


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
