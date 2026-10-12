"""Uploaded road videos: the stored record, and the review request bodies."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass
class Clip:
    clip_id: str
    filename: str
    video_path: str
    edge_id: str
    road_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    operator: str = "operator:console"
    submitted_ms: int = 0
    status: str = "QUEUED"            # QUEUED | ANALYSING | DONE | FAILED
    progress: float = 0.0
    result: dict | None = None        # the final ClipAnalysed payload
    review: str | None = None         # PENDING | CONFIRMED | REJECTED; None = nothing to review
    reviewed_by: str = ""
    reviewed_ms: int | None = None
    review_note: str = ""
    anomaly_id: str | None = None     # the anomaly a confirmation created
    confirmed_type: str | None = None
    confirmed_severity: str | None = None


class ClipConfirmRequest(BaseModel):
    actor: str = Field(min_length=1)
    anomaly_type: str | None = None  # the reviewer's correction; default: what the analysis found
    severity: str | None = None
    note: str = ""


class ClipRejectRequest(BaseModel):
    actor: str = Field(min_length=1)
    note: str = ""
