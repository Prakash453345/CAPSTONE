"""EWMA baseline anomaly detector."""

import math


class EWMABaseline:
    """Per-link EWMA with z-score threshold. No spatial context.
    
    The 'regular approach' baseline the GNN must beat.
    """
    
    def __init__(self, alpha: float = 0.1, z_threshold: float = 3.0):
        """Initialize the baseline detector.
        
        Args:
            alpha: EWMA smoothing factor (0 < alpha <= 1).
            z_threshold: Z-score threshold for anomaly detection.
        """
        self.alpha = alpha
        self.z_threshold = z_threshold
        
        # State: {edge_id: {feature_name: (mean, variance)}}
        self.state = {}
        
        self._last_scores = {}
        
    def update(self, tick_features: dict[str, dict[str, float]]) -> None:
        """Update the EWMA states and compute current scores.
        
        Args:
            tick_features: Dictionary mapping edge_id to feature dictionary.
        """
        self._last_scores = {}
        
        for edge_id, features in tick_features.items():
            if edge_id not in self.state:
                self.state[edge_id] = {}
                # Initialize state with first observations
                for feat, val in features.items():
                    self.state[edge_id][feat] = (val, 0.0)
                self._last_scores[edge_id] = 0.0
                continue
                
            max_z = 0.0
            
            for feat, val in features.items():
                if feat not in self.state[edge_id]:
                    self.state[edge_id][feat] = (val, 0.0)
                    continue
                    
                prev_mean, prev_var = self.state[edge_id][feat]
                
                # Compute diff from previous mean
                diff = val - prev_mean
                
                # Update mean
                new_mean = prev_mean + self.alpha * diff
                
                # Update variance
                # Using incremental variance update
                new_var = (1 - self.alpha) * (prev_var + self.alpha * (diff ** 2))
                
                self.state[edge_id][feat] = (new_mean, new_var)
                
                # Compute z-score
                std_dev = math.sqrt(prev_var)
                if std_dev > 1e-6:
                    z = abs(diff) / std_dev
                else:
                    z = 0.0
                    
                if z > max_z:
                    max_z = z
                    
            self._last_scores[edge_id] = max_z

    def score(self) -> dict[str, float]:
        """Get the current max z-scores per edge.
        
        Returns:
            dict: Mapping from edge ID to max z-score across all features.
        """
        return self._last_scores
