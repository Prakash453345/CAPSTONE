import pytest
import numpy as np
from incident_service.fusion import FusionLayer

def test_fusion_layer_bounds():
    fusion = FusionLayer()
    
    score = fusion.fuse(graph_score=0.0)
    assert 0.0 <= score <= 1.0
    
    score = fusion.fuse(graph_score=10.0)
    assert 0.0 <= score <= 1.0

def test_higher_graph_score_increases_fused_score():
    fusion = FusionLayer()
    
    score1 = fusion.fuse(graph_score=1.0)
    score2 = fusion.fuse(graph_score=5.0)
    
    assert score2 > score1

def test_phase_interaction():
    fusion = FusionLayer()
    
    # Same graph score, but one is during green phase
    score_red = fusion.fuse(graph_score=3.0, phase_is_green=False)
    score_green = fusion.fuse(graph_score=3.0, phase_is_green=True)
    
    # Green phase interaction boosts the score (graph_score * phase_is_green * 0.8)
    assert score_green > score_red

def test_graceful_degradation():
    fusion = FusionLayer()
    
    # vision_score=None should work and be treated as 0.0
    score_none = fusion.fuse(graph_score=2.0, vision_score=None)
    score_zero = fusion.fuse(graph_score=2.0, vision_score=0.0)
    
    assert np.isclose(score_none, score_zero)
