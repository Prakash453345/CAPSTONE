"""ITMS anomaly detection package — M6.

Graph-aware spatiotemporal anomaly detection for traffic incident identification.
Trained on normal simulated traffic, scores deviation from learned-normal behaviour
per road link using the PostGIS road topology as the graph structure.
"""

from itms_anomaly.model import SpatioTemporalGAE
from itms_anomaly.detector import AnomalyDetector
from itms_anomaly.baseline import EWMABaseline
from itms_anomaly.conformal import ConformalCalibrator

__all__ = ["SpatioTemporalGAE", "AnomalyDetector", "EWMABaseline", "ConformalCalibrator"]
