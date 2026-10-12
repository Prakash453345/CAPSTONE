"""The ITMS vehicle taxonomy, and how every source's labels map into it.

Seven classes, chosen for Indian mixed traffic rather than inherited from a
detector's training set. PCU values are the IRC SP:41 priors
`scenarios/demand/vijayawada/assign_vtypes.py` already uses for the four
simulated classes (motorcycle 0.3, car 1.0, auto-rickshaw 0.6, bus 3.0) --
the same numbers, so a camera `queue_pcu` and the SUMO one measure the same
thing. Truck and bicycle are not in the simulation's vType mix; their PCUs
(3.0, 0.2) are provisional priors of the same kind and are marked so.

Dimensions are real-world typical sizes, used for two things: turning a
bounding box's ground contact point into a vehicle centre, and occupancy
(metres of lane covered). They are deliberately **not** SUMO's defaults --
SUMO models an auto-rickshaw as a 5 m `taxi`, which is a simulation artefact,
not what a camera should assume. The digital-twin experiments pass SUMO's
own dimensions in explicitly (`ClassTable.with_dimensions`) so the twin is
self-consistent, and say so.

`person` exists only so people can be found and blurred (ADR-006: vision
never infers human behaviour). It has no PCU and no rule reads it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class VClass(StrEnum):
    MOTORCYCLE = "motorcycle"
    CAR = "car"
    AUTO_RICKSHAW = "auto_rickshaw"
    BUS = "bus"
    TRUCK = "truck"
    BICYCLE = "bicycle"
    PERSON = "person"


VEHICLE_CLASSES = frozenset(c for c in VClass if c is not VClass.PERSON)


@dataclass(frozen=True)
class ClassInfo:
    pcu: float
    length_m: float
    width_m: float
    height_m: float
    provisional_pcu: bool = False


_DEFAULT_INFO: dict[VClass, ClassInfo] = {
    VClass.MOTORCYCLE: ClassInfo(0.3, 2.0, 0.8, 1.5),      # height with rider
    VClass.CAR: ClassInfo(1.0, 4.2, 1.75, 1.5),
    VClass.AUTO_RICKSHAW: ClassInfo(0.6, 2.7, 1.3, 1.8),
    VClass.BUS: ClassInfo(3.0, 11.0, 2.5, 3.2),
    VClass.TRUCK: ClassInfo(3.0, 8.0, 2.5, 3.0, provisional_pcu=True),
    VClass.BICYCLE: ClassInfo(0.2, 1.8, 0.6, 1.6, provisional_pcu=True),
    VClass.PERSON: ClassInfo(0.0, 0.5, 0.5, 1.7),
}


@dataclass(frozen=True)
class ClassTable:
    """Per-class PCU and dimensions. Immutable; derive variants with the
    `with_*` methods."""

    info: dict[VClass, ClassInfo]

    @classmethod
    def default(cls) -> ClassTable:
        return cls(dict(_DEFAULT_INFO))

    def __getitem__(self, c: VClass) -> ClassInfo:
        return self.info[c]

    def pcu(self, c: VClass) -> float:
        return self.info[c].pcu

    def with_dimensions(self, dims: dict[VClass, tuple[float, float]]) -> ClassTable:
        """Override `(length, width)` for some classes -- used by the
        digital twin to match the simulation's own vehicle sizes."""
        new = dict(self.info)
        for c, (length, width) in dims.items():
            new[c] = replace(new[c], length_m=length, width_m=width)
        return ClassTable(new)

    def with_pcu(self, pcu: dict[VClass, float]) -> ClassTable:
        new = dict(self.info)
        for c, v in pcu.items():
            new[c] = replace(new[c], pcu=v)
        return ClassTable(new)


# ---- label maps --------------------------------------------------------

# COCO ids a stock YOLO11 checkpoint emits. Anything else (traffic lights,
# dogs, umbrellas...) is dropped, not guessed at.
COCO_TO_VCLASS: dict[int, VClass] = {
    0: VClass.PERSON,
    1: VClass.BICYCLE,
    2: VClass.CAR,
    3: VClass.MOTORCYCLE,
    5: VClass.BUS,
    7: VClass.TRUCK,
}

# SUMO vType ids of the Vijayawada demand (assign_vtypes.py), and SUMO
# vClasses for any other scenario.
SUMO_VTYPE_TO_VCLASS: dict[str, VClass] = {
    "veh_motorcycle": VClass.MOTORCYCLE,
    "veh_car": VClass.CAR,
    "veh_auto": VClass.AUTO_RICKSHAW,
    "veh_bus": VClass.BUS,
}
SUMO_VCLASS_TO_VCLASS: dict[str, VClass] = {
    "motorcycle": VClass.MOTORCYCLE,
    "moped": VClass.MOTORCYCLE,
    "passenger": VClass.CAR,
    "private": VClass.CAR,
    "taxi": VClass.AUTO_RICKSHAW,
    "bus": VClass.BUS,
    "coach": VClass.BUS,
    "truck": VClass.TRUCK,
    "trailer": VClass.TRUCK,
    "delivery": VClass.TRUCK,
    "bicycle": VClass.BICYCLE,
    "pedestrian": VClass.PERSON,
}

# Name fragments for fine-tuned models (BMD-45, IDD, UVH-26 and similar use
# free-text class names). Checked in order; first match wins, so the more
# specific fragments come first ("auto" before "car" would matter for
# "autocar"-style names; "bus" before "minibus" does not; "traveller" before
# "tempo": a Tempo Traveller is a passenger van, a tempo a goods carrier).
# BMD-45 and UVH-26 share 14 labels -- Hatchback, Sedan, SUV, MUV, Bus,
# Truck, Three-wheeler, Two-wheeler, LCV, Mini-bus, Tempo-traveller,
# Bicycle, Van, Other -- and every one but "Other" must land somewhere: a
# label that maps to nothing is a vehicle the queue count never sees.
_NAME_RULES: tuple[tuple[tuple[str, ...], VClass], ...] = (
    (("auto", "rickshaw", "three-wheeler", "three_wheeler", "3-wheeler", "tuk"),
     VClass.AUTO_RICKSHAW),
    (("motorbike", "motorcycle", "scooter", "two-wheeler", "two_wheeler", "2-wheeler", "bike",
      "moped"), VClass.MOTORCYCLE),
    (("bicycle", "cycle"), VClass.BICYCLE),
    (("bus", "traveller", "traveler"), VClass.BUS),
    (("truck", "lorry", "lcv", "tempo", "tractor", "trailer", "tanker"), VClass.TRUCK),
    (("car", "sedan", "suv", "muv", "hatchback", "van", "jeep", "taxi", "mpv"), VClass.CAR),
    (("person", "pedestrian", "people"), VClass.PERSON),
)


def vclass_from_name(name: str) -> VClass | None:
    """Map a detector's free-text class name into the taxonomy, or `None`
    for anything that is not a road user we track."""
    n = name.strip().lower()
    for fragments, vclass in _NAME_RULES:
        if any(f in n for f in fragments):
            return vclass
    return None


def vclass_from_sumo(vtype_id: str, vclass: str = "") -> VClass:
    if vtype_id in SUMO_VTYPE_TO_VCLASS:
        return SUMO_VTYPE_TO_VCLASS[vtype_id]
    if vclass in SUMO_VCLASS_TO_VCLASS:
        return SUMO_VCLASS_TO_VCLASS[vclass]
    return VClass.CAR
