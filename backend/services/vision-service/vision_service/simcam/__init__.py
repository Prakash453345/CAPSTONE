"""SimCam: a digital-twin camera that films the SUMO corridor through each
real camera's geometry, with exact ground truth. See
docs/vision_system_design.md §4."""

from vision_service.simcam.errors import PRESETS, ErrorPreset, PerceptionErrorModel
from vision_service.simcam.render import FilmedObjects, film, rasterise
from vision_service.simcam.world import (
    TraciWorld,
    WorldSnapshot,
    interpolate,
    snapshot_from_records,
)

__all__ = [
    "PRESETS",
    "ErrorPreset",
    "FilmedObjects",
    "PerceptionErrorModel",
    "TraciWorld",
    "WorldSnapshot",
    "film",
    "interpolate",
    "rasterise",
    "snapshot_from_records",
]
