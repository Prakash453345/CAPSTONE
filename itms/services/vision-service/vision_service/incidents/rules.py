"""Phase-aware, auditable incident rules -- the M6 plan's Stream 2.

No learned "accident classifier". Each rule is a short, explainable test over
ground tracks and the live signal state, produces a score in [0, 1] with the
evidence that produced it, and is attributed to the controlled links (`L{i}`)
the affected lane feeds -- the same node ids the M6 graph detector scores, so
`vision_score` slots straight into `control/anomaly/fusion.py`.

- `stuck_on_green`: the lead stopped vehicle in a lane, with clear road
  ahead, stays stopped through >= 15 s of *protected* green while a sibling
  lane on the same green is discharging (>= 45 s when there is no
  discharging sibling to compare with), and the receiving lane is not full;
- `midblock_stop`: a vehicle that drove in stays stopped clear of the
  stop-line queue with >= 25 m of empty lane ahead of it -- for >= 15 s if
  vehicles are queuing up behind it, otherwise >= 30 s (>= 90 s for buses
  and auto-rickshaws, which stop to board passengers as routine);
- `wrong_way`: a vehicle travels >= 15 m over >= 3 s against its lane's
  direction;
- `collision_cue`: two vehicles that were apart converge until their
  footprints overlap, then both stay stopped >= 10 s, one having been moving
  fast just before;
- `flow_void`: a mid-block stretch of lane (>= 60 m from the stop line,
  where lane changes for turns concentrate) that normally carries its share
  of traffic sees no vehicle for >= 90 s, while adjacent same-direction lanes keep
  flowing through it *and* vehicles are seen leaving this lane *slowly* for
  a neighbour just upstream of the gap -- an obstruction found by the traffic
  swerving around it, whatever it is. Both extra conditions matter: SUMO and
  real drivers alike leave some lanes empty for minutes by choice (a
  turn-only lane with no turning demand), and neither of those shows
  vehicles swerving out right before the empty stretch.

Why each guard exists:

- *protected* green only: a permissive (`g`) movement waiting for a gap is
  doing exactly what it should;
- receiving lane not full: a vehicle that cannot move on green because the
  exit is jammed is congestion, not an incident;
- "drove in" (5 m travelled fast, *or* 5 m of net progress however slow): a
  detector hotspot on a billboard produces a "vehicle" that is stopped
  forever -- but it never arrived. A vehicle that never moved is furniture.
  The first version counted only fast travel, and a vehicle that eased up
  to the stop line, stalled there and never showed 5 m above 1.5 m/s in
  view could not be flagged at all (found tracing missed incidents);
- "were apart, then converged": ByteTrack can briefly hold two tracks on one
  vehicle; those sit on top of each other from birth and must not read as a
  crash.

ADR-006: there is no person rule. `person` detections exist only to be
blurred.

`IncidentEngine` runs the rules once per controller tick, keeps each hit's
persistence, and raises an `AnomalyCandidate` when a hit holds its score
above `raise_score` for `raise_persist_s`; it resolves the candidate once the
hit has been gone for `clear_s`. A candidate is not an incident: ADR-006's
operator gate still stands between it and any dispatch.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import numpy as np
from itms_geo.road import heading_diff, invert_link_map

from vision_service.classes import VClass
from vision_service.records import GroundTrack

_DWELL_CLASSES = frozenset({VClass.BUS, VClass.AUTO_RICKSHAW})

if TYPE_CHECKING:
    from vision_service.cameras import CameraRig
    from vision_service.state.estimator import LinkStateEstimator


class SignalStateProvider(Protocol):
    def link_state(self, tls_id: str, link: str) -> str:
        """'G' protected green, 'g' permissive green, 'y', 'r', or '' if unknown."""
        ...

    def green_since(self, tls_id: str, link: str) -> float | None: ...


@dataclass(frozen=True)
class RuleConfig:
    stuck_green_s: float = 15.0          # when a sibling lane on the same green discharges
    stuck_green_alone_s: float = 45.0    # when there is no discharging sibling to compare with
    head_clear_m: float = 15.0
    stop_line_zone_m: float = 20.0
    spillback_occupancy: float = 0.6
    midblock_stop_s: float = 30.0
    midblock_stop_dwell_s: float = 90.0  # buses / auto-rickshaws: routine boarding stops
    midblock_impact_s: float = 15.0      # sooner if vehicles are queued up behind it
    midblock_impact_m: float = 30.0
    midblock_clear_ahead_m: float = 25.0
    midblock_queue_margin_m: float = 5.0
    min_arrival_moved_m: float = 5.0
    wrong_way_s: float = 3.0
    wrong_way_min_m: float = 15.0
    wrong_way_min_speed: float = 2.0
    wrong_way_min_diff_deg: float = 150.0
    collision_stop_s: float = 10.0
    collision_overlap: float = 0.5
    collision_prior_speed: float = 5.0
    collision_apart_m: float = 4.0
    void_s: float = 90.0
    void_bin_m: float = 10.0
    void_min_from_stop_line_m: float = 60.0
    void_min_neighbour_passes: int = 5
    void_pass_speed: float = 2.0
    void_min_share: float = 0.3          # lane's long-run passes vs its neighbours'
    void_baseline_tau_s: float = 600.0
    void_min_swerves: int = 3            # vehicles seen leaving the lane just upstream
    void_swerve_window_m: float = 40.0
    void_swerve_max_speed_frac: float = 0.5
    raise_score: float = 0.5
    raise_persist_s: float = 3.0
    clear_s: float = 20.0
    cooldown_s: float = 120.0
    enabled: tuple[str, ...] = ("stuck_on_green", "midblock_stop", "wrong_way",
                                "collision_cue", "flow_void")


# Measured operating points (baselines/2026-09-25_m8_review, Gate 4). Chosen
# by `scripts/m8_incident_analysis.py` on TRAIN seeds against a false-alarm
# budget for the whole corridor, then scored once on held-out seeds, with
# false alarms counted the way the engine raises them (re-raised after it
# clears and cools down -- the first analysis counted one per place per run
# and under-stated every rate):
#
#   quiet   budget 1/h   held-out: 19 % of in-view incidents (5/27), 1.7 false alarms/h
#   assist  budget 10/h  held-out: 19 % (5/27), 10.3 false alarms/h -- `stuck_on_green`
#                        earned its place on TRAIN (30 % -> 35 %) and caught nothing
#                        more on held-out seeds
#   hand_set (the defaults above, all five rules): 37 %, 37 false alarms/h
#
# So `quiet` is the service default: a candidate goes to a person (ADR-006),
# and on held-out seeds `assist` bought no recall for six times the alarms.
# `collision_cue`, `wrong_way` and `flow_void` are off at both points:
# collision fires on overlapping footprints in dense queues, and no injected
# incident exercises wrong-way. `raise_persist_s` 4 s is the analysis'
# "5 consecutive ticks".
OPERATING_POINTS: dict[str, RuleConfig] = {
    "hand_set": RuleConfig(),
    "quiet": RuleConfig(midblock_stop_s=45.0, midblock_stop_dwell_s=60.0,
                        midblock_impact_s=20.0, raise_persist_s=4.0,
                        enabled=("midblock_stop",)),
    "assist": RuleConfig(stuck_green_s=30.0, stuck_green_alone_s=90.0,
                         midblock_stop_s=45.0, midblock_stop_dwell_s=60.0,
                         midblock_impact_s=20.0, raise_persist_s=4.0,
                         enabled=("stuck_on_green", "midblock_stop")),
}
DEFAULT_OPERATING_POINT = "quiet"


# rule -> (anomaly type, severity) in itms_domain.anomaly's vocabulary
RULE_ANOMALY: dict[str, tuple[str, str]] = {
    "stuck_on_green": ("stalled_vehicle", "medium"),
    "midblock_stop": ("vehicle_breakdown", "medium"),
    "wrong_way": ("unknown", "high"),
    "collision_cue": ("accident", "high"),
    "flow_void": ("lane_blockage", "medium"),
}


@dataclass
class RuleHit:
    rule: str
    lane_id: str
    score: float
    s: float
    links: tuple[tuple[str, str], ...]
    evidence: dict


@dataclass
class AnomalyCandidate:
    anomaly_id: str
    rule: str
    anomaly_type: str
    severity: str
    lane_id: str
    edge_id: str
    position_m: float
    links: tuple[tuple[str, str], ...]
    score: float
    first_t: float
    raised_t: float
    evidence: dict
    status: str = "ACTIVE"
    resolved_t: float | None = None


@dataclass
class _HitState:
    first_over_t: float | None = None
    last_seen_t: float = 0.0
    candidate: AnomalyCandidate | None = None
    cooldown_until: float = -math.inf


def _arrived(g: GroundTrack, cfg: RuleConfig) -> bool:
    """Did this "vehicle" drive in, rather than appear where it stands?"""
    return g.moved_m >= cfg.min_arrival_moved_m or g.displaced_m >= cfg.min_arrival_moved_m


def _clip01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


def _ramp(duration: float, threshold: float) -> float:
    """0.5 at the threshold, 1.0 once the condition has held twice as long."""
    if duration < threshold:
        return 0.0
    return _clip01(0.5 + 0.5 * (duration - threshold) / max(threshold, 1e-6))


class IncidentEngine:
    def __init__(
        self,
        rig: CameraRig,
        approach_links: Mapping[str, Mapping[str, str]],
        receiving_links: Mapping[str, Mapping[str, str]],
        config: RuleConfig | None = None,
        signal_state: SignalStateProvider | None = None,
    ):
        self.rig = rig
        self.cfg = config or RuleConfig()
        self.signal = signal_state
        self.approach_links = approach_links
        self.receiving_links = receiving_links
        self._approach_by_lane = invert_link_map(approach_links)
        self._receiving_by_lane = invert_link_map(receiving_links)
        self._wrong: dict[tuple[str, int], tuple[float, np.ndarray]] = {}
        self._bins_seen: dict[str, np.ndarray] = {}       # lane -> last time any track in bin
        self._bins_passes: dict[str, list[list[float]]] = {}  # lane -> per bin moving pass times
        self._bin_covered: dict[str, np.ndarray] = {}
        self._pass_rate: dict[str, np.ndarray] = {}
        self._track_lane: dict[tuple[str, int], tuple[str, float, float]] = {}
        self._swerves: dict[str, list[tuple[float, float]]] = {}
        self._last_obs_t: float | None = None
        self._t0: float | None = None
        self._state: dict[tuple[str, str, object], _HitState] = {}
        self.hits: list[RuleHit] = []
        self.new_candidates: list[AnomalyCandidate] = []
        self.resolved: list[AnomalyCandidate] = []
        self.active: dict[str, AnomalyCandidate] = {}

    # ---- helpers --------------------------------------------------------------------

    def links_for_lane(self, lane_id: str) -> tuple[tuple[str, str], ...]:
        got = self._approach_by_lane.get(lane_id) or self._receiving_by_lane.get(lane_id) or []
        return tuple(got)

    def _state_of(self, tls: str, link: str) -> tuple[str, float | None]:
        if self.signal is None:
            return "", None
        return self.signal.link_state(tls, link), self.signal.green_since(tls, link)

    # ---- rules ----------------------------------------------------------------------

    def _sibling_flowing(self, t: float, lane_id: str, est: LinkStateEstimator) -> bool | None:
        """Is another lane of the same approach, currently served by a
        protected green, discharging (no stopped queue head, and vehicles
        moving near its stop line)? `None` when there is no such lane to
        compare with."""
        net = self.rig.network
        lane = net.lanes[lane_id]
        sibs = [lid for lid in net.edges.get(lane.edge_id, ()) if lid != lane_id
                and lid in self._approach_by_lane and lid in self.rig.coverage_by_lane]
        verdict: bool | None = None
        for sib in sibs:
            if not any(self._state_of(tls, link)[0] == "G"
                       for tls, link in self._approach_by_lane[sib]):
                continue
            verdict = False if verdict is None else verdict
            sl = net.lanes[sib]
            le = est.lanes.get(sib)
            moving = [g for g in est.lane_tracks.get(sib, [])
                      if not g.stopped and g.speed_known and g.speed > 3.0
                      and sl.length - g.s < 60.0]
            if moving and (le is None or le.queue_back_m < 5.0):
                return True
        return verdict

    def _stuck_on_green(self, t: float, lane_id: str, tracks: list[GroundTrack],
                        est: LinkStateEstimator) -> list[RuleHit]:
        cfg = self.cfg
        lane = self.rig.network.lanes[lane_id]
        approach = self._approach_by_lane.get(lane_id)
        if not approach:
            return []
        ordered = sorted(tracks, key=lambda g: -g.s)
        lead_idx = next((i for i, g in enumerate(ordered) if g.stopped), None)
        if lead_idx is None:
            return []
        lead = ordered[lead_idx]
        ahead = ordered[:lead_idx]  # all moving: the lead is the first stopped vehicle
        far_from_stop_line = lane.length - (lead.s + lead.length_m / 2.0) > cfg.stop_line_zone_m
        # Away from the stop line, only a lead with genuinely clear road ahead
        # counts; a moving vehicle just ahead means the queue is starting up.
        if far_from_stop_line and any(g.s - lead.s < cfg.head_clear_m for g in ahead):
            return []
        if not _arrived(lead, cfg) or lead.stopped_since is None:
            return []
        stopped_for = t - lead.stopped_since
        # The comparison that separates a broken-down vehicle from a blocked
        # movement: if a sibling lane on the same green is discharging, this
        # lane's lead has no excuse; if every lane is held (junction box
        # blocked, turning conflict, spillback) it is congestion, and only a
        # much longer hold is suspicious.
        sibling = self._sibling_flowing(t, lane_id, est)
        threshold = cfg.stuck_green_s if sibling else cfg.stuck_green_alone_s
        out = []
        for tls, link in approach:
            state, since = self._state_of(tls, link)
            if state != "G" or since is None:
                continue
            green_for = t - since
            stuck_in_green = min(stopped_for, green_for)
            if stuck_in_green < threshold:
                continue
            recv = self.receiving_links.get(tls, {}).get(link)
            if recv is not None:
                r = est.lanes.get(recv)
                rl = self.rig.network.lanes.get(recv)
                if r is not None and rl is not None and (
                    r.occupancy >= cfg.spillback_occupancy
                    or r.queue_back_m >= rl.length - cfg.stop_line_zone_m
                ):
                    continue
            out.append(RuleHit(
                "stuck_on_green", lane_id, _ramp(stuck_in_green, threshold), lead.s,
                ((tls, link),),
                {"track": [lead.camera_id, lead.track_id], "stopped_s": round(stopped_for, 1),
                 "measure": round(stuck_in_green, 1),
                 "green_s": round(green_for, 1), "sibling_flowing": sibling,
                 "truth_id": lead.truth_id},
            ))
        return out

    def _midblock_stop(self, t: float, lane_id: str, tracks: list[GroundTrack],
                       est: LinkStateEstimator) -> list[RuleHit]:
        cfg = self.cfg
        lane = self.rig.network.lanes[lane_id]
        le = est.lanes.get(lane_id)
        queue_back = le.queue_back_m if le is not None else 0.0
        out = []
        for g in tracks:
            if not g.stopped or g.stopped_since is None or not _arrived(g, cfg):
                continue
            dur = t - g.stopped_since
            front = g.s + g.length_m / 2.0
            if front > lane.length - queue_back - cfg.midblock_queue_margin_m:
                continue  # part of the stop-line queue
            if lane.length - front < cfg.stop_line_zone_m:
                continue  # at the stop line: that is stuck_on_green's case
            ahead = [h for h in tracks if h is not g and 0 < h.s - g.s < cfg.midblock_clear_ahead_m]
            if ahead:
                continue
            # Buses and auto-rickshaws stop mid-block to board passengers as a
            # matter of routine; a stop only becomes suspicious after longer.
            base = cfg.midblock_stop_dwell_s if g.vclass in _DWELL_CLASSES else \
                cfg.midblock_stop_s
            # ...unless it is visibly obstructing: vehicles queued up behind it.
            behind = [h for h in tracks if h is not g and h.stopped
                      and 0 < g.s - h.s < cfg.midblock_impact_m]
            threshold = cfg.midblock_impact_s if len(behind) >= 2 else base
            if dur < threshold:
                continue
            out.append(RuleHit(
                "midblock_stop", lane_id, _ramp(dur, threshold), g.s,
                self.links_for_lane(lane_id),
                {"track": [g.camera_id, g.track_id], "stopped_s": round(dur, 1),
                 "measure": round(dur, 1),
                 "queued_behind": len(behind), "class": str(g.vclass),
                 "truth_id": g.truth_id},
            ))
        return out

    def _wrong_way(self, t: float, all_tracks: list[GroundTrack]) -> list[RuleHit]:
        cfg = self.cfg
        out = []
        live = set()
        for g in all_tracks:
            if g.lane_id is None or g.lane_agrees or g.speed < cfg.wrong_way_min_speed \
                    or not math.isfinite(g.heading_deg):
                continue
            lane = self.rig.network.lanes[g.lane_id]
            diff = float(heading_diff(g.heading_deg, lane.heading_at(g.s)[0]))
            if diff < cfg.wrong_way_min_diff_deg:
                continue
            key = (g.camera_id, g.track_id)
            live.add(key)
            first = self._wrong.setdefault(key, (t, g.xy.copy()))
            dur = t - first[0]
            dist = float(np.hypot(*(g.xy - first[1])))
            if dur >= cfg.wrong_way_s and dist >= cfg.wrong_way_min_m:
                out.append(RuleHit("wrong_way", g.lane_id, 1.0, g.s,
                                   self.links_for_lane(g.lane_id),
                                   {"track": list(key), "heading_diff": round(diff, 1),
                                    "measure": round(dur, 1),
                                    "distance_m": round(dist, 1), "truth_id": g.truth_id}))
        for k in [k for k in self._wrong if k not in live]:
            del self._wrong[k]
        return out

    @staticmethod
    def _recent_speed(g: GroundTrack, before_t: float, window_s: float = 8.0) -> float:
        pts = [p for p in g.history if before_t - window_s <= p[0] <= before_t]
        best = 0.0
        for a, b in zip(pts, pts[1:], strict=False):
            dt = b[0] - a[0]
            if dt > 0:
                best = max(best, math.hypot(b[1] - a[1], b[2] - a[2]) / dt)
        return best

    @staticmethod
    def _were_apart(a: GroundTrack, b: GroundTrack, apart_m: float) -> bool:
        """Did these two tracks' 1 Hz histories ever put them `apart_m` apart
        at the same moment? Two tracks on one vehicle never were."""
        hb = {round(p[0]): p for p in b.history}
        for ta, xa, ya in a.history:
            q = hb.get(round(ta))
            if q is not None and math.hypot(xa - q[1], ya - q[2]) > apart_m:
                return True
        return False

    def _collision(self, t: float, all_tracks: list[GroundTrack]) -> list[RuleHit]:
        cfg = self.cfg
        out: list[RuleHit] = []
        # only stopped, visible, arrived vehicles can be a collision pair
        tr = [g for g in all_tracks if g.lane_id is not None and not g.coasting and g.stopped
              and g.stopped_since is not None and _arrived(g, cfg)
              and t - g.stopped_since >= cfg.collision_stop_s]
        n = len(tr)
        if n < 2:
            return out
        xy = np.stack([g.xy for g in tr])
        lengths = np.array([g.length_m for g in tr])
        d = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1])
        reach = cfg.collision_overlap * (lengths[:, None] + lengths[None, :]) / 2.0
        close = np.triu(d <= reach, k=1)
        for i, j in zip(*np.nonzero(close), strict=True):
            a, b = tr[int(i)], tr[int(j)]
            # Two cameras that both see one vehicle give two tracks in one
            # place; a real collision is two vehicles in *one* camera's view.
            if a.camera_id != b.camera_id:
                continue
            if not self._were_apart(a, b, cfg.collision_apart_m):
                continue
            dur = t - max(a.stopped_since or t, b.stopped_since or t)
            prior = max(self._recent_speed(a, a.stopped_since or t),
                        self._recent_speed(b, b.stopped_since or t))
            if prior < cfg.collision_prior_speed:
                continue
            keys = sorted([[a.camera_id, a.track_id], [b.camera_id, b.track_id]])
            out.append(RuleHit("collision_cue", a.lane_id or "", 1.0, a.s,
                               self.links_for_lane(a.lane_id or ""),
                               {"tracks": keys, "stopped_s": round(dur, 1),
                                "measure": round(dur, 1),
                                "prior_speed_mps": round(prior, 1)}))
        return out

    def _observe_lanes(self, t: float, all_tracks: list[GroundTrack]) -> None:
        """Per-track lane memory -> bin sweeps, passes, and lane changes."""
        cfg = self.cfg
        net = self.rig.network
        bin_m = cfg.void_bin_m
        dt = 1.0 if self._last_obs_t is None else max(1e-3, t - self._last_obs_t)
        self._last_obs_t = t
        decay = math.exp(-dt / cfg.void_baseline_tau_s)
        for lane_id, cov in self.rig.coverage_by_lane.items():
            if lane_id not in self._bin_covered:
                lane = net.lanes[lane_id]
                nb = max(1, int(math.ceil(lane.length / bin_m)))
                mids = np.minimum((np.arange(nb) + 0.5) * bin_m, lane.length)
                self._bin_covered[lane_id] = cov.covers(mids)
                self._bins_seen[lane_id] = np.full(nb, t)
                self._bins_passes[lane_id] = [[] for _ in range(nb)]
                self._pass_rate[lane_id] = np.zeros(nb)
            self._pass_rate[lane_id] *= decay
        live = set()
        for g in all_tracks:
            if g.lane_id is None or g.lane_id not in self._bin_covered:
                continue
            key = (g.camera_id, g.track_id)
            live.add(key)
            prev = self._track_lane.get(key)
            lane_id = g.lane_id
            nb = len(self._bins_seen[lane_id])
            if prev is not None and prev[0] != lane_id:
                a = net.lanes.get(prev[0])
                # Only *slow* lane changes count as swerving around something:
                # strategic lane changes for the next turn happen at speed, all
                # along the lane, all the time.
                if a is not None and a.edge_id == net.lanes[lane_id].edge_id and \
                        g.speed < cfg.void_swerve_max_speed_frac * a.speed:
                    self._swerves.setdefault(prev[0], []).append((t, prev[1]))
            s0 = prev[1] if prev is not None and prev[0] == lane_id else g.s
            lo, hi = sorted((s0, g.s))
            b_lo = int(np.clip(lo // bin_m, 0, nb - 1))
            b_hi = int(np.clip(hi // bin_m, 0, nb - 1))
            self._bins_seen[lane_id][b_lo:b_hi + 1] = t
            if g.s > s0:
                for b in range(b_lo, b_hi + 1):
                    mid = (b + 0.5) * bin_m
                    if s0 < mid <= g.s:
                        self._bins_passes[lane_id][b].append(t)
                        self._pass_rate[lane_id][b] += 1.0
            self._track_lane[key] = (lane_id, g.s, t)
        for key in [k for k, v in self._track_lane.items() if k not in live and t - v[2] > 10.0]:
            del self._track_lane[key]
        for passes in self._bins_passes.values():
            for pl in passes:
                while pl and pl[0] < t - cfg.void_s:
                    pl.pop(0)
        for lane_id, sw in self._swerves.items():
            self._swerves[lane_id] = [e for e in sw if e[0] >= t - cfg.void_s]

    def _flow_void(self, t: float) -> list[RuleHit]:
        cfg = self.cfg
        net = self.rig.network
        bin_m = cfg.void_bin_m
        # needs a baseline of normal lane use first
        if self._t0 is None or t - self._t0 < max(cfg.void_s, cfg.void_baseline_tau_s / 2):
            return []
        out = []
        for lane_ids in net.edges.values():
            covered = [lid for lid in lane_ids if lid in self._bin_covered]
            if len(covered) < 2:
                continue
            for lid in covered:
                seen = self._bins_seen[lid]
                swerves = self._swerves.get(lid, [])
                if len(swerves) < cfg.void_min_swerves:
                    continue
                for b in np.nonzero(self._bin_covered[lid])[0]:
                    b = int(b)
                    void_for = t - seen[b]
                    if void_for < cfg.void_s:
                        continue
                    mid = (b + 0.5) * bin_m
                    if net.lanes[lid].length - mid < cfg.void_min_from_stop_line_m:
                        continue
                    neigh_now = 0
                    neigh_rate = []
                    for other in covered:
                        if other == lid or b >= len(self._bins_passes[other]):
                            continue
                        neigh_now += len(self._bins_passes[other][b])
                        neigh_rate.append(self._pass_rate[other][b])
                    if neigh_now < cfg.void_min_neighbour_passes or not neigh_rate:
                        continue
                    own = self._pass_rate[lid][b]
                    if own < 1.0 or own < cfg.void_min_share * float(np.mean(neigh_rate)):
                        continue  # a lane drivers normally leave empty
                    n_sw = sum(1 for _, s in swerves if mid - cfg.void_swerve_window_m <= s < mid)
                    if n_sw < cfg.void_min_swerves:
                        continue
                    out.append(RuleHit("flow_void", lid, _ramp(void_for, cfg.void_s), mid,
                                       self.links_for_lane(lid),
                                       {"bin_s_m": [b * bin_m, (b + 1) * bin_m],
                                        "void_s": round(float(void_for), 1),
                                        "measure": round(float(void_for), 1),
                                        "share": round(float(own / max(1e-9, np.mean(neigh_rate))),
                                                       2),
                                        "from_stop_line_m": round(float(
                                            net.lanes[lid].length - mid), 1),
                                        "neighbour_passes": neigh_now, "swerves": n_sw}))
                    break  # one void per lane is enough
        return out

    # ---- main ---------------------------------------------------------------------

    def update(self, t: float, tracks: Iterable[GroundTrack],
               est: LinkStateEstimator) -> dict[tuple[str, str], float]:
        if self._t0 is None:
            self._t0 = t
        all_tracks = list(tracks)
        by_lane = est.lane_tracks
        on = set(self.cfg.enabled)
        hits: list[RuleHit] = []
        for lane_id, lt in by_lane.items():
            if "stuck_on_green" in on:
                hits += self._stuck_on_green(t, lane_id, lt, est)
            if "midblock_stop" in on:
                hits += self._midblock_stop(t, lane_id, lt, est)
        if "wrong_way" in on:
            hits += self._wrong_way(t, all_tracks)
        if "collision_cue" in on:
            hits += self._collision(t, all_tracks)
        self._observe_lanes(t, all_tracks)  # flow statistics are learned regardless
        if "flow_void" in on:
            hits += self._flow_void(t)
        self.hits = hits

        scores: dict[tuple[str, str], float] = {}
        for h in hits:
            for key in h.links:
                scores[key] = max(scores.get(key, 0.0), h.score)
        self._raise(t, hits)
        return scores

    def _raise(self, t: float, hits: list[RuleHit]) -> None:
        cfg = self.cfg
        self.new_candidates = []
        self.resolved = []
        seen_keys = set()
        for h in hits:
            # A hit about one vehicle keeps its identity as the vehicle moves
            # (a wrong-way driver changes position every tick); a hit about a
            # place (a void) is keyed by where it is.
            anchor = h.evidence.get("track") or h.evidence.get("tracks")
            key: tuple[str, str, object] = (
                h.rule, h.lane_id, str(anchor) if anchor is not None else int(h.s // 20.0))
            seen_keys.add(key)
            st = self._state.setdefault(key, _HitState())
            st.last_seen_t = t
            if h.score < cfg.raise_score:
                st.first_over_t = None
                continue
            if st.first_over_t is None:
                st.first_over_t = t
            if st.candidate is not None:
                st.candidate.score = max(st.candidate.score, h.score)
                continue
            if t < st.cooldown_until or t - st.first_over_t < cfg.raise_persist_s:
                continue
            atype, sev = RULE_ANOMALY[h.rule]
            lane = self.rig.network.lanes.get(h.lane_id)
            cand = AnomalyCandidate(
                anomaly_id=str(uuid.uuid4()),
                rule=h.rule,
                anomaly_type=atype,
                severity=sev,
                lane_id=h.lane_id,
                edge_id=lane.edge_id if lane is not None else "",
                position_m=float(h.s),
                links=h.links,
                score=h.score,
                first_t=st.first_over_t,
                raised_t=t,
                evidence=dict(h.evidence),
            )
            st.candidate = cand
            self.active[cand.anomaly_id] = cand
            self.new_candidates.append(cand)
        for key, st in list(self._state.items()):
            if key in seen_keys:
                continue
            if t - st.last_seen_t >= cfg.clear_s:
                if st.candidate is not None:
                    st.candidate.status = "RESOLVED"
                    st.candidate.resolved_t = t
                    self.resolved.append(st.candidate)
                    self.active.pop(st.candidate.anomaly_id, None)
                    st.cooldown_until = t + cfg.cooldown_s
                    st.candidate = None
                st.first_over_t = None
                if st.cooldown_until < t:
                    del self._state[key]


@dataclass
class StaticSignalState:
    """For tests and replays: a fixed map of link states and green onsets."""

    states: dict[tuple[str, str], str] = field(default_factory=dict)
    since: dict[tuple[str, str], float] = field(default_factory=dict)

    def link_state(self, tls_id: str, link: str) -> str:
        return self.states.get((tls_id, link), "")

    def green_since(self, tls_id: str, link: str) -> float | None:
        return self.since.get((tls_id, link))


class TraciSignalState:
    """Live link states from TraCI, with green-onset times tracked here.
    `refresh(t)` once per tick, before the incident engine runs."""

    def __init__(self, tls_ids: Iterable[str]):
        self.tls_ids = list(tls_ids)
        self._state: dict[tuple[str, str], str] = {}
        self._since: dict[tuple[str, str], float] = {}

    def refresh(self, t: float) -> None:
        import traci  # noqa: PLC0415

        for tls in self.tls_ids:
            rygs = traci.trafficlight.getRedYellowGreenState(tls)
            for i, ch in enumerate(rygs):
                key = (tls, f"L{i}")
                prev = self._state.get(key, "")
                if ch in "Gg" and prev not in ("G", "g"):
                    self._since[key] = t
                elif ch not in "Gg":
                    self._since.pop(key, None)
                self._state[key] = ch

    def link_state(self, tls_id: str, link: str) -> str:
        return self._state.get((tls_id, link), "")

    def green_since(self, tls_id: str, link: str) -> float | None:
        return self._since.get((tls_id, link))


class PhaseSignalState:
    """Link states from `SignalChanged` events: `on_phase(t, tls, "P{k}")`
    looks the phase up in the net's own program (`RoadNetwork.
    phase_link_states`) and records green onsets. Between phases the
    controller's yellow and all-red are not announced on the bus, so for those
    few seconds the previous green is still reported -- a known, bounded lag
    that only ever delays a `stuck_on_green` hit, never creates one."""

    def __init__(self, phase_states: dict[str, dict[str, dict[str, str]]]):
        self.phase_states = phase_states
        self._state: dict[tuple[str, str], str] = {}
        self._since: dict[tuple[str, str], float] = {}

    def on_phase(self, t: float, tls_id: str, phase_id: str) -> None:
        links = self.phase_states.get(tls_id, {}).get(phase_id)
        if links is None:
            return
        for link, ch in links.items():
            key = (tls_id, link)
            was_green = self._state.get(key, "") in ("G", "g")
            if ch in "Gg" and not was_green:
                self._since[key] = t
            elif ch not in "Gg":
                self._since.pop(key, None)
            self._state[key] = ch

    def link_state(self, tls_id: str, link: str) -> str:
        return self._state.get((tls_id, link), "")

    def green_since(self, tls_id: str, link: str) -> float | None:
        return self._since.get((tls_id, link))
