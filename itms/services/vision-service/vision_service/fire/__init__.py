"""Fire and smoke: detector + crop classifier (`detector`), persistence into
operator-confirmed candidates (`monitor`). Not part of the road-user pipeline."""

from vision_service.fire.monitor import (
    FireCandidate,
    FireMonitor,
    FireMonitorConfig,
)

__all__ = ["FireCandidate", "FireMonitor", "FireMonitorConfig"]
