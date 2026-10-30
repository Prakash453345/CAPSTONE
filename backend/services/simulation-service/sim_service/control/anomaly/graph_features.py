"""The static road graph the anomaly detector runs on, and the per-tick
per-link feature vector that rides on its nodes -- plan pillar 4.1
("topology-aware", not a flat per-sensor threshold) and 4.3 (the signal-phase
state is a feature, so a red-light queue and a green-light jam are *different*
inputs, not the same number).

`AnomalyGraph.from_network` turns the corridor's own `.net.xml` into a graph:

    nodes   one per signal-controlled link (`L{index}` at a `tls_id`) --
            exactly `link_lanes.link_to_lane_map`'s keys, 73 of them for the
            Vijayawada corridor
    edges   directed:
              "downstream"  A -> B when the lane A discharges into is B's own
                            approach lane (`link_to_receiving_lane_map`)
              "intra"       A <-> B for links at the same junction (they share
                            a controller and compete for the same green time)
              "self"        A -> A, so a node keeps its own signal under
                            message passing

`LinkFeatureSampler` produces the `[N, F]` matrix for one tick, node order ==
`AnomalyGraph.node_ids`, every feature already on a roughly O(1) scale so the
model sees comparable magnitudes before any learned normalization. It reuses
`QueueStateSampler` for the PCU/occupancy terms rather than re-deriving them.

Both are numpy/torch-free on purpose: the sampler runs inside the SUMO tick
loop, and the detector (which does pull in torch) converts the plain lists to
tensors on its side. `FeatureNormalizer` is the pure per-feature standardizer
fitted on normal-traffic frames and saved beside the model.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import traci

from sim_service.signal_controller.queue_state import QueueStateSampler

# Order is the contract between training and inference -- never reorder, only
# append (and bump the detector version when you do).
FEATURE_NAMES: tuple[str, ...] = (
    "queue_pcu",            # PCU-weighted stopped queue on the approach lane
    "receiving_occupancy",  # downstream lane occupancy [0,1] -- spillback signal
    "receiving_queue_pcu",  # PCU-weighted stopped queue on the downstream lane
    "approaching_pcu",      # PCU-weighted moving traffic inside the decision horizon
    "halting_frac",         # halted vehicles / lane vehicle-capacity
    "mean_speed_frac",      # lane mean speed / lane max speed (1 = free flow)
    "is_green",             # 1.0 if this link's movement is green this tick
    "phase_age_frac",       # elapsed green / max green for the current phase
    "sin_tod",              # demand-profile phase, sin component
    "cos_tod",              # demand-profile phase, cos component
)
N_FEATURES = len(FEATURE_NAMES)

# Rough metres of road one queued vehicle occupies (veh length + gap) -- the
# same 7 m `spillback.py`/the queue literature use to turn a halted count into
# a fraction of lane capacity.
_METRES_PER_VEHICLE = 7.0

# Nominal period, in seconds, of the demand profile the sinusoids wrap. The
# corridor's demand files are ~1 h shaped; a real deployment would pass the
# true day length. Tier-1 (a knob), not a safety constant.
_DEMAND_PERIOD_S = 3600.0


@dataclass(frozen=True)
class AnomalyGraph:
    """Static topology. Built once per network and reused for every run --
    node identity and order are stable, which is what lets a trained model and
    a saved normalizer line up with a live sampler."""

    node_ids: tuple[str, ...]                 # "f{tls}::{L}" canonical
    tls_of: tuple[str, ...]                   # per-node junction id
    link_of: tuple[str, ...]                  # per-node "L{index}"
    approach_lane_of: tuple[str, ...]         # per-node SUMO lane id
    receiving_lane_of: tuple[str | None, ...]
    edge_index: tuple[tuple[int, int], ...]   # directed (src, dst)
    edge_type: tuple[str, ...]                # "downstream" | "intra" | "self"

    @property
    def num_nodes(self) -> int:
        return len(self.node_ids)

    @property
    def num_edges(self) -> int:
        return len(self.edge_index)

    def index_of(self, tls_id: str, link_id: str) -> int:
        return self.node_ids.index(f"{tls_id}::{link_id}")

    def adjacency_lists(self) -> list[list[int]]:
        """`adj[dst]` = sorted list of source node indices with an edge into
        `dst` (self included). What an aggregation step iterates."""
        adj: list[list[int]] = [[] for _ in range(self.num_nodes)]
        for src, dst in self.edge_index:
            adj[dst].append(src)
        return [sorted(set(a)) for a in adj]

    @classmethod
    def from_network(
        cls,
        net_path: str | Path,
        *,
        intra_junction_edges: bool = True,
        self_loops: bool = True,
    ) -> AnomalyGraph:
        approach = _link_to_lane_map(net_path, receiving=False)
        receiving = _link_to_lane_map(net_path, receiving=True)

        # Stable node order: junctions sorted, links numerically within each.
        node_keys: list[tuple[str, str]] = []
        for tls_id in sorted(approach):
            for link_id in sorted(approach[tls_id], key=_link_sort_key):
                node_keys.append((tls_id, link_id))

        node_ids = tuple(f"{t}::{link}" for t, link in node_keys)
        tls_of = tuple(t for t, _ in node_keys)
        link_of = tuple(link for _, link in node_keys)
        approach_lane_of = tuple(approach[t][link] for t, link in node_keys)
        receiving_lane_of = tuple(receiving.get(t, {}).get(link) for t, link in node_keys)

        # Which node feeds a given approach lane -- to resolve downstream edges.
        feeders_of_lane: dict[str, list[int]] = {}
        for i, lane in enumerate(approach_lane_of):
            feeders_of_lane.setdefault(lane, []).append(i)

        edges: list[tuple[int, int]] = []
        etypes: list[str] = []

        for src, recv_lane in enumerate(receiving_lane_of):
            if recv_lane is None:
                continue
            for dst in feeders_of_lane.get(recv_lane, []):
                if dst == src:
                    continue
                edges.append((src, dst))
                etypes.append("downstream")

        if intra_junction_edges:
            by_tls: dict[str, list[int]] = {}
            for i, t in enumerate(tls_of):
                by_tls.setdefault(t, []).append(i)
            for members in by_tls.values():
                for a in members:
                    for b in members:
                        if a != b:
                            edges.append((a, b))
                            etypes.append("intra")

        if self_loops:
            for i in range(len(node_ids)):
                edges.append((i, i))
                etypes.append("self")

        return cls(
            node_ids=node_ids,
            tls_of=tls_of,
            link_of=link_of,
            approach_lane_of=approach_lane_of,
            receiving_lane_of=receiving_lane_of,
            edge_index=tuple(edges),
            edge_type=tuple(etypes),
        )


class LinkFeatureSampler:
    """One tick -> one `[num_nodes][N_FEATURES]` list of lists, node order ==
    `graph.node_ids`. Construct once per run.

    `configs` is `{tls_id: Tier0Config}` (for max-green, and the phase ->
    movement membership `is_green` needs). `pcu_by_vtype` is
    `queue_state.load_vtype_pcu(route_path)`. `lane_cache`, if given, is shared
    with the other per-junction samplers so each lane is read once per tick.
    """

    def __init__(
        self,
        graph: AnomalyGraph,
        configs: Mapping[str, object],
        pcu_by_vtype: Mapping[str, float],
        *,
        lane_cache=None,
        demand_period_s: float = _DEMAND_PERIOD_S,
    ):
        self._graph = graph
        self._configs = configs
        self._demand_period_s = demand_period_s

        # A QueueStateSampler per junction, over just that junction's links.
        self._queue_samplers: dict[str, QueueStateSampler] = {}
        appr_by_tls: dict[str, dict[str, str]] = {}
        recv_by_tls: dict[str, dict[str, str]] = {}
        for i in range(graph.num_nodes):
            tls_id = graph.tls_of[i]
            link_id = graph.link_of[i]
            appr_by_tls.setdefault(tls_id, {})[link_id] = graph.approach_lane_of[i]
            recv = graph.receiving_lane_of[i]
            if recv is not None:
                recv_by_tls.setdefault(tls_id, {})[link_id] = recv
        for tls_id, appr in appr_by_tls.items():
            self._queue_samplers[tls_id] = QueueStateSampler(
                appr, recv_by_tls.get(tls_id, {}), pcu_by_vtype, lane_cache=lane_cache
            )

        self._lane_length_m: dict[str, float] = {}
        self._lane_max_speed: dict[str, float] = {}

    def _lane_length(self, lane_id: str) -> float:
        v = self._lane_length_m.get(lane_id)
        if v is None:
            v = traci.lane.getLength(lane_id)
            self._lane_length_m[lane_id] = v
        return v

    def _lane_max_speed_of(self, lane_id: str) -> float:
        v = self._lane_max_speed.get(lane_id)
        if v is None:
            v = traci.lane.getMaxSpeed(lane_id)
            self._lane_max_speed[lane_id] = v
        return v

    def sample(
        self,
        sim_time_s: float,
        phase_by_tls: Mapping[str, tuple[str, float]],
    ) -> list[list[float]]:
        """`phase_by_tls[tls]` is `(current_phase_id, current_phase_elapsed_s)`
        -- straight off the runner's `js.ctx`. A junction missing from it is
        treated as all-red (`is_green` 0, `phase_age_frac` 0) rather than an
        error, so a mid-transition junction the runner skipped is still a
        valid, if uninformative, row."""
        g = self._graph
        qs_cache = {t: s.sample_extended() for t, s in self._queue_samplers.items()}

        tod = 2.0 * math.pi * (sim_time_s % self._demand_period_s) / self._demand_period_s
        sin_tod, cos_tod = math.sin(tod), math.cos(tod)

        rows: list[list[float]] = []
        for i in range(g.num_nodes):
            tls_id = g.tls_of[i]
            link_id = g.link_of[i]
            appr_lane = g.approach_lane_of[i]
            qsample = qs_cache[tls_id]

            queue_pcu = qsample.queue_pcu.get(link_id, 0.0)
            recv_occ = qsample.receiving_occupancy.get(link_id, 0.0)
            recv_q = qsample.receiving_queue_pcu.get(link_id, 0.0)
            appr_pcu = qsample.approaching_pcu.get(link_id, 0.0)

            capacity_veh = max(1.0, self._lane_length(appr_lane) / _METRES_PER_VEHICLE)
            halting = traci.lane.getLastStepHaltingNumber(appr_lane)
            halting_frac = halting / capacity_veh

            max_speed = max(1e-6, self._lane_max_speed_of(appr_lane))
            mean_speed = traci.lane.getLastStepMeanSpeed(appr_lane)
            # SUMO returns the lane max speed for an empty lane -> frac 1.0,
            # the right reading (nothing is being held up).
            mean_speed_frac = min(1.0, max(0.0, mean_speed / max_speed))

            phase_id, elapsed_s = phase_by_tls.get(tls_id, ("", 0.0))
            cfg = self._configs.get(tls_id)
            is_green = 0.0
            phase_age_frac = 0.0
            if cfg is not None and phase_id:
                phase = getattr(cfg, "phases", {}).get(phase_id)
                if phase is not None and link_id in phase.green_movements:
                    is_green = 1.0
                max_green = getattr(cfg, "max_green_s", {}).get(phase_id, 60.0) or 60.0
                phase_age_frac = min(1.0, max(0.0, elapsed_s / max_green))

            rows.append(
                [
                    queue_pcu,
                    recv_occ,
                    recv_q,
                    appr_pcu,
                    halting_frac,
                    mean_speed_frac,
                    is_green,
                    phase_age_frac,
                    sin_tod,
                    cos_tod,
                ]
            )
        return rows


@dataclass
class FeatureNormalizer:
    """Per-feature standardizer. Fitted once on concatenated normal-traffic
    frames and saved as JSON beside the model, so inference sees the same
    scaling training did. `is_green` and the sinusoids are left untouched
    (already bounded and meaningful raw) via `passthrough`."""

    mean: list[float]
    std: list[float]
    passthrough: tuple[str, ...] = ("is_green", "sin_tod", "cos_tod")

    @classmethod
    def fit(cls, frames: Sequence[Sequence[Sequence[float]]]) -> FeatureNormalizer:
        """`frames` is a sequence of `[N][F]` matrices. Stats are pooled over
        every node and tick -- the model scores per-node deviation from that
        node's own history separately (that is `graph_score`), so the input
        normalizer only needs a stable global scale per feature."""
        n = 0
        sums = [0.0] * N_FEATURES
        sqsums = [0.0] * N_FEATURES
        for frame in frames:
            for row in frame:
                n += 1
                for f in range(N_FEATURES):
                    sums[f] += row[f]
                    sqsums[f] += row[f] * row[f]
        if n == 0:
            raise ValueError("cannot fit a normalizer on zero frames")
        mean = [s / n for s in sums]
        std = [
            math.sqrt(max(1e-12, sqsums[f] / n - mean[f] * mean[f]))
            for f in range(N_FEATURES)
        ]
        return cls(mean=mean, std=std)

    def transform_row(self, row: Sequence[float]) -> list[float]:
        out = []
        for f, name in enumerate(FEATURE_NAMES):
            if name in self.passthrough:
                out.append(row[f])
            else:
                out.append((row[f] - self.mean[f]) / self.std[f])
        return out

    def transform(self, frame: Sequence[Sequence[float]]) -> list[list[float]]:
        return [self.transform_row(r) for r in frame]

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(
                {
                    "feature_names": list(FEATURE_NAMES),
                    "mean": self.mean,
                    "std": self.std,
                    "passthrough": list(self.passthrough),
                },
                indent=2,
            )
        )

    @classmethod
    def load(cls, path: str | Path) -> FeatureNormalizer:
        payload = json.loads(Path(path).read_text())
        if payload.get("feature_names") != list(FEATURE_NAMES):
            raise ValueError(
                "normalizer was fitted against a different FEATURE_NAMES -- retrain"
            )
        return cls(
            mean=payload["mean"],
            std=payload["std"],
            passthrough=tuple(payload["passthrough"]),
        )


# --- network parsing (kept local so this module doesn't depend on the
#     scenarios/ import path the gate scripts add to sys.path) ---------------


def _link_sort_key(link_id: str) -> tuple[int, str]:
    """`L7` before `L10` -- numeric where possible."""
    if link_id.startswith("L") and link_id[1:].isdigit():
        return (int(link_id[1:]), "")
    return (10**9, link_id)


def _link_to_lane_map(net_path: str | Path, *, receiving: bool) -> dict[str, dict[str, str]]:
    edge_attr, lane_attr = ("to", "toLane") if receiving else ("from", "fromLane")
    root = ET.parse(net_path).getroot()
    mapping: dict[str, dict[str, str]] = {}
    for conn in root.findall("connection"):
        tls_id = conn.get("tl")
        link_index = conn.get("linkIndex")
        edge = conn.get(edge_attr)
        lane = conn.get(lane_attr)
        if not tls_id or link_index is None or not edge or lane is None:
            continue
        mapping.setdefault(tls_id, {})[f"L{link_index}"] = f"{edge}_{lane}"
    return mapping
