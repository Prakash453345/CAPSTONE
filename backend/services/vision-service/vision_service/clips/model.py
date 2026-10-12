"""The record every clip detector produces."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Finding:
    """One thing a detector flagged in a clip. `anomaly_type` is an
    `itms_domain.anomaly.AnomalyType` value; `severity`/`reasons` are filled
    in by `severity.assess` once the whole clip has been seen."""

    anomaly_type: str
    detector: str                      # "accident" | "fire" | "stalled" | "congestion"
    confidence: float                  # 0..1, how sure the detector was
    start_s: float
    end_s: float
    evidence: dict = field(default_factory=dict)
    box_norm: tuple[float, float, float, float] | None = None   # x1,y1,x2,y2 as 0..1 of the frame
    severity: str = ""
    reasons: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "anomaly_type": self.anomaly_type,
            "detector": self.detector,
            "severity": self.severity,
            "confidence": round(self.confidence, 3),
            "start_s": round(self.start_s, 2),
            "end_s": round(self.end_s, 2),
            "reasons": list(self.reasons),
            "evidence": self.evidence,
            "box_norm": None if self.box_norm is None else [round(v, 4) for v in self.box_norm],
        }
