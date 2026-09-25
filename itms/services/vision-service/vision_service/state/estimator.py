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
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import numpy as np
from itms_geo.coverage import LaneCoverage, merge_coverage

from vision_service.cameras import CameraRig
from vision_service.records import GroundTrack


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
    trunc_conf_start: float = 0.95
    trunc_conf_floor: float = 0.7
    trunc_conf_decay_s: float = 180.0
    dedup_radius_m: float = 3.0
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
    ):
        self.rig = rig
        self.approach_links = approach_links
        self.receiving_links = receiving_links
        self.cfg = config or EstimatorConfig()
        self._memory: dict[str, _LaneMemory] = {}
        self.lanes: dict[str, LaneEstimate] = {}
        self.lane_tracks: dict[str, list[GroundTrack]] = {}
        self.links: dict[tuple[str, str], LinkEstimate] = {}
        self.t = 0.0
        self._clutter: dict[tuple[str, int, int], float] = {}
        self._cov_cache: dict[tuple[str, tuple[str, ...]], LaneCoverage] = {}
        self._clutter_t: float | None = None

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

    # ---- main --------------------------------------------------------------

    def update(
        self,
        t: float,
        tracks: Iterable[GroundTrack],
        health: Mapping[str, float] | None = None,
    ) -> dict[tuple[str, str], LinkEstimate]:
        """`tracks`: this tick's ground tracks from every camera, with lanes
        assigned. `health`: camera id -> [0, 1] (missing = 1.0)."""
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
        self.lanes = {
            lid: self._estimate_lane(t, lid, by_lane.get(lid, []), health)
            for lid in needed
            if lid in self.rig.network.lanes
        }
        self.lane_tracks = by_lane
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
                need_a = min(lane.length, cfg.required_approach_m)
                c_cov = min(1.0, a.covered_from_end_m / need_a) if need_a > 0 else 0.0
                if r is not None:
                    rl = self.rig.network.lanes[r.lane_id]
                    need_r = min(rl.length, cfg.required_receiving_m)
                    c_r_cov = min(1.0, r.covered_from_start_m / need_r) if need_r > 0 else 0.0
                    c_recv = c_r_cov * r.c_health
                else:
                    c_recv = 0.0
                conf = c_cov * a.c_health * a.c_visibility * a.c_truncation * \
                    (0.9 + 0.1 * c_recv)
                self.links[(tls, link)] = LinkEstimate(
                    tls_id=tls,
                    link=link,
                    queue_pcu=a.queue_pcu,
                    approaching_pcu=a.approaching_pcu,
                    receiving_occupancy=r.occupancy if r is not None else 0.0,
                    receiving_queue_pcu=r.queue_pcu if r is not None else 0.0,
                    confidence=float(max(0.0, min(1.0, conf))),
                    c_coverage=c_cov,
                    c_health=a.c_health,
                    c_visibility=a.c_visibility,
                    c_truncation=a.c_truncation,
                    c_receiving=c_recv,
                    truncated=a.truncated,
                    hidden_m=a.hidden_m,
                    cameras=a.cameras,
                    vehicles_seen=seen_on_edge.get(lane.edge_id, 0),
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
