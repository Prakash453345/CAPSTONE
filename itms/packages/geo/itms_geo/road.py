"""The road network as geometry: lane centrelines, widths and directions read
straight from a SUMO `.net.xml`, plus the queries a camera pipeline needs --
which lane is this ground point on, how far along it, how far from its stop
line, which way does it run, and how much of it can a given camera see.

Read with the standard library's XML parser, not `sumolib`, so the vision
service has no SUMO dependency at runtime; a real deployment with no
simulator still reads the same net file for its map.

**Lane frame.** `s` is distance along a lane from its upstream start, in
metres; `s == length` is the downstream end, which for an approach lane is
its stop line. `lateral` is signed distance from the centreline, positive to
the *left* of the direction of travel.

**Links.** `RoadNetwork.link_lane_maps()` reproduces
`scenarios/networks/vijayawada/link_lanes.py` exactly (a test pins that):
`{tls_id: {"L{linkIndex}": lane_id}}` for the approach lane and the
receiving lane of every signal-controlled connection. Keeping both in one
place is what lets a camera estimate be keyed identically to
`QueueStateSampler`'s ground truth.

numpy only (pyproj optional, for lat/lon).
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from itms_domain.signal_program import green_phase_states

_DEFAULT_LANE_WIDTH_M = 3.2  # SUMO's default when a lane has no width attribute
BOX_PATH_LEAD_M = 10.0  # a box path starts this far before the stop line


def _parse_shape(s: str) -> np.ndarray:
    pts = [tuple(float(v) for v in p.split(",")[:2]) for p in s.split()]
    return np.asarray(pts, dtype=np.float64)


def heading_of(vec: np.ndarray) -> np.ndarray:
    """Compass bearing (deg, 0 = north, clockwise) of `(N, 2)` vectors."""
    v = np.asarray(vec, dtype=np.float64).reshape(-1, 2)
    return np.degrees(np.arctan2(v[:, 0], v[:, 1])) % 360.0


def heading_diff(a, b) -> np.ndarray:
    """Smallest absolute angle between two compass bearings, in [0, 180]."""
    d = (np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)) % 360.0
    return np.minimum(d, 360.0 - d)


@dataclass(frozen=True)
class Lane:
    lane_id: str
    edge_id: str
    index: int
    length: float
    width: float
    speed: float
    shape: np.ndarray = field(repr=False, compare=False)

    # derived segment arrays, computed once
    _starts: np.ndarray = field(init=False, repr=False, compare=False)
    _vecs: np.ndarray = field(init=False, repr=False, compare=False)
    _seg_len: np.ndarray = field(init=False, repr=False, compare=False)
    _cum: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        shape = np.asarray(self.shape, dtype=np.float64)
        if len(shape) < 2:
            raise ValueError(f"lane {self.lane_id} has fewer than 2 shape points")
        starts = shape[:-1]
        vecs = shape[1:] - shape[:-1]
        seg_len = np.sqrt((vecs**2).sum(axis=1))
        keep = seg_len > 1e-9
        starts, vecs, seg_len = starts[keep], vecs[keep], seg_len[keep]
        cum = np.concatenate([[0.0], np.cumsum(seg_len)[:-1]])
        object.__setattr__(self, "_starts", starts)
        object.__setattr__(self, "_vecs", vecs)
        object.__setattr__(self, "_seg_len", seg_len)
        object.__setattr__(self, "_cum", cum)

    @property
    def geometric_length(self) -> float:
        return float(self._seg_len.sum())

    def _scale(self) -> float:
        """SUMO's `length` attribute can differ slightly from the polyline's
        own length (it is measured before junction cut-back). Positions are
        reported in SUMO's `length` units so they compare with
        `traci.vehicle.getLanePosition`."""
        g = self.geometric_length
        return self.length / g if g > 1e-9 else 1.0

    def project(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """`(N, 2)` points -> `(s, lateral, segment_heading_deg)` against the
        nearest point of this lane's centreline."""
        p = np.asarray(points, dtype=np.float64).reshape(-1, 2)
        rel = p[:, None, :] - self._starts[None, :, :]  # (N, M, 2)
        t = (rel * self._vecs[None]).sum(axis=2) / (self._seg_len**2)[None]
        t = np.clip(t, 0.0, 1.0)
        closest = self._starts[None] + t[..., None] * self._vecs[None]
        d2 = ((p[:, None, :] - closest) ** 2).sum(axis=2)
        k = np.argmin(d2, axis=1)
        idx = np.arange(len(p))
        seg_vec = self._vecs[k]
        rel_k = rel[idx, k]
        cross = seg_vec[:, 0] * rel_k[:, 1] - seg_vec[:, 1] * rel_k[:, 0]
        lateral = np.sign(cross) * np.sqrt(d2[idx, k])
        s = (self._cum[k] + t[idx, k] * self._seg_len[k]) * self._scale()
        return s, lateral, heading_of(seg_vec)

    def point_at(self, s: np.ndarray | float, lateral: np.ndarray | float = 0.0) -> np.ndarray:
        """Inverse of `project`: `(s, lateral)` -> ground point(s)."""
        s_arr = np.atleast_1d(np.asarray(s, dtype=np.float64)) / self._scale()
        lat = np.broadcast_to(np.asarray(lateral, dtype=np.float64), s_arr.shape)
        k = np.clip(np.searchsorted(self._cum, s_arr, side="right") - 1, 0, len(self._cum) - 1)
        t = (s_arr - self._cum[k]) / self._seg_len[k]
        base = self._starts[k] + t[:, None] * self._vecs[k]
        u = self._vecs[k] / self._seg_len[k][:, None]
        left = np.stack([-u[:, 1], u[:, 0]], axis=1)
        return base + lat[:, None] * left

    def heading_at(self, s: np.ndarray | float) -> np.ndarray:
        s_arr = np.atleast_1d(np.asarray(s, dtype=np.float64)) / self._scale()
        k = np.clip(np.searchsorted(self._cum, s_arr, side="right") - 1, 0, len(self._cum) - 1)
        return heading_of(self._vecs[k])

    def sample(self, step_m: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
        """Centreline points every `step_m` (in `length` units) and their `s`."""
        n = max(2, int(math.ceil(self.length / step_m)) + 1)
        s = np.linspace(0.0, self.length, n)
        return self.point_at(s), s

    def polygon(self) -> np.ndarray:
        """Closed outline of the lane surface (left edge forward, right edge
        back) -- for drawing and for off-road tests."""
        pts, s = self.sample(max(1.0, self.length / 60.0))
        left = self.point_at(s, self.width / 2.0)
        right = self.point_at(s, -self.width / 2.0)
        return np.vstack([left, right[::-1]])


@dataclass(frozen=True)
class BoxPath:
    """The path one signal link takes through its junction: a `Lane` whose
    centreline is the last `BOX_PATH_LEAD_M` of the approach lane (all of
    it, if shorter) followed by the link's junction-internal lanes, in
    metres along the drawn line (`path.length` is its geometric length).
    `stop_s` is the stop line's `s` on it."""

    path: Lane
    stop_s: float

    @property
    def length(self) -> float:
        return self.path.length


@dataclass(frozen=True)
class Connection:
    from_lane: str
    to_lane: str
    tls_id: str | None
    link_index: int | None
    direction: str


@dataclass
class RoadNetwork:
    lanes: dict[str, Lane]
    edges: dict[str, tuple[str, ...]]            # edge_id -> lane ids (by index)
    edge_nodes: dict[str, tuple[str, str]]       # edge_id -> (from node, to node)
    junctions: dict[str, tuple[float, float, str]]  # id -> (x, y, type)
    connections: list[Connection]
    net_offset: tuple[float, float] = (0.0, 0.0)
    proj_parameter: str = ""
    # tls -> the state strings of its green phases, in program order: index k
    # is phase "P{k}" in extract_tier0_config.py's numbering
    # (`itms_domain.signal_program`), which is what SignalChanged.phase_id carries.
    green_phases: dict[str, list[str]] = field(default_factory=dict)
    # tls -> {"L{i}": the path link i takes through the junction box}.
    # Empty for a network built without internal lanes.
    box_paths: dict[str, dict[str, BoxPath]] = field(default_factory=dict)

    # ---- loading ----------------------------------------------------

    @classmethod
    def from_sumo_net(cls, path: str | Path) -> RoadNetwork:
        root = ET.parse(path).getroot()
        lanes: dict[str, Lane] = {}
        edges: dict[str, tuple[str, ...]] = {}
        edge_nodes: dict[str, tuple[str, str]] = {}
        internal_shape: dict[str, np.ndarray] = {}
        for e in root.findall("edge"):
            if e.get("function") == "internal":
                for ln in e.findall("lane"):
                    if ln.get("shape"):
                        internal_shape[ln.get("id", "")] = _parse_shape(ln.get("shape", ""))
                continue
            eid = e.get("id", "")
            ids = []
            for ln in e.findall("lane"):
                lane = Lane(
                    lane_id=ln.get("id", ""),
                    edge_id=eid,
                    index=int(ln.get("index", "0")),
                    length=float(ln.get("length", "0")),
                    width=float(ln.get("width", _DEFAULT_LANE_WIDTH_M)),
                    speed=float(ln.get("speed", "13.89")),
                    shape=_parse_shape(ln.get("shape", "")),
                )
                lanes[lane.lane_id] = lane
                ids.append((lane.index, lane.lane_id))
            edges[eid] = tuple(lid for _, lid in sorted(ids))
            edge_nodes[eid] = (e.get("from", ""), e.get("to", ""))
        junctions = {
            j.get("id", ""): (float(j.get("x", "0")), float(j.get("y", "0")), j.get("type", ""))
            for j in root.findall("junction")
            if j.get("type") != "internal"
        }
        connections = []
        via_first: dict[tuple[str, str], tuple[str, str]] = {}  # (tls, link) -> (lane, via)
        via_next: dict[str, str] = {}                           # internal lane -> next one
        for c in root.findall("connection"):
            fe, te = c.get("from"), c.get("to")
            fl, tl = c.get("fromLane"), c.get("toLane")
            if fe is None or te is None or fl is None or tl is None:
                continue
            if fe.startswith(":") or te.startswith(":"):
                # internal-lane chains: a link with a waiting position inside
                # the box continues on a second internal lane
                if fe.startswith(":") and c.get("via"):
                    via_next[f"{fe}_{fl}"] = c.get("via", "")
                continue
            li = c.get("linkIndex")
            if c.get("tl") and li is not None and c.get("via"):
                via_first[(c.get("tl", ""), f"L{li}")] = (f"{fe}_{fl}", c.get("via", ""))
            connections.append(
                Connection(
                    from_lane=f"{fe}_{fl}",
                    to_lane=f"{te}_{tl}",
                    tls_id=c.get("tl"),
                    link_index=int(li) if li is not None else None,
                    direction=c.get("dir", ""),
                )
            )
        green_phases: dict[str, list[str]] = {}
        for logic in root.findall("tlLogic"):
            # the phases exactly as extract_tier0_config numbers them (change
            # intervals, parts of a stage and repeats skipped); the last
            # program for a light is the one SUMO runs, as there
            states = [ph.get("state", "") for ph in logic.findall("phase")]
            green_phases[logic.get("id", "")] = [st for _, st in green_phase_states(states)]
        loc = root.find("location")
        offset = (0.0, 0.0)
        proj = ""
        if loc is not None:
            ox, oy = (float(v) for v in loc.get("netOffset", "0,0").split(","))
            offset = (ox, oy)
            proj = loc.get("projParameter", "")
        return cls(lanes, edges, edge_nodes, junctions, connections, offset, proj, green_phases,
                   _box_paths(lanes, internal_shape, via_first, via_next))

    # ---- links --------------------------------------------------------

    def link_lane_maps(
        self,
    ) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
        """`(approach, receiving)`, each `{tls_id: {"L{i}": lane_id}}`."""
        approach: dict[str, dict[str, str]] = {}
        receiving: dict[str, dict[str, str]] = {}
        for c in self.connections:
            if not c.tls_id or c.link_index is None:
                continue
            key = f"L{c.link_index}"
            approach.setdefault(c.tls_id, {})[key] = c.from_lane
            receiving.setdefault(c.tls_id, {})[key] = c.to_lane
        return approach, receiving

    def phase_link_states(self, tls_id: str) -> dict[str, dict[str, str]]:
        """`{"P{k}": {"L{i}": state char}}` for one traffic light."""
        return {f"P{k}": {f"L{i}": c for i, c in enumerate(st)}
                for k, st in enumerate(self.green_phases.get(tls_id, []))}

    def tls_ids(self) -> list[str]:
        approach, _ = self.link_lane_maps()
        return sorted(approach)

    def approach_edges(self, tls_id: str) -> list[str]:
        approach, _ = self.link_lane_maps()
        seen: dict[str, None] = {}
        for lane_id in approach.get(tls_id, {}).values():
            seen.setdefault(self.lanes[lane_id].edge_id, None)
        return list(seen)

    # ---- coordinates --------------------------------------------------

    @property
    def georeferenced(self) -> bool:
        """False for a network with no projection (`projParameter="!"`, e.g.
        one made by netgenerate). SUMO then reports "geo" coordinates as the
        plain network coordinates less the offset, and so does this class."""
        return self.proj_parameter not in ("", "!", None)

    def xy_to_lonlat(self, xy: np.ndarray) -> np.ndarray:
        """Net XY -> (lon, lat) using the net's own projection. Needs pyproj."""
        pts = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        if not self.georeferenced:
            return pts - np.asarray(self.net_offset, dtype=np.float64)
        from pyproj import Proj  # noqa: PLC0415 -- optional dependency

        p = Proj(self.proj_parameter)
        lon, lat = p(pts[:, 0] - self.net_offset[0], pts[:, 1] - self.net_offset[1], inverse=True)
        return np.stack([np.asarray(lon), np.asarray(lat)], axis=1)

    def lonlat_to_xy(self, lonlat: np.ndarray) -> np.ndarray:
        pts = np.asarray(lonlat, dtype=np.float64).reshape(-1, 2)
        if not self.georeferenced:
            return pts + np.asarray(self.net_offset, dtype=np.float64)
        from pyproj import Proj  # noqa: PLC0415

        p = Proj(self.proj_parameter)
        x, y = p(pts[:, 0], pts[:, 1])
        return np.stack(
            [np.asarray(x) + self.net_offset[0], np.asarray(y) + self.net_offset[1]], axis=1
        )


def _box_paths(
    lanes: Mapping[str, Lane],
    internal_shape: Mapping[str, np.ndarray],
    via_first: Mapping[tuple[str, str], tuple[str, str]],
    via_next: Mapping[str, str],
) -> dict[str, dict[str, BoxPath]]:
    out: dict[str, dict[str, BoxPath]] = {}
    for (tls, link), (from_lane, via) in via_first.items():
        lane = lanes.get(from_lane)
        if lane is None:
            continue
        lead = min(BOX_PATH_LEAD_M, lane.length)
        pts = [lane.point_at(lane.length - lead)[0], lane.point_at(lane.length)[0]]
        seen: set[str] = set()
        while via and via not in seen and via in internal_shape:
            seen.add(via)
            pts.extend(internal_shape[via])
            via = via_next.get(via, "")
        shape = np.asarray(pts, dtype=np.float64)
        keep = np.concatenate([[True], np.sqrt((np.diff(shape, axis=0) ** 2).sum(axis=1)) > 1e-6])
        shape = shape[keep]
        if len(shape) < 3:
            continue
        length = float(np.sqrt((np.diff(shape, axis=0) ** 2).sum(axis=1)).sum())
        path = Lane(lane_id=f"{tls}:{link}", edge_id=lane.edge_id, index=lane.index,
                    length=length, width=lane.width, speed=lane.speed, shape=shape)
        # where the approach lane ends on the drawn line (SUMO's `length` of
        # a lane can differ from its drawn length by up to a metre)
        stop_s = float(path.project(lane.point_at(lane.length))[0][0])
        out.setdefault(tls, {})[link] = BoxPath(path, stop_s)
    return out


@dataclass(frozen=True)
class LaneMatch:
    """Per-point result of `LaneLocator.locate`. `lane` is an index into the
    locator's lane list (-1 when the point is on no lane). `agrees` is
    whether the supplied heading agrees with the lane direction (True when
    no heading was supplied)."""

    lane: np.ndarray
    s: np.ndarray
    lateral: np.ndarray
    lane_heading: np.ndarray
    agrees: np.ndarray


class LaneLocator:
    """Nearest-lane queries over a fixed subset of lanes (typically the lanes
    one camera can see), vectorised over points.

    A point is on a lane when it is within `width/2 + tolerance_m` of the
    centreline and within the lane's length (plus a small overhang so a
    vehicle nosing over its stop line still counts). When a heading is given,
    lanes running the *opposite* way are only chosen if no same-direction lane
    is within reach -- that is the case the wrong-way rule is looking for."""

    def __init__(
        self,
        lanes: Sequence[Lane],
        *,
        tolerance_m: float = 0.6,
        overhang_m: float = 3.0,
        max_heading_diff_deg: float = 60.0,
    ):
        self.lanes = list(lanes)
        self.lane_ids = [ln.lane_id for ln in self.lanes]
        self._index = {lid: i for i, lid in enumerate(self.lane_ids)}
        self.tolerance_m = tolerance_m
        self.overhang_m = overhang_m
        self.max_heading_diff_deg = max_heading_diff_deg

    def index_of(self, lane_id: str) -> int:
        return self._index[lane_id]

    def locate(self, points: np.ndarray, headings: np.ndarray | None = None) -> LaneMatch:
        p = np.asarray(points, dtype=np.float64).reshape(-1, 2)
        n, m = len(p), len(self.lanes)
        if m == 0 or n == 0:
            empty = np.full(n, np.nan)
            return LaneMatch(np.full(n, -1), empty, empty, empty, np.ones(n, dtype=bool))
        s_all = np.empty((n, m))
        lat_all = np.empty((n, m))
        hd_all = np.empty((n, m))
        for j, lane in enumerate(self.lanes):
            s_all[:, j], lat_all[:, j], hd_all[:, j] = lane.project(p)
        widths = np.array([ln.width for ln in self.lanes])
        lengths = np.array([ln.length for ln in self.lanes])
        on = (np.abs(lat_all) <= widths[None] / 2.0 + self.tolerance_m) & (
            s_all >= -self.overhang_m
        ) & (s_all <= lengths[None] + self.overhang_m)
        cost = np.where(on, np.abs(lat_all), np.inf)
        if headings is not None:
            hdg = np.asarray(headings, dtype=np.float64).reshape(-1)
            valid_h = np.isfinite(hdg)
            agrees_all = np.ones((n, m), dtype=bool)
            agrees_all[valid_h] = (
                heading_diff(hdg[valid_h, None], hd_all[valid_h]) <= self.max_heading_diff_deg
            )
            cost = cost + np.where(agrees_all, 0.0, 1e3)  # prefer same-direction lanes
        else:
            agrees_all = np.ones((n, m), dtype=bool)
        best = np.argmin(cost, axis=1)
        idx = np.arange(n)
        found = np.isfinite(cost[idx, best])
        lane = np.where(found, best, -1)
        return LaneMatch(
            lane=lane,
            s=np.where(found, s_all[idx, best], np.nan),
            lateral=np.where(found, lat_all[idx, best], np.nan),
            lane_heading=np.where(found, hd_all[idx, best], np.nan),
            agrees=np.where(found, agrees_all[idx, best], True),
        )


def lanes_near(
    network: RoadNetwork, centre_xy: Iterable[float], radius_m: float
) -> list[Lane]:
    """Lanes with any centreline vertex within `radius_m` of a point -- a
    cheap prefilter before the exact camera-coverage computation."""
    c = np.asarray(list(centre_xy), dtype=np.float64)
    out = []
    for lane in network.lanes.values():
        pts, _ = lane.sample(10.0)
        if (np.sqrt(((pts - c) ** 2).sum(axis=1)) <= radius_m).any():
            out.append(lane)
    return out


def invert_link_map(link_map: Mapping[str, Mapping[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """`{lane_id: [(tls_id, link_key), ...]}` from a `{tls: {L: lane}}` map."""
    out: dict[str, list[tuple[str, str]]] = {}
    for tls, links in link_map.items():
        for key, lane_id in links.items():
            out.setdefault(lane_id, []).append((tls, key))
    return out
