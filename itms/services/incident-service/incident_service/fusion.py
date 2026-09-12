import numpy as np

class FusionLayer:
    """Interpretable fusion: logistic regression over engineered features.
    
    Features:
    - graph_score: from the GNN detector
    - vision_score: from vision stream (0.0 until M8)
    - phase_is_green: 1 if signal phase is green, 0 otherwise
    - queue_during_green: graph_score * phase_is_green (interaction)
    - time_sin, time_cos: cyclical time encoding
    
    Graceful degradation: vision_score coefficient is 0 until M8 trains it.
    """
    
    def __init__(self, weights=None):
        # Default weights: graph_score dominates, phase interaction boosts
        if weights is None:
            self.weights = np.array([1.0, 0.0, -0.5, 0.8, 0.1, 0.1])
            self.bias = -1.5
        else:
            self.weights = np.array(weights[:-1])
            self.bias = weights[-1]
    
    def fuse(self, graph_score: float, vision_score: float | None = None, phase_is_green: bool = False, sim_time_s: float = 0.0) -> float:
        vision = vision_score if vision_score is not None else 0.0
        green = 1.0 if phase_is_green else 0.0
        t = (sim_time_s % 1800) / 1800 * 2 * np.pi
        features = np.array([
            graph_score,
            vision,
            green,
            graph_score * green,
            np.sin(t),
            np.cos(t),
        ])
        logit = features @ self.weights + self.bias
        return float(1.0 / (1.0 + np.exp(-logit)))  # sigmoid → fused_score in [0,1]
