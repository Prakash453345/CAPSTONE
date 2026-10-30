"""What the digital-twin camera films: a snapshot of every vehicle on the
network, from TraCI or from the `VehiclePositionUpdated` bus stream.

A snapshot is struct-of-arrays -- one numpy array per attribute -- because
every consumer (projection, occlusion, the error model, the evaluators) is
vectorised over vehicles.

SUMO reports a vehicle's position at the **centre of its front bumper**;
`WorldSnapshot.xy` is the **centre of the vehicle**, converted once here so no
downstream stage has to remember the convention.

`interpolate` produces the in-between frames that let the camera pipeline
run at 5 fps while SUMO and the controller keep stepping at 1 Hz. Vehicles
present in both endpoint snapshots move linearly (heading by the shortest
arc); a vehicle that appears only in the later one is shown from its first
real position, and one that vanished is dropped.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from vision_service.classes import ClassTable, VClass, vclass_from_sumo


@dataclass(frozen=True)
class WorldSnapshot:
    t: float
    ids: tuple[str, ...]
    vclass: tuple[VClass, ...]
    xy: np.ndarray        # (N, 2) vehicle centres, net metres
    heading: np.ndarray   # (N,) compass degrees
    length: np.ndarray
    width: np.ndarray
    height: np.ndarray
    speed: np.ndarray
    lane_id: tuple[str, ...]
    lane_pos: np.ndarray  # SUMO lane position of the front bumper, NaN if unknown

    def __len__(self) -> int:
        return len(self.ids)

    @classmethod
    def empty(cls, t: float = 0.0) -> WorldSnapshot:
        z = np.zeros(0)
        return cls(t, (), (), np.zeros((0, 2)), z, z, z, z, z, (), z)

    def index(self) -> dict[str, int]:
        return {vid: i for i, vid in enumerate(self.ids)}

    def subset(self, mask: np.ndarray) -> WorldSnapshot:
        idx = np.nonzero(mask)[0]
        return WorldSnapshot(
            self.t,
            tuple(self.ids[i] for i in idx),
            tuple(self.vclass[i] for i in idx),
            self.xy[idx],
            self.heading[idx],
            self.length[idx],
            self.width[idx],
            self.height[idx],
            self.speed[idx],
            tuple(self.lane_id[i] for i in idx),
            self.lane_pos[idx],
        )


def _front_to_centre(front: np.ndarray, heading_deg: np.ndarray, length: np.ndarray) -> np.ndarray:
    th = np.radians(heading_deg)
    fwd = np.stack([np.sin(th), np.cos(th)], axis=1)
    return front - fwd * (length / 2.0)[:, None]


def snapshot_from_records(
    t: float,
    records: list[dict],
    classes: ClassTable,
    *,
    position_is_front: bool = True,
) -> WorldSnapshot:
    """Build a snapshot from plain dicts with keys `id`, `vclass` (a
    `VClass`), `x`, `y`, `heading`, `speed`, and optionally `length`,
    `width`, `lane_id`, `lane_pos`. Missing dimensions come from `classes`."""
    if not records:
        return WorldSnapshot.empty(t)
    vc = tuple(r["vclass"] for r in records)
    length = np.array([r.get("length") or classes[c].length_m for r, c in zip(records, vc,
                                                                                strict=True)])
    width = np.array([r.get("width") or classes[c].width_m for r, c in zip(records, vc,
                                                                            strict=True)])
    height = np.array([classes[c].height_m for c in vc])
    heading = np.array([float(r["heading"]) for r in records]) % 360.0
    pos = np.array([[float(r["x"]), float(r["y"])] for r in records])
    xy = _front_to_centre(pos, heading, length) if position_is_front else pos
    return WorldSnapshot(
        t=t,
        ids=tuple(str(r["id"]) for r in records),
        vclass=vc,
        xy=xy,
        heading=heading,
        length=length,
        width=width,
        height=height,
        speed=np.array([float(r.get("speed", 0.0)) for r in records]),
        lane_id=tuple(str(r.get("lane_id", "")) for r in records),
        lane_pos=np.array([float(r.get("lane_pos", math.nan)) for r in records]),
    )


def interpolate(a: WorldSnapshot, b: WorldSnapshot, t: float) -> WorldSnapshot:
    """The world at time `t` in `[a.t, b.t]`. See module docstring."""
    if b.t <= a.t:
        return b
    alpha = float(np.clip((t - a.t) / (b.t - a.t), 0.0, 1.0))
    if alpha >= 1.0:
        return b
    ia = a.index()
    xy = b.xy.copy()
    heading = b.heading.copy()
    speed = b.speed.copy()
    for j, vid in enumerate(b.ids):
        i = ia.get(vid)
        if i is None:
            continue
        xy[j] = a.xy[i] + alpha * (b.xy[j] - a.xy[i])
        dh = ((b.heading[j] - a.heading[i] + 180.0) % 360.0) - 180.0
        heading[j] = (a.heading[i] + alpha * dh) % 360.0
        speed[j] = a.speed[i] + alpha * (b.speed[j] - a.speed[i])
    return WorldSnapshot(
        t, b.ids, b.vclass, xy, heading, b.length, b.width, b.height, speed, b.lane_id, b.lane_pos
    )


class TraciWorld:
    """Snapshots from a live TraCI connection, via vehicle subscriptions so a
    step costs one round trip for all vehicles rather than several per
    vehicle. Vehicle dimensions come from each vType, read once."""

    def __init__(self, classes: ClassTable | None = None):
        self.classes = classes or ClassTable.default()
        self._vtype_cache: dict[str, tuple[VClass, float, float]] = {}
        self._subscribed: set[str] = set()
        self._started = False

    def _vtype(self, vtype_id: str) -> tuple[VClass, float, float]:
        got = self._vtype_cache.get(vtype_id)
        if got is None:
            import traci  # noqa: PLC0415 -- optional, simulation-only dependency

            vc = vclass_from_sumo(vtype_id, traci.vehicletype.getVehicleClass(vtype_id))
            got = (vc, traci.vehicletype.getLength(vtype_id), traci.vehicletype.getWidth(vtype_id))
            self._vtype_cache[vtype_id] = got
        return got

    def vtype_dimensions(self) -> dict[VClass, tuple[float, float]]:
        """`{class: (length, width)}` of the vTypes seen so far -- what a
        self-consistent twin passes to `ClassTable.with_dimensions`."""
        return {vc: (ln, w) for vc, ln, w in self._vtype_cache.values()}

    def _subscribe(self, ids) -> None:
        import traci  # noqa: PLC0415
        import traci.constants as tc  # noqa: PLC0415

        for vid in ids:
            if vid in self._subscribed:
                continue
            traci.vehicle.subscribe(
                vid,
                (
                    tc.VAR_POSITION,
                    tc.VAR_ANGLE,
                    tc.VAR_TYPE,
                    tc.VAR_SPEED,
                    tc.VAR_LANE_ID,
                    tc.VAR_LANEPOSITION,
                ),
            )
            self._subscribed.add(vid)

    def snapshot(self) -> WorldSnapshot:
        import traci  # noqa: PLC0415
        import traci.constants as tc  # noqa: PLC0415

        if not self._started:
            self._subscribe(traci.vehicle.getIDList())
            self._started = True
        self._subscribe(traci.simulation.getDepartedIDList())
        for vid in traci.simulation.getArrivedIDList():
            self._subscribed.discard(vid)
        results: Mapping[str, dict] = traci.vehicle.getAllSubscriptionResults()
        t = traci.simulation.getTime()
        records = []
        for vid, r in results.items():
            if tc.VAR_POSITION not in r:
                continue
            vc, length, width = self._vtype(r[tc.VAR_TYPE])
            x, y = r[tc.VAR_POSITION]
            records.append(
                {
                    "id": vid,
                    "vclass": vc,
                    "x": x,
                    "y": y,
                    "heading": r[tc.VAR_ANGLE],
                    "speed": r[tc.VAR_SPEED],
                    "length": length,
                    "width": width,
                    "lane_id": r[tc.VAR_LANE_ID],
                    "lane_pos": r[tc.VAR_LANEPOSITION],
                }
            )
        return snapshot_from_records(t, records, self.classes)
