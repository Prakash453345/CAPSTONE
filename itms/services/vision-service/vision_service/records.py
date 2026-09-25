"""Records passed between pipeline stages.

Kept deliberately plain (dataclasses of floats and small numpy arrays) so a
stage can be tested by constructing its input by hand, and so the edge/central
split in the design (docs/vision_system_design.md §3) is a serialisation
question, not a refactor.

`truth_id` appears on detections and tracks produced from SimCam. It is the
simulation's vehicle id, carried **only** so evaluation code can score
identity; no pipeline stage reads it, and a real source leaves it `None`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from vision_service.classes import VClass


@dataclass(frozen=True)
class Detection:
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels
    score: float
    vclass: VClass
    truth_id: str | None = None

    @property
    def width(self) -> float:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]

    @property
    def bottom_centre(self) -> tuple[float, float]:
        return ((self.box[0] + self.box[2]) / 2.0, self.box[3])


def boxes_array(dets: list[Detection]) -> np.ndarray:
    if not dets:
        return np.zeros((0, 4))
    return np.asarray([d.box for d in dets], dtype=np.float64)


@dataclass
class ImageTrack:
    """A ByteTrack track as seen by the next stage. `coasting` means it was
    carried forward by its motion model this frame rather than matched to a
    detection (a bus is in the way, or the detector blinked)."""

    track_id: int
    box: np.ndarray
    score: float
    vclass: VClass
    hits: int
    age_frames: int
    coasting: bool
    truth_id: str | None = None


@dataclass
class GroundTrack:
    """One vehicle on the road plane, in the network's metres.

    `stopped` is the hysteresis state, not a raw speed comparison.
    `speed_known` is False until the velocity has been seeded from two clean
    measurements; before that `velocity` is the filter's zero prior, not a
    measurement, and consumers must not read it as "stationary".
    `moved_m` is how far the track has travelled *while moving* (speed above
    1.5 m/s) since it was born -- the difference between a stalled vehicle
    and a roadside object the detector keeps mistaking for one (a vehicle
    that never moved is furniture).
    `displaced_m` is the net distance the track has covered from where it
    was first cleanly measured, however slowly -- a vehicle that crept into
    a queue has arrived even if it never went fast.
    `lane_id`/`s`/`lateral` are empty when the point is on no lane (inside
    the junction box, on a footpath, or a projection error)."""

    camera_id: str
    track_id: int
    t: float
    xy: np.ndarray
    velocity: np.ndarray
    vclass: VClass
    pcu: float
    length_m: float
    resolution_m_per_px: float
    coasting: bool
    at_border: bool = False  # its image box touches the frame edge (entering or leaving view)
    stopped: bool = False
    stopped_since: float | None = None
    born_t: float = 0.0
    moved_m: float = 0.0
    displaced_m: float = 0.0  # net progress from the first clean fix (see above)
    heading_deg: float = float("nan")
    speed_known: bool = True
    lane_id: str | None = None
    s: float = float("nan")
    lateral: float = float("nan")
    lane_agrees: bool = True
    truth_id: str | None = None
    history: list[tuple[float, float, float]] = field(default_factory=list, repr=False)

    @property
    def speed(self) -> float:
        return float(np.hypot(self.velocity[0], self.velocity[1]))
