"""Per-link traffic state from every camera at once -- the sensor-equivalence
layer. Its output is keyed and measured exactly like
`sim_service/signal_controller/queue_state.py`'s `QueueSample`:

    queue_pcu[l]            PCU-weighted *stopped* vehicles on l's approach lane
    approaching_pcu[l]      PCU-weighted moving vehicles on l's approach lane
                            that reach the stop line within the arrival horizon
    receiving_occupancy[l]  fraction of l's receiving lane covered by vehicles
    receiving_queue_pcu[l]  PCU-weighted stopped vehicles on the receiving lane

plus what no simulator reading ever needed: a **confidence** per link, built
from causes that can be named.

**Per lane first, then per link.** Several links share an approach lane and
one lane is often both one junction's receiving lane and the next junction's
approach, so each lane is estimated once, from every camera that sees it,
and links read the lane estimates.

**Cross-camera duplicates.** Where two cameras see the same stretch of lane,
a vehicle appears twice. Tracks on the same lane within `dedup_radius_m` of
each other along the lane, from different cameras, are merged, keeping the
better-resolved one.

**Queue past the edge of view (build guide §3.2.3).** A queue grows back from
the stop line. When its back reaches the end of what the cameras cover, the
visible count is a lower bound. From then on the hidden part is extrapolated
from how fast the back of the queue was moving just before it left the view
-- the back-of-queue shockwave of Lighthill-Whitham-Richards traffic theory --
at the density measured in the visible part, capped at the lane's length.
The longer that lasts, the less the estimate is trusted.

That rule rarely fires on the lanes that need it: vehicles at the back hide
behind the ones in front, so a visible queue ends 45-70 m back while the
real one runs to hundreds of metres. So the queue past the view is also
**counted** (`gap_count.py`): vehicles in at the upstream junction's view of
the lane (or, on an entry, the arrival rate learned while nothing queued),
out at the near view, less what can be seen in between and what is still
driving through. An edge's counted queue above 10 PCU replaces the growth
extrapolation on its queued lanes; below that the lane is left as this rule
made it. It exists for the runaway: heavy seed 5, whose lane really held
20-65 halted vehicles against 11 PCU or less seen, went from 729k s
person-delay to 585k.

**Furniture.** Roadside clutter the detector keeps calling a vehicle (a
billboard, a parked cart, a shadow) produces tracks that never move -- and,
because a flickering false detection keeps losing its track, tracks that are
re-born every few tens of seconds, so "this track is old and never moved"
alone does not catch it. The estimator therefore *learns the scene*: every
2 m ground cell accumulates the time never-moved tracks have spent in it
(decaying over ten minutes). A cell with more than a minute of that is
clutter, and a never-moved track in a clutter cell -- or any never-moved
track older than any red phase -- is not queue. A real queued vehicle has
arrived, so it has moved.

**Confidence** = coverage x health x visibility x truncation, each in [0, 1]
and each reported:

- coverage: how much of the lane, from the stop line back, is covered,
  against the first `required_approach_m` (the stretch the controller's
  queue and arrival terms mostly live in);
- health: the worst health score among the cameras covering the lane;
- visibility: `1 - 0.3 x` the share of the lane's PCU that is coasting
  (carried by its motion model because something hides it), smoothed over
  ~30 s -- one motorcycle behind a bus for a second is not a reason to stop
  trusting a whole approach;
- truncation: decays from `trunc_conf_start` to `trunc_conf_floor` over
  `trunc_conf_decay_s` while the queue runs past the view.

The receiving lane contributes mildly (`0.9 + 0.1 x` its confidence): a
missing receiving reading makes the controller's spillback term read zero,
which is the same thing it assumes wherever it has no data.

**A road SUMO splits into several edges** (`lane_chains`, from
`itms_domain.lane_chains`; added 2026-09-29). Where a turn bay or a tag
change cuts an approach into edges, the link's approach lane is only the
last stretch. A link then also reads the lanes that continue it, as
`queue_state.QueueStateSampler` does with simulator data: their queues
(share-weighted), their arrivals by distance to the stop line, and the
coverage of the road from the stop line back across them; a receiving
lane's occupancy is weighted over what the cameras cover of its
continuation. Not given (the default), or on a network with no such
splits, nothing changes. The counted queue past the view (`gap_count.py`)
still works per edge and does not follow a chain.

**A lane blocked at its head** (`blocked`, added 2026-10-03; the controller
side is `sim_service/control/strategies/hol.py`). A vehicle waiting inside
the junction box -- a turner yielding to oncoming traffic -- with the lane's
front vehicle stopped right behind it: the lane has a green and nothing
moves. A stop-bar loop cannot tell that from a queue discharging; a camera
that sees the box can -- which the approach cameras do not (the box is
under their frame), so this reads the junction-overview cameras
(`cameras.py`, role `"box"`) and nothing else. Each signal link has a path
through the box (`RoadNetwork.box_paths`), starting 10 m before the stop
line. A track is *on a lane's paths* when it lies within `block_lateral_m`
of one of them, not heading across it, and *in the box* when its nose is
also at least `block_nose_m` past the stop line. The lane is blocked when
the in-box track nearest the stop line is standing and the first vehicle
behind it is standing within `block_gap_m` of its tail. Only tracks of the
junction's own overview camera count, matched to a detection this frame,
past the minimum track age and seen to arrive; two tracks overlapping by
more than `block_overlap_m` are one vehicle, not a pair. With no overview
camera nothing is ever reported blocked. Which movement the
waiting vehicle is making is *not* reported: where a turner waits, 4 m into
a single-lane junction, its path and the through path are 0.2 m apart at
the vehicle's centre, less than the position error, so the links of the
lane are all reported blocked by `BLOCKER_UNKNOWN` and the controller works
out which yielding movement it must be.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import numpy as np
from itms_domain.signal import BLOCKER_UNKNOWN
from itms_geo.coverage import LaneCoverage, merge_coverage
from itms_geo.road import BoxPath, heading_diff

from vision_service.cameras import CameraRig
from vision_service.records import GroundTrack
from vision_service.state.gap_count import EdgeGap, GapConfig, build_gaps, update_gap


@dataclass(frozen=True)
class EstimatorConfig:
    arrival_horizon_s: float = 8.0       # matches queue_state._ARRIVAL_HORIZON_S
    required_approach_m: float = 60.0
    required_receiving_m: float = 30.0
    lead_max_m: float = 15.0             # a queue starts within this of the stop line
    queue_gap_m: float = 10.0            # max clear gap between queued vehicles
    truncation_margin_m: float = 8.0
    growth_window_s: float = 20.0
    max_growth_mps: float = 6.0
    # How the hidden part grows while the queue runs past the view: 0 =
    # linearly at the growth rate measured just before (the first version);
    # > 0 = that rate decaying with this time constant, because arrivals come
    # in platoons and a platoon's rate does not last. The first version
    # over-shot: on held-out seed 1 (heavy, perfect detection) truncated
    # lane-ticks -- 1.6 % of the total -- carried +12 PCU of error each and
    # *all* of the gate's +0.17 PCU bias. Chosen on TRAIN seed 101 (heavy,
    # perfect detection) among linear / 30 / 90 s and a 60 s growth window:
    # 30 s cut the truncated part's error from 0.081 to 0.067 PCU per
    # link-tick; a 60 s window under-shot (-0.088).
    hidden_tau_s: float = 30.0
    # The occlusion horizon. A camera looking down a queue loses the queue
    # before it loses the lane: vehicles further back hide behind the ones
    # in front (from 10 m up, a bus hides the cars in the fifth of the
    # distance behind it), so the visible queue stops short of the covered
    # length and the queue never "reaches the edge of the view". Measured on
    # the corridor: a 599 m lane covered to 98 m showed queues ending at
    # 77 m while the true queue ran to 100-150 m, and such lanes carried the
    # gate's whole heavy-demand under-count. The estimator therefore learns,
    # per lane, how far back it has ever actually seen a queue end (a high
    # quantile, so one glitch does not set it) and treats that as the edge
    # of the view for truncation.
    #
    # **Off by default (0), on the controller's evidence.** At 0.9 it did what
    # it was built to do to the bias -- heavy-demand queue bias on the two
    # TRAIN seeds -0.55 -> -0.36 and -0.17 -> -0.03 PCU per link, mean error
    # no better (0.759 -> 0.747, 0.369 -> 0.393) -- and it made the
    # controller worse: CC-A-CAMP on those cameras (`trust`, heavy) had
    # 21.8 % and 14.7 % more person-delay on the same two seeds. Extrapolating
    # every queue that reaches a learned, shorter horizon turns a
    # systematic under-count into noisy over-counts on the approaches the
    # controller is deciding between, and a pressure controller is more
    # sensitive to the second. Kept, and tested, for a controller that can
    # use it; see baselines/2026-09-25_m8_review/.
    horizon_quantile: float = 0.0
    horizon_min_samples: int = 120
    # Queue past the view, counted rather than extrapolated (`gap_count.py`):
    # every approach edge filmed at both ends, and the entries by their
    # learned arrival rate. Only a large counted queue is reported.
    gap_counting: bool = True
    gap: GapConfig = field(default_factory=GapConfig)
    trunc_conf_start: float = 0.95
    trunc_conf_floor: float = 0.7
    trunc_conf_decay_s: float = 180.0
    dedup_radius_m: float = 3.0
    # A lane blocked at its head (module docstring). `block_nose_m`: how far
    # past the stop line a vehicle's nose must be for it to count as inside
    # the junction (a queue's first vehicle stops at the line, give or take
    # the position error). `block_gap_m`: the simulator's own test is 3 m
    # bumper to bumper (`queue_state._BLOCK_GAP_M`); the camera's allows for
    # two vehicle positions' worth of error. `block_speed_mps` is the ground
    # tracker's own stopping threshold.
    block_nose_m: float = 2.0
    block_lateral_m: float = 1.5
    block_gap_m: float = 4.5
    block_speed_mps: float = 0.8
    block_heading_moved_m: float = 2.0
    block_arrived_m: float = 1.0
    block_overlap_m: float = 1.0
    min_track_age_s: float = 0.6
    visibility_weight: float = 0.3
    visibility_tau_s: float = 30.0
    # A track that has sat still since it was born for this long is roadside
    # furniture the detector keeps mistaking for a vehicle (or a parked
    # vehicle): either way it is not waiting for a green, so it is not queue.
    furniture_age_s: float = 90.0
    furniture_moved_m: float = 1.5
    clutter_cell_m: float = 2.0
    clutter_dwell_s: float = 60.0       # never-moved dwell that marks a cell as clutter
    clutter_tau_s: float = 600.0
    # The stop-bar cross-check compares a loop over the last 20 m of the
    # approach lane (`sim.closed_loop.STOPBAR_ZONE_M`) with the vehicles the
    # cameras see on the approach. Where the approach lane is shorter than
    # this (a 4 m stretch after a turn bay opens, a 0.2 m link inside a
    # joined light), a vehicle over the loop is tracked on the lane before
    # it, so vehicles on the lanes feeding it within this distance of the
    # stop line count as seen too.
    seen_zone_m: float = 30.0


def _standing(g: GroundTrack, below_mps: float) -> bool:
    return g.stopped or (g.speed_known and g.speed < below_mps)


@dataclass
class LaneEstimate:
    lane_id: str
    stopped_pcu: float = 0.0
    approaching_pcu: float = 0.0
    occupancy: float = 0.0
    queue_back_m: float = 0.0
    truncated: bool = False
    hidden_m: float = 0.0
    hidden_pcu: float = 0.0
    covered_from_end_m: float = 0.0
    covered_from_start_m: float = 0.0
    covered_fraction: float = 0.0
    c_health: float = 0.0
    c_visibility: float = 1.0
    c_truncation: float = 1.0
    n_tracks: int = 0
    cameras: tuple[str, ...] = ()

    @property
    def queue_pcu(self) -> float:
        return self.stopped_pcu + self.hidden_pcu


@dataclass
class LinkEstimate:
    tls_id: str
    link: str
    queue_pcu: float
    approaching_pcu: float
    receiving_occupancy: float
    receiving_queue_pcu: float
    confidence: float
    c_coverage: float
    c_health: float
    c_visibility: float
    c_truncation: float
    c_receiving: float
    truncated: bool
    hidden_m: float
    cameras: tuple[str, ...]
    # vehicles tracked anywhere on the link's approach edge (every lane of it):
    # the stop-bar cross-check's "does this camera see anything here" --
    # per-lane counts miss a car the tracker put in the next lane
    vehicles_seen: int = 0


@dataclass
class _LaneMemory:
    history: deque = field(default_factory=lambda: deque(maxlen=120))  # (t, queue_back_m)
    truncated_since: float | None = None
    growth_mps: float = 0.0
    coast_ewma: float = 0.0
    backs: deque = field(default_factory=lambda: deque(maxlen=1800))  # non-zero queue backs
    horizon_m: float | None = None
    n_backs: int = 0


class LinkStateEstimator:
    def __init__(
        self,
        rig: CameraRig,
        approach_links: Mapping[str, Mapping[str, str]],
        receiving_links: Mapping[str, Mapping[str, str]],
        config: EstimatorConfig | None = None,
        lane_chains: tuple[Mapping, Mapping] | None = None,
    ):
        self.rig = rig
        self.approach_links = approach_links
        self.receiving_links = receiving_links
        self.cfg = config or EstimatorConfig()
        # `itms_domain.lane_chains`: {lane: [(lane, share, offset_m)]}
        self.upstream, self.downstream = lane_chains or ({}, {})
        self._memory: dict[str, _LaneMemory] = {}
        self.lanes: dict[str, LaneEstimate] = {}
        self.lane_tracks: dict[str, list[GroundTrack]] = {}
        self.links: dict[tuple[str, str], LinkEstimate] = {}
        self.t = 0.0
        self._clutter: dict[tuple[str, int, int], float] = {}
        self._cov_cache: dict[tuple[str, tuple[str, ...]], LaneCoverage] = {}
        self._clutter_t: float | None = None
        self._clean: dict[str, list[GroundTrack]] = {}
        self._feeders = self._short_approach_feeders()
        self.blocked: dict[str, dict[str, str]] = {}
        """`{tls: {link: BLOCKER_UNKNOWN}}`: the links whose lane is blocked at
        its head this tick (`JunctionContext.blocked_by`)."""
        # tls -> approach lane -> [(link, its path through the box)]
        self._box: dict[str, dict[str, list[tuple[str, BoxPath]]]] = {}
        self._box_circle: dict[str, tuple[np.ndarray, float]] = {}
        for tls, links in approach_links.items():
            paths = rig.network.box_paths.get(tls, {})
            for link, lane_id in links.items():
                if link in paths and lane_id in rig.network.lanes:
                    self._box.setdefault(tls, {}).setdefault(lane_id, []).append(
                        (link, paths[link]))
            if tls in self._box:
                pts = np.vstack([p.path.shape for ps in self._box[tls].values() for _, p in ps])
                centre = pts.mean(axis=0)
                self._box_circle[tls] = (
                    centre, float(np.sqrt(((pts - centre) ** 2).sum(axis=1)).max()) + 3.0)
        self.gaps: dict[str, EdgeGap] = {}
        if self.cfg.gap_counting:
            lanes = {ln for links in approach_links.values() for ln in links.values()}
            self.gaps = build_gaps(rig.network, rig.coverage_by_camera, lanes, self.cfg.gap)

    # ---- lanes ----------------------------------------------------------------

    def _dedup(self, tracks: list[GroundTrack]) -> list[GroundTrack]:
        if len(tracks) < 2:
            return tracks
        tracks = sorted(tracks, key=lambda g: g.s)
        kept: list[GroundTrack] = []
        for g in tracks:
            dup = -1
            for i in range(len(kept) - 1, -1, -1):
                k = kept[i]
                if g.s - k.s > self.cfg.dedup_radius_m:
                    break
                if k.camera_id != g.camera_id:
                    dup = i
                    break
            if dup < 0:
                kept.append(g)
            elif g.resolution_m_per_px < kept[dup].resolution_m_per_px:
                kept[dup] = g
        return kept

    def _queue_back(self, length: float, tracks: list[GroundTrack]) -> float:
        """Distance from the stop line to the back of the contiguous stopped
        queue that starts at it; 0 when the vehicle nearest the stop line is
        not stopped (or there is none)."""
        stopped = sorted((g for g in tracks if g.stopped), key=lambda g: -g.s)
        if not stopped:
            return 0.0
        first = stopped[0]
        if length - (first.s + first.length_m / 2.0) > self.cfg.lead_max_m:
            return 0.0
        back = length - (first.s - first.length_m / 2.0)
        prev = first
        for g in stopped[1:]:
            gap = (prev.s - prev.length_m / 2.0) - (g.s + g.length_m / 2.0)
            if gap > self.cfg.queue_gap_m:
                break
            back = length - (g.s - g.length_m / 2.0)
            prev = g
        return max(0.0, back)

    def _cell(self, g: GroundTrack) -> tuple[str, int, int]:
        c = self.cfg.clutter_cell_m
        return (g.camera_id, int(g.xy[0] // c), int(g.xy[1] // c))

    def _learn_clutter(self, t: float, tracks: Iterable[GroundTrack]) -> None:
        cfg = self.cfg
        dt = 1.0 if self._clutter_t is None else max(0.0, t - self._clutter_t)
        self._clutter_t = t
        if dt > 0:
            decay = math.exp(-dt / cfg.clutter_tau_s)
            for k in list(self._clutter):
                self._clutter[k] *= decay
                if self._clutter[k] < 0.5:
                    del self._clutter[k]
        for g in tracks:
            if g.moved_m < cfg.furniture_moved_m and not g.coasting:
                key = self._cell(g)
                self._clutter[key] = self._clutter.get(key, 0.0) + dt

    def _is_furniture(self, t: float, g: GroundTrack) -> bool:
        cfg = self.cfg
        if g.moved_m >= cfg.furniture_moved_m:
            return False
        if t - g.born_t >= cfg.furniture_age_s:
            return True
        return self._clutter.get(self._cell(g), 0.0) >= cfg.clutter_dwell_s

    def _working_coverage(self, lane_id: str, health: Mapping[str, float]) -> tuple[
        LaneCoverage | None, tuple[str, ...]
    ]:
        """Coverage of a lane by the cameras that are still working, and
        those cameras. A lane two cameras see keeps the view of the one
        that is left when the other fails -- the first version took the
        *minimum* health over every camera that saw the lane, so one dead
        camera zeroed lanes a neighbour's camera still covered in full."""
        cams = tuple(self.rig.cameras_by_lane.get(lane_id, ()))
        working = tuple(c for c in cams if health.get(c, 1.0) > 0.0)
        if working == cams:
            return self.rig.coverage(lane_id), cams
        if not working:
            return None, cams
        key = (lane_id, working)
        cov = self._cov_cache.get(key)
        if cov is None:
            cov = merge_coverage([self.rig.coverage_by_camera[c][lane_id] for c in working])
            self._cov_cache[key] = cov
        return cov, working

    def _estimate_lane(self, t: float, lane_id: str, tracks: list[GroundTrack],
                       health: Mapping[str, float]) -> LaneEstimate:
        cfg = self.cfg
        lane = self.rig.network.lanes[lane_id]
        cov, cams = self._working_coverage(lane_id, health)
        est = LaneEstimate(lane_id=lane_id, cameras=cams)
        if cov is None:
            return est  # nobody (working) sees this lane: confidence 0 via coverage
        est.covered_from_end_m = cov.covered_from_end_m
        est.covered_from_start_m = cov.covered_from_start_m
        est.covered_fraction = cov.fraction
        est.c_health = min((health.get(c, 1.0) for c in cams), default=0.0)

        tracks = [
            g for g in tracks
            if t - g.born_t >= cfg.min_track_age_s and not self._is_furniture(t, g)
        ]
        tracks = self._dedup(tracks)
        self._clean[lane_id] = tracks
        est.n_tracks = len(tracks)
        mem = self._memory.setdefault(lane_id, _LaneMemory())
        # Visibility: the share of real vehicles *inside* the frame that the
        # detector is not currently seeing (occlusion, glare, misses). Two
        # kinds of track are left out, because their coasting says nothing
        # about whether vehicles can be seen:
        # - a box touching the frame edge: the vehicle is entering or leaving
        #   view, and ByteTrack coasts it past the edge for a moment;
        # - a track that never drove (`moved_m` below the furniture limit):
        #   a flickering false positive on a billboard coasts most of the
        #   time, forever.
        # The first version counted both. Measured on the corridor: detector
        # hotspot tracks were three quarters of all coasting on the worst
        # lane, links read "25 % unseen" with nothing hidden, and CC-A-CAMP's
        # ladder dropped to fixed-time on 5-8 % of junction-ticks for no
        # physical reason.
        inside = [g for g in tracks
                  if not g.at_border and g.moved_m >= cfg.furniture_moved_m]
        if inside:
            coast = sum(g.pcu for g in inside if g.coasting) / max(1e-6, sum(g.pcu for g in inside))
            a = min(1.0, 1.0 / cfg.visibility_tau_s)
            mem.coast_ewma += a * (coast - mem.coast_ewma)
        est.c_visibility = 1.0 - cfg.visibility_weight * mem.coast_ewma

        occ_len = 0.0
        for g in tracks:
            if g.stopped:
                est.stopped_pcu += g.pcu
            else:
                front = g.s + g.length_m / 2.0
                dist = max(0.0, lane.length - front)
                # a just-born track has no measured speed yet: assume it is
                # travelling at the lane's limit (it was moving to get here)
                v = g.speed if g.speed_known else lane.speed
                if dist / max(v, 0.1) <= cfg.arrival_horizon_s:
                    est.approaching_pcu += g.pcu
            occ_len += g.length_m
        covered_m = max(cov.covered_m, 1e-6)
        est.occupancy = float(min(1.0, occ_len / covered_m))

        # queue back, truncation, extrapolation
        back = self._queue_back(lane.length, tracks)
        est.queue_back_m = back
        view_end = cov.covered_from_end_m
        if back > 0.0:
            mem.backs.append(back)
            mem.n_backs += 1
            if cfg.horizon_quantile > 0 and mem.n_backs >= cfg.horizon_min_samples and \
                    mem.n_backs % 30 == 0:  # refresh every 30 samples, not every tick
                mem.horizon_m = float(np.quantile(np.asarray(mem.backs), cfg.horizon_quantile))
        if mem.horizon_m is not None:
            view_end = min(view_end, max(mem.horizon_m, cfg.lead_max_m + cfg.truncation_margin_m))
        truncated = view_end < lane.length - 1.0 and back >= view_end - cfg.truncation_margin_m \
            and back > 0.0
        if truncated:
            if mem.truncated_since is None:
                mem.truncated_since = t
                mem.growth_mps = self._growth(mem, t)
            dur = t - mem.truncated_since
            grown = mem.growth_mps * (cfg.hidden_tau_s * (1.0 - math.exp(-dur / cfg.hidden_tau_s))
                                      if cfg.hidden_tau_s > 0 else dur)
            hidden = min(grown, max(0.0, lane.length - view_end))
            stopped_visible = [g for g in tracks if g.stopped]
            density = (sum(g.pcu for g in stopped_visible) / max(back, 1.0)) if back > 0 else 0.0
            est.truncated = True
            est.hidden_m = hidden
            est.hidden_pcu = density * hidden
            frac = min(1.0, dur / cfg.trunc_conf_decay_s)
            est.c_truncation = cfg.trunc_conf_start - frac * (cfg.trunc_conf_start -
                                                              cfg.trunc_conf_floor)
        else:
            mem.truncated_since = None
            mem.history.append((t, back))
        return est

    def _growth(self, mem: _LaneMemory, t: float) -> float:
        pts = [(tt, b) for tt, b in mem.history if t - tt <= self.cfg.growth_window_s]
        if len(pts) < 3:
            return 0.0
        ts = np.array([p[0] for p in pts])
        bs = np.array([p[1] for p in pts])
        if np.ptp(ts) < 1e-6:
            return 0.0
        slope = float(np.polyfit(ts, bs, 1)[0])
        return float(np.clip(slope, 0.0, self.cfg.max_growth_mps))

    def _count_gaps(self, t: float, health: Mapping[str, float]) -> None:
        """The counted queue past the view (`gap_count.py`), where it is
        reported, replaces the growth extrapolation on that lane; anywhere
        else the lane is left exactly as the estimator made it. An edge whose
        count-line camera is down is left alone, and its count restarts when
        the camera is back."""
        cfg = self.cfg
        for gap in self.gaps.values():
            if health.get(gap.cam_a, 1.0) <= 0.0 or health.get(gap.cam_b, 1.0) <= 0.0:  # type: ignore[arg-type]
                gap.anchored = False
                gap.hidden = 0.0
                continue
            update_gap(gap, t, {ln: self._clean.get(ln, []) for ln in gap.lanes}, cfg.gap)
            share = gap.share(t, cfg.gap)
            for ln in gap.lanes:
                est = self.lanes.get(ln)
                if est is None:
                    continue
                pcu = share.get(ln, 0.0)
                if pcu > 0.0:
                    stopped = [g for g in self._clean.get(ln, []) if g.stopped]
                    density = sum(g.pcu for g in stopped) / max(est.queue_back_m, 1.0) \
                        if est.queue_back_m > 0 else cfg.gap.jam_pcu_per_m
                    est.hidden_pcu = pcu
                    est.hidden_m = pcu / max(density, 0.05)
                    est.truncated = True
                    est.c_truncation = cfg.trunc_conf_start

    # ---- a road split into several edges -------------------------------------

    def _short_approach_feeders(self) -> dict[str, list[tuple[str, float]]]:
        """For each approach lane shorter than `seen_zone_m`: the lanes that
        feed it, back to that distance from the stop line, each with the
        distance from its end to the stop line. Any node, U-turns aside --
        this is about where a vehicle over the loop is tracked, not about
        whose queue it is."""
        net = self.rig.network
        zone = self.cfg.seen_zone_m
        preds: dict[str, list[str]] = {}
        for c in net.connections:
            if c.direction not in ("t", "T"):
                preds.setdefault(c.to_lane, []).append(c.from_lane)
        out: dict[str, list[tuple[str, float]]] = {}
        for lane_id in {ln for links in self.approach_links.values() for ln in links.values()}:
            if lane_id not in net.lanes or net.lanes[lane_id].length >= zone:
                continue
            found: list[tuple[str, float]] = []
            frontier, seen = [(lane_id, 0.0)], {lane_id}
            while frontier:
                cur, off = frontier.pop()
                end = off + net.lanes[cur].length
                if end >= zone:
                    continue
                for p in preds.get(cur, []):
                    if p in net.lanes and p not in seen:
                        seen.add(p)
                        found.append((p, end))
                        frontier.append((p, end))
            if found:
                out[lane_id] = found
        return out

    def _seen_feeding(self, lane_id: str) -> int:
        """Tracked vehicles on `_feeders[lane_id]` within `seen_zone_m` of the
        stop line."""
        net = self.rig.network
        n = 0
        for p, off in self._feeders.get(lane_id, ()):
            length = net.lanes[p].length
            n += sum(1 for g in self._clean.get(p, [])
                     if max(0.0, length - (g.s + g.length_m / 2.0)) + off <= self.cfg.seen_zone_m)
        return n

    def _approaching_on(self, lane_id: str, offset_m: float) -> float:
        """`approaching_pcu`'s test on a lane that ends `offset_m` before the
        stop line."""
        cfg = self.cfg
        lane = self.rig.network.lanes[lane_id]
        total = 0.0
        for g in self._clean.get(lane_id, []):
            if g.stopped:
                continue
            dist = max(0.0, lane.length - (g.s + g.length_m / 2.0)) + offset_m
            v = g.speed if g.speed_known else lane.speed
            if dist / max(v, 0.1) <= cfg.arrival_horizon_s:
                total += g.pcu
        return total

    def _road_covered(self, a: LaneEstimate, length: float, chain) -> tuple[float, float]:
        """`(covered, road)`: metres covered from the stop line back without a
        gap, across the chain, and the road's length. Lanes side by side (the
        same offset) count by the best-covered of them."""
        covered = a.covered_from_end_m
        road = length
        levels: dict[float, list[str]] = {}
        for x, _, off in chain:
            levels.setdefault(off, []).append(x)
            road = max(road, off + self.rig.network.lanes[x].length)
        if covered < length - 1.0:
            return covered, road
        for off in sorted(levels):
            best = max((self.lanes[x].covered_from_end_m for x in levels[off]
                        if x in self.lanes), default=0.0)
            covered = off + best
            if best < min(self.rig.network.lanes[x].length for x in levels[off]) - 1.0:
                break
        return covered, road

    # ---- a lane blocked at its head ------------------------------------------

    def _find_blocked(self, box_tracks: list[GroundTrack]) -> dict[str, dict[str, str]]:
        """See the module docstring. `box_tracks`: this tick's ground tracks
        from the junction-overview cameras. A coasting track is where the
        tracker's motion model thinks a vehicle it cannot see has got to,
        which for a vehicle that stopped out of sight is somewhere it never
        went; only tracks matched to a detection this frame are used."""
        cfg = self.cfg
        out: dict[str, dict[str, str]] = {}
        # Tracks that can be believed: matched to a detection this frame,
        # old enough not to be a one-frame flicker, and seen to arrive (a
        # track that has never moved is roadside clutter the detector keeps
        # calling a vehicle, as in the lane estimate -- a vehicle waiting in
        # the box drove there).
        live = [g for g in box_tracks
                if not g.coasting and self.t - g.born_t >= cfg.min_track_age_s
                and max(g.moved_m, g.displaced_m) >= cfg.block_arrived_m]
        if not self._box or len(live) < 2:
            return out
        specs = self.rig.specs
        for tls, by_lane in self._box.items():
            centre, radius = self._box_circle[tls]
            # this junction's own overview camera only: the next junction's
            # sees this box from 200 m away, if at all
            near = [g for g in live
                    if getattr(specs.get(g.camera_id), "tls_id", tls) == tls
                    and float(((g.xy - centre) ** 2).sum()) <= radius * radius]
            if len(near) < 2:
                continue
            xy = np.stack([g.xy for g in near])
            for paths in by_lane.values():
                # each track's place along this lane's paths, on the path it is
                # nearest to; s is measured from the stop line (negative before it)
                best_s = np.full(len(near), np.nan)
                best_lat = np.full(len(near), np.inf)
                for _, box in paths:
                    s, lat, hdg = box.path.project(xy)
                    for i, g in enumerate(near):
                        if abs(lat[i]) >= best_lat[i]:
                            continue
                        # crossing or oncoming traffic -- judged only for a
                        # track that has been seen driving: one born standing
                        # still has no heading worth the name
                        if (g.moved_m >= cfg.block_heading_moved_m
                                and math.isfinite(g.heading_deg)
                                and float(heading_diff(g.heading_deg, hdg[i])) > 60.0):
                            continue
                        best_lat[i], best_s[i] = abs(lat[i]), s[i] - box.stop_s
                on = [(float(best_s[i]), g) for i, g in enumerate(near)
                      if best_lat[i] <= cfg.block_lateral_m]
                in_box = [(s - g.length_m / 2.0, g) for s, g in on
                          if s + g.length_m / 2.0 >= cfg.block_nose_m]
                behind = [(s + g.length_m / 2.0, g) for s, g in on
                          if s + g.length_m / 2.0 < cfg.block_nose_m]
                if not in_box or not behind:
                    continue
                tail, blocker = min(in_box, key=lambda x: x[0])
                nose, front = max(behind, key=lambda x: x[0])
                # two tracks overlapping along the path are one vehicle seen
                # twice, or two abreast -- not one behind the other
                if (_standing(blocker, cfg.block_speed_mps)
                        and _standing(front, cfg.block_speed_mps)
                        and -cfg.block_overlap_m <= tail - nose <= cfg.block_gap_m):
                    out.setdefault(tls, {}).update(
                        dict.fromkeys((k for k, _ in paths), BLOCKER_UNKNOWN))
        return out

    # ---- main --------------------------------------------------------------

    def update(
        self,
        t: float,
        tracks: Iterable[GroundTrack],
        health: Mapping[str, float] | None = None,
        *,
        box_tracks: Iterable[GroundTrack] = (),
    ) -> dict[tuple[str, str], LinkEstimate]:
        """`tracks`: this tick's ground tracks from every approach camera,
        with lanes assigned. `health`: camera id -> [0, 1] (missing = 1.0).
        `box_tracks`: the junction-overview cameras' tracks, read only by
        the blocked-lane test."""
        self.t = t
        health = health or {}
        tracks = list(tracks)
        self._learn_clutter(t, tracks)
        by_lane: dict[str, list[GroundTrack]] = {}
        for g in tracks:
            if g.lane_id is None or not g.lane_agrees:
                continue
            by_lane.setdefault(g.lane_id, []).append(g)
        needed = set(by_lane)
        for links in self.approach_links.values():
            needed.update(links.values())
        for links in self.receiving_links.values():
            needed.update(links.values())
        for chains in (self.upstream, self.downstream):
            for ln in [ln for ln in needed if ln in chains]:
                needed.update(x for x, _, _ in chains[ln])
        self.lanes = {
            lid: self._estimate_lane(t, lid, by_lane.get(lid, []), health)
            for lid in needed
            if lid in self.rig.network.lanes
        }
        self.lane_tracks = by_lane
        self.blocked = self._find_blocked(list(box_tracks))
        self._count_gaps(t, health)
        self.links = {}
        cfg = self.cfg
        net = self.rig.network
        seen_on_edge: dict[str, int] = {}
        for lid, le in self.lanes.items():
            edge = net.lanes[lid].edge_id
            seen_on_edge[edge] = seen_on_edge.get(edge, 0) + le.n_tracks
        for tls, links in self.approach_links.items():
            for link, a_lane in links.items():
                a = self.lanes.get(a_lane)
                r_lane = self.receiving_links.get(tls, {}).get(link)
                r = self.lanes.get(r_lane) if r_lane else None
                if a is None:
                    continue
                lane = self.rig.network.lanes[a_lane]
                queue, approaching = a.queue_pcu, a.approaching_pcu
                c_trunc, truncated, hidden_m = a.c_truncation, a.truncated, a.hidden_m
                covered, road = a.covered_from_end_m, lane.length
                up = self.upstream.get(a_lane)
                if up:
                    for x, share, off in up:
                        xe = self.lanes.get(x)
                        if xe is None:
                            continue
                        queue += share * xe.queue_pcu
                        approaching += share * self._approaching_on(x, off)
                        if xe.truncated:
                            c_trunc = min(c_trunc, xe.c_truncation)
                            truncated = True
                            hidden_m += share * xe.hidden_m
                    covered, road = self._road_covered(a, lane.length, up)
                need_a = min(road, cfg.required_approach_m)
                c_cov = min(1.0, covered / need_a) if need_a > 0 else 0.0
                r_occ = r.occupancy if r is not None else 0.0
                r_queue = r.queue_pcu if r is not None else 0.0
                if r is not None:
                    rl = self.rig.network.lanes[r.lane_id]
                    need_r = min(rl.length, cfg.required_receiving_m)
                    c_r_cov = min(1.0, r.covered_from_start_m / need_r) if need_r > 0 else 0.0
                    c_recv = c_r_cov * r.c_health
                    down = self.downstream.get(r.lane_id)
                    if down:
                        # occupancy over what the cameras cover of the road
                        seen = r.covered_fraction * rl.length
                        occ = r.occupancy * seen
                        for x, share, _ in down:
                            xe = self.lanes.get(x)
                            if xe is None:
                                continue
                            xs = share * xe.covered_fraction * self.rig.network.lanes[x].length
                            occ += xe.occupancy * xs
                            seen += xs
                            r_queue += share * xe.queue_pcu
                        r_occ = occ / seen if seen > 0 else r.occupancy
                else:
                    c_recv = 0.0
                conf = c_cov * a.c_health * a.c_visibility * c_trunc * \
                    (0.9 + 0.1 * c_recv)
                self.links[(tls, link)] = LinkEstimate(
                    tls_id=tls,
                    link=link,
                    queue_pcu=queue,
                    approaching_pcu=approaching,
                    receiving_occupancy=r_occ,
                    receiving_queue_pcu=r_queue,
                    confidence=float(max(0.0, min(1.0, conf))),
                    c_coverage=c_cov,
                    c_health=a.c_health,
                    c_visibility=a.c_visibility,
                    c_truncation=c_trunc,
                    c_receiving=c_recv,
                    truncated=truncated,
                    hidden_m=hidden_m,
                    cameras=a.cameras,
                    vehicles_seen=seen_on_edge.get(lane.edge_id, 0) + (
                        self._seen_feeding(a_lane) if a_lane in self._feeders else 0),
                )
        return self.links

    def queue_sample(self, tls_id: str) -> dict[str, dict[str, float]]:
        """The four `QueueSample` dicts plus `confidence`, for one junction --
        field names identical to `JunctionContext`'s."""
        out: dict[str, dict[str, float]] = {
            "queue_pcu": {},
            "approaching_pcu": {},
            "receiving_occupancy": {},
            "receiving_queue_pcu": {},
            "confidence": {},
            "vehicles_seen": {},
        }
        for (tls, link), e in self.links.items():
            if tls != tls_id:
                continue
            out["queue_pcu"][link] = e.queue_pcu
            out["approaching_pcu"][link] = e.approaching_pcu
            out["receiving_occupancy"][link] = e.receiving_occupancy
            out["receiving_queue_pcu"][link] = e.receiving_queue_pcu
            out["confidence"][link] = e.confidence
            out["vehicles_seen"][link] = float(e.vehicles_seen)
        return out


def summarise_confidence(links: Mapping[tuple[str, str], LinkEstimate]) -> dict[str, float]:
    if not links:
        return {"mean": math.nan, "min": math.nan, "below_0.8": math.nan}
    c = np.array([e.confidence for e in links.values()])
    return {"mean": float(c.mean()), "min": float(c.min()), "below_0.8": float((c < 0.8).mean())}
