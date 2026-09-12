import os
from dataclasses import dataclass

@dataclass
class IncidentServiceConfig:
    # Event bus
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Database
    database_url: str = os.getenv("DATABASE_URL", "postgresql://itms:itms@localhost:5432/itms")
    
    # Anomaly detector
    model_path: str = os.getenv("MODEL_PATH", "models/anomaly_detector.pt")
    graph_path: str = os.getenv("GRAPH_PATH", "scenarios/networks/vijayawada/adjacency.json")
    scaler_path: str = os.getenv("SCALER_PATH", "models/scaler.json")
    
    # Detection parameters
    window_size: int = int(os.getenv("WINDOW_SIZE", "10"))  # sliding window for GNN input
    z_window: int = int(os.getenv("Z_WINDOW", "100"))    # rolling z-score window
    pre_screen_threshold: float = float(os.getenv("PRE_SCREEN_THRESHOLD", "2.0"))  # pre-screen before fusion
    
    # Conformal calibration
    conformal_alpha: float = float(os.getenv("CONFORMAL_ALPHA", "0.05"))
    conformal_path: str = os.getenv("CONFORMAL_PATH", "models/conformal.json")
    
    # Topics
    approach_state_topic: str = os.getenv("APPROACH_STATE_TOPIC", "approach.state")
    signal_changed_topic: str = os.getenv("SIGNAL_CHANGED_TOPIC", "signal.changed")
    incident_candidate_topic: str = os.getenv("INCIDENT_CANDIDATE_TOPIC", "incident.candidate")
    incident_detected_topic: str = os.getenv("INCIDENT_DETECTED_TOPIC", "incident.detected")
    incident_updated_topic: str = os.getenv("INCIDENT_UPDATED_TOPIC", "incident.updated")
    
    # Consumer
    consumer_group: str = os.getenv("CONSUMER_GROUP", "incident-service")
    consumer_name: str = os.getenv("CONSUMER_NAME", "detector-0")
