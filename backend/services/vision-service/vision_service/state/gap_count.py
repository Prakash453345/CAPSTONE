"""Queue beyond the camera's view, by counting vehicles in and out (M8).

**Why this exists.** Every approach camera sees about 100 m back from its
stop line, and a queue on a 600 m lane does not stop at 100 m. The camera
also loses the queue before it loses the lane: vehicles further back hide
behind the ones in front, so the visible queue ends 45-70 m back even when
the real one runs to 450 m. The estimator's truncation rule (the queue
reaching the edge of the view) therefore never fires on the lanes where it
matters, and those lanes read as a queue of 11 PCU or less whatever is
really there. That is what turned heavy seed 5 into a long jam: at
`cluster_1880441740_4393296791` the shared lane `470178558_2` really held
20-65 halted vehicles for most of an hour while the camera's estimate stayed
at 11 PCU or less, so the
controller kept giving its green to the approaches it could see in full, and
the lane spilled back to the junction upstream
(`baselines/2026-09-29_m8_heavy_jam/`, which also has the oracle run: the
true out-of-view queue added back, and the jam gone).

Extrapolating the queue's growth past the edge of view (the estimator's
`horizon_quantile`, shockwave style) was tried in the M8 review and judged
worse on two seeds -- a margin that later measurement showed is inside
heavy demand's seed-to-seed noise, but a count is the better signal anyway.

**What this does instead: conservation, measured at both ends.** Most long
approach lanes are also the *receiving* lane of the junction upstream, whose
camera sees their first 100 m. So the corridor films both ends of the unseen
stretch. For each approach edge with such an upstream view, two count lines
are drawn across every lane of the edge:

* line A across the middle of the upstream view;
* line B across the middle of the approach camera's near view, where
  vehicles are still close enough to track through a queue.

Vehicles (in PCU) crossing A add to the stretch between the lines, vehicles
crossing B leave it, and what the cameras can see between the lines is
subtracted. What is left is out of sight: on the unseen stretch, or hidden
behind other vehicles in the far half of the near view (which is where the
camera under-counts a queue it can see). Of that, the PCU that left the
upstream view within the time it takes to drive the unseen stretch is
counted as still in transit; the rest is queued.

**Entries** -- edges nobody films upstream -- have no line A. Their inflow
is the arrival rate learned at line B while no queue stands there (what
crosses B then is what arrives), frozen while one does. Without them a
junction is only partly counted, and the first version, which counted the
filmed edges alone, unbalanced exactly the junction it was for: the counted
approach's queue rose to the truth while an entry's stayed under-counted,
and the entry's phase lost time (heavy seed 4: +28.5 %).

**Where the count is allowed to speak.** A queue grows back from the stop
line, so a queue that runs out of sight first stands across line B. The
evidence is read in a zone `b_zone_m` either side of B -- the middle of the
near view, not its far end: at 60-100 m from the camera a standing queue is
mostly hidden behind its own front, and the first version, which read the
far end, took that for an empty road and threw a real queue of about 38 PCU away
(heavy seed 5). The hidden PCU is shared among the lanes that have had a
stopped vehicle in the zone within `evidence_s` (longer than any green the
corridor gives one lane), in proportion to how much they did; a lane without
that evidence gets none, whatever the count says.

**Re-anchoring.** Counting drifts (a missed track, a fragment counted twice:
counted inflow ran 0-15 % below the true one), so the count is thrown away
and restarted from "only traffic in transit" whenever the view proves
nothing is queued past it:

* every lane's zone has been *empty* -- no vehicle at all, moving or
  stopped -- for `clear_s` at once. A queue that reached B would stand, or
  discharge, through the zone; an empty one means every lane's queue ends
  short of B, so nothing past it can be queued. Or
* no lane has had a stopped vehicle in its zone for `evidence_s`.

The count therefore only runs free during an episode of queueing past B.

**Only a large hidden queue is reported** (`report_above_pcu`, 10 PCU per
edge; the excess over it). Below that the lane estimate is exactly what it
would be without counting. Reporting everything (version 2) fixed seed 5
but was +4.4 % (n.s.) on the ten held-out heavy seeds; with the threshold,
ordinary runs are left exactly as they were and only a large hidden queue
changes anything. With the threshold (chosen before its runs, not tuned), heavy
demand, ten seeds each: held-out mean -0.9 % (n.s.) and worst run 593k
against 729k; TRAIN mean -0.2 % and worst run 602k against 702k; medium
demand bit-identical. Its effect is on the runaway, not the average.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from itms_geo.coverage import LaneCoverage


@dataclass(frozen=True)
class GapConfig:
    min_view_m: float = 30.0          # an upstream view shorter than this is not used
    min_unseen_m: float = 40.0        # a shorter unseen stretch holds too little to count
    b_zone_m: float = 10.0            # either side of line B: where a queue past it shows
    evidence_s: float = 240.0         # longer than the longest green one lane gets
    clear_s: float = 3.0              # every lane's zone empty this long: nothing hidden
    jam_pcu_per_m: float = 0.2        # a lane holds at most this much queue (5 m per PCU)
    # Only the excess over this is reported (per edge). Below it the estimate
    # is left exactly as it was without counting, so ordinary runs are not
    # touched; reporting everything was worse in the closed loop (see the
    # module docstring).
    report_above_pcu: float = 10.0
    forget_s: float = 20.0            # a track unseen this long is forgotten
    # Edges nobody films upstream (the corridor's entries): the inflow is the
    # arrival rate learned at line B while no queue stands there.
    entries: bool = True
    entry_free_hold_s: float = 30.0   # no stopped vehicle at B this long: crossings are arrivals
    entry_rate_tau_s: float = 600.0   # time constant of the learned arrival rate


def _runs(cov: LaneCoverage) -> list[tuple[float, float]]:
    """Covered stretches of a lane, as (start, end) in metres from its start."""
    out: list[tuple[float, float]] = []
    start = None
    prev = 0.0
    for s, c in zip(cov.s, cov.covered, strict=True):
        if c and start is None:
            start = float(s)
        if not c and start is not None:
            out.append((start, prev))
            start = None
        prev = float(s)
    if start is not None:
        out.append((start, prev))
    return out


@dataclass
class EdgeGap:
    """The unseen stretch of one approach edge, and its running count."""

    edge_id: str
    lanes: tuple[str, ...]
    s_a: float                        # line A (middle of the upstream view)
    end_a: float                      # where the upstream view ends
    s_b: float                        # line B (middle of the near view)
    cam_a: str | None                 # None: an entry, inflow modelled (see GapConfig)
    cam_b: str
    near_start: dict[str, float]      # per lane: where the near view begins
    unseen_m: dict[str, float]        # per lane: metres nobody sees between A and B
    lag_s: float                      # free-flow time from A to the end of the upstream view
    free_s: float                     # free-flow time across the unseen stretch
    n_between: float = 0.0            # PCU counted between the lines
    hidden: float = 0.0               # PCU queued out of view (edge total)
    anchored: bool = False
    inflow: deque = field(default_factory=deque)             # (t, pcu) crossings of A
    last_s: dict = field(default_factory=dict)               # (cam, track) -> (t, s)
    crossed_a: set = field(default_factory=set)
    crossed_b: set = field(default_factory=set)
    evidence: dict[str, float] = field(default_factory=dict)  # lane -> stopped-at-far-end weight
    last_evidence_t: dict[str, float] = field(default_factory=dict)
    last_busy_t: dict[str, float] = field(default_factory=dict)  # zone had any vehicle
    in_pcu: float = 0.0               # totals, for diagnostics
    out_pcu: float = 0.0
    anchors: int = 0
    rate: float = 0.0                 # entries: learned arrival rate, PCU/s
    last_t: float | None = None
    last_stop_zone_t: float = -1e18   # any lane: a stopped vehicle at B

    @property
    def modelled(self) -> bool:
        return self.cam_a is None

    def share(self, t: float, cfg: GapConfig) -> dict[str, float]:
        """The hidden PCU to report per lane: the edge's excess over
        `report_above_pcu`, shared among the lanes with recent evidence."""
        live = {ln: w for ln, w in self.evidence.items()
                if t - self.last_evidence_t.get(ln, -1e18) <= cfg.evidence_s and w > 0}
        excess = self.hidden - cfg.report_above_pcu
        if excess <= 0 or not live:
            return {}
        total = sum(live.values())
        out = {}
        for ln, w in live.items():
            cap = cfg.jam_pcu_per_m * self.unseen_m[ln]
            out[ln] = min(cap, excess * w / total)
        return out


def build_gaps(network, coverage_by_camera: Mapping[str, Mapping[str, LaneCoverage]],
               approach_lanes: Iterable[str], cfg: GapConfig) -> dict[str, EdgeGap]:
    """One `EdgeGap` per approach edge that a camera films at both ends, with a
    stretch of at least `min_unseen_m` in between on every lane."""
    by_edge: dict[str, list[str]] = {}
    for lid, lane in network.lanes.items():
        by_edge.setdefault(lane.edge_id, []).append(lid)
    edges = {network.lanes[lid].edge_id for lid in approach_lanes if lid in network.lanes}
    gaps: dict[str, EdgeGap] = {}
    for edge in sorted(edges):
        lanes = tuple(sorted(by_edge[edge]))
        per_cam: dict[str, dict[str, list[tuple[float, float]]]] = {}
        for cam, covs in coverage_by_camera.items():
            for ln in lanes:
                if ln in covs:
                    per_cam.setdefault(cam, {})[ln] = _runs(covs[ln])
        # near view: a camera covering every lane up to its end
        cam_b, near_start = None, {}
        for cam in sorted(per_cam):
            runs = per_cam[cam]
            ends = {}
            for ln in lanes:
                length = network.lanes[ln].length
                tail = [r for r in runs.get(ln, []) if r[1] >= length - 3.0]
                if not tail:
                    break
                ends[ln] = tail[-1][0]
            else:
                if cam_b is None or max(ends.values()) < max(near_start.values()):
                    cam_b, near_start = cam, ends
        if cam_b is None:
            continue
        s_b = max(near_start[ln] + (network.lanes[ln].length - near_start[ln]) / 2.0
                  for ln in lanes)
        # upstream view: the camera whose stretch, common to every lane, ends
        # closest to the near view with an unseen gap in between
        best = None
        seen_before = 0.0   # the most any other camera sees of the stretch before the near view
        for cam in sorted(per_cam):
            if cam == cam_b:
                continue
            for ln in lanes:
                seen_before = max(seen_before, sum(
                    max(0.0, min(r[1], near_start[ln]) - r[0]) for r in per_cam[cam].get(ln, [])))
            common_end = None
            common_start = None
            for ln in lanes:
                cand = [r for r in per_cam[cam].get(ln, [])
                        if r[1] <= near_start[ln] - cfg.min_unseen_m]
                if not cand:
                    common_end = None
                    break
                r = max(cand, key=lambda r: r[1])
                common_end = r[1] if common_end is None else min(common_end, r[1])
                common_start = r[0] if common_start is None else max(common_start, r[0])
            if common_end is None or common_end - common_start < cfg.min_view_m:  # type: ignore[operator]
                continue
            if best is None or common_end > best[2]:
                best = (cam, common_start, common_end)
        speed = max(1.0, min(network.lanes[ln].speed for ln in lanes))
        if best is None:
            if cfg.entries and min(near_start.values()) >= cfg.min_unseen_m \
                    and seen_before < cfg.min_view_m:
                gaps[edge] = EdgeGap(edge_id=edge, lanes=lanes, s_a=0.0, end_a=0.0, s_b=s_b,
                                     cam_a=None, cam_b=cam_b, near_start=near_start,
                                     unseen_m=dict(near_start), lag_s=0.0,
                                     free_s=min(near_start.values()) / speed)
            continue
        cam_a, start_a, end_a = best
        s_a = (start_a + end_a) / 2.0  # type: ignore[operator]
        unseen = {ln: max(0.0, near_start[ln] - end_a) for ln in lanes}
        gaps[edge] = EdgeGap(edge_id=edge, lanes=lanes, s_a=s_a, end_a=end_a, s_b=s_b,
                             cam_a=cam_a, cam_b=cam_b, near_start=near_start, unseen_m=unseen,
                             lag_s=(end_a - s_a) / speed,
                             free_s=(min(near_start.values()) - end_a) / speed)
    return gaps


def update_gap(gap: EdgeGap, t: float, tracks_by_lane: Mapping[str, list],
               cfg: GapConfig) -> None:
    """One tick. `tracks_by_lane`: the estimator's cleaned tracks (furniture
    and duplicates removed) for this edge's lanes."""
    in_pcu = out_pcu = 0.0
    visible = 0.0
    dt = 0.0 if gap.last_t is None else max(0.0, t - gap.last_t)
    gap.last_t = t
    for ln in gap.lanes:
        stopped_zone = 0.0
        busy_zone = False
        for g in tracks_by_lane.get(ln, ()):
            if gap.s_a < g.s < gap.s_b:
                visible += g.pcu
            if abs(g.s - gap.s_b) <= cfg.b_zone_m:
                busy_zone = True
                if g.stopped:
                    stopped_zone += g.pcu
            key = (g.camera_id, g.track_id)
            prev = gap.last_s.get(key)
            gap.last_s[key] = (t, g.s)
            if prev is None:
                continue
            if g.camera_id == gap.cam_a and prev[1] < gap.s_a <= g.s and key not in gap.crossed_a:
                gap.crossed_a.add(key)
                in_pcu += g.pcu
            if g.camera_id == gap.cam_b and prev[1] < gap.s_b <= g.s and key not in gap.crossed_b:
                gap.crossed_b.add(key)
                out_pcu += g.pcu
        if stopped_zone > 0:
            gap.last_evidence_t[ln] = t
            gap.last_stop_zone_t = t
        if busy_zone:
            gap.last_busy_t[ln] = t
        # evidence weight: stopped PCU in the zone, averaged over evidence_s
        w = gap.evidence.get(ln, 0.0)
        gap.evidence[ln] = w + (stopped_zone - w) / max(1.0, cfg.evidence_s)
    for key in [k for k, (tt, _) in gap.last_s.items() if t - tt > cfg.forget_s]:
        del gap.last_s[key]
        gap.crossed_a.discard(key)
        gap.crossed_b.discard(key)
    if gap.modelled:
        if dt > 0 and t - gap.last_stop_zone_t >= cfg.entry_free_hold_s:
            # nothing standing at B for a while: what crosses it is what arrives
            a = min(1.0, dt / cfg.entry_rate_tau_s)
            gap.rate += a * (out_pcu / dt - gap.rate)
        in_pcu = gap.rate * dt
    if in_pcu:
        gap.inflow.append((t, in_pcu))
    while gap.inflow and t - gap.inflow[0][0] > gap.lag_s + gap.free_s:
        gap.inflow.popleft()
    gap.in_pcu += in_pcu
    gap.out_pcu += out_pcu
    gap.n_between += in_pcu - out_pcu
    queued_somewhere = any(t - gap.last_evidence_t.get(ln, -1e18) <= cfg.evidence_s
                           for ln in gap.lanes)
    # in transit: what crossed A too recently to have reached the back of a
    # queue -- over the whole free-flow time when nothing is queued out of view,
    # less as a hidden queue shortens the drive to its back
    lanes_q = max(1, sum(1 for ln in gap.lanes
                         if t - gap.last_evidence_t.get(ln, -1e18) <= cfg.evidence_s))
    back_m = gap.hidden / (cfg.jam_pcu_per_m * lanes_q)
    drive_s = gap.free_s * max(0.0, 1.0 - back_m / max(1.0, min(gap.unseen_m.values())))
    # past the upstream view (older than lag_s) but not yet at the queue's back
    transit = sum(p for tt, p in gap.inflow if gap.lag_s < t - tt <= gap.lag_s + drive_s)
    all_clear = all(t - gap.last_busy_t.get(ln, -1e18) >= cfg.clear_s for ln in gap.lanes)
    if not queued_somewhere or all_clear or not gap.anchored:
        # nothing queued out of view: the stretch holds only traffic in transit
        if gap.hidden > 0 or not gap.anchored:
            gap.anchors += 1
        gap.n_between = visible + sum(p for tt, p in gap.inflow if t - tt > gap.lag_s)
        gap.anchored = True
        gap.hidden = 0.0
        return
    gap.hidden = max(0.0, gap.n_between - visible - transit)
