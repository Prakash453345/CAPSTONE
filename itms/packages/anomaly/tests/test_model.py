"""Unit tests for the itms_anomaly package."""

import pytest
import torch
import numpy as np
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
import pandas as pd

from itms_anomaly.model import SpatioTemporalGAE
from itms_anomaly.baseline import EWMABaseline
from itms_anomaly.conformal import ConformalCalibrator
from itms_anomaly.graph import build_graph_from_net
from itms_anomaly.dataset import TrafficDataset, FeatureScaler


def test_model_forward():
    """Test model forward pass with random data."""
    batch_size = 4
    time_steps = 10
    num_nodes = 5
    in_features = 6
    
    model = SpatioTemporalGAE(in_features=in_features)
    
    x = torch.randn(batch_size, time_steps, num_nodes, in_features)
    # Simple linear graph 0->1->2->3->4
    edge_index = torch.tensor([
        [0, 1, 2, 3],
        [1, 2, 3, 4]
    ], dtype=torch.long)
    
    out = model(x, edge_index)
    
    assert out.shape == (batch_size, time_steps, num_nodes, in_features)


def test_ewma_baseline():
    """Test EWMA baseline update and scoring."""
    baseline = EWMABaseline(alpha=0.5)
    
    tick1 = {
        "edge_1": {"speed": 10.0, "occ": 0.1},
        "edge_2": {"speed": 12.0, "occ": 0.2}
    }
    
    baseline.update(tick1)
    scores1 = baseline.score()
    
    # First update sets state, score should be 0
    assert scores1["edge_1"] == 0.0
    assert scores1["edge_2"] == 0.0
    
    # Second update with same values
    baseline.update(tick1)
    scores2 = baseline.score()
    assert scores2["edge_1"] == 0.0
    
    # Update with an anomaly
    tick3 = {
        "edge_1": {"speed": 2.0, "occ": 0.9},
        "edge_2": {"speed": 12.0, "occ": 0.2}
    }
    baseline.update(tick3)
    scores3 = baseline.score()
    
    assert scores3["edge_1"] > 0.0
    assert scores3["edge_2"] == 0.0


def test_conformal_calibrator():
    """Test conformal calibrator fit and threshold."""
    calibrator = ConformalCalibrator(alpha=0.1, window_size=100)
    
    normal_scores = np.random.uniform(0.1, 1.0, size=200)
    
    tau = calibrator.fit(normal_scores)
    
    assert calibrator.threshold == tau
    assert tau > 0.0
    assert len(calibrator.scores) == 100  # Window size
    
    new_tau = calibrator.update(0.5)
    assert calibrator.threshold == new_tau
    assert len(calibrator.scores) == 100


def test_graph_construction():
    """Test graph construction from a small synthetic net.xml."""
    xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<net>
    <edge id="edge1" from="node1" to="node2"/>
    <edge id="edge2" from="node2" to="node3"/>
    <edge id=":internal" from="node2" to="node2"/>
    <connection from="edge1" to="edge2"/>
    <connection from="edge1" to=":internal"/>
</net>
    '''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.net.xml', delete=False) as f:
        f.write(xml_content)
        temp_path = f.name
        
    try:
        edge_index, node_index = build_graph_from_net(temp_path)
        
        assert "edge1" in node_index
        assert "edge2" in node_index
        assert ":internal" not in node_index
        
        assert edge_index.shape[0] == 2
        assert edge_index.shape[1] == 1  # Only edge1 -> edge2 should be kept
        
    finally:
        Path(temp_path).unlink()


def test_dataset_windowing():
    """Test dataset windowing."""
    df = pd.DataFrame({
        "tick": [1, 1, 2, 2, 3, 3, 4, 4],
        "edge_id": ["e1", "e2", "e1", "e2", "e1", "e2", "e1", "e2"],
        "queue_pcu": [0, 0, 1, 0, 2, 0, 0, 0],
        "receiving_occupancy": [0, 0, 0, 0, 0, 0, 0, 0],
        "mean_speed_mps": [10, 10, 10, 10, 10, 10, 10, 10],
        "occupancy": [0, 0, 0, 0, 0, 0, 0, 0],
        "wait_time_s": [0, 0, 0, 0, 0, 0, 0, 0],
        "vehicle_count": [1, 1, 1, 1, 1, 1, 1, 1]
    })
    
    node_index = {"e1": 0, "e2": 1}
    
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.parquet', delete=False) as f:
        df.to_parquet(f.name)
        temp_path = f.name
        
    try:
        dataset = TrafficDataset([temp_path], node_index, window_size=2, stride=1)
        
        assert len(dataset) == 3  # (4 ticks - 2 window) + 1 = 3
        
        item = dataset[0]
        assert item.shape == (2, 2, 6)  # [T, N, F]
        
    finally:
        Path(temp_path).unlink()
