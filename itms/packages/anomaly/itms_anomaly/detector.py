"""Online anomaly detector using the SpatioTemporalGAE."""

import torch
import numpy as np
from collections import deque
from typing import Dict

from itms_anomaly.model import SpatioTemporalGAE
from itms_anomaly.dataset import FeatureScaler


class AnomalyDetector:
    """Loads a trained SpatioTemporalGAE and scores new observations.
    
    Maintains a rolling z-score per node: each node's reconstruction
    error is compared to its own recent history, not a global threshold.
    """
    
    def __init__(
        self, 
        model: SpatioTemporalGAE, 
        edge_index: torch.Tensor, 
        node_index: Dict[str, int], 
        scaler: FeatureScaler, 
        window_size: int = 10, 
        z_window: int = 100
    ):
        """Initialize the detector.
        
        Args:
            model: Trained SpatioTemporalGAE model.
            edge_index: Graph connectivity.
            node_index: Mapping from edge ID to integer node index.
            scaler: Fitted FeatureScaler.
            window_size: Model input temporal window size.
            z_window: Window size for tracking rolling reconstruction error stats.
        """
        self.model = model
        self.model.eval()
        self.device = next(model.parameters()).device
        self.edge_index = edge_index.to(self.device)
        self.node_index = node_index
        self.reverse_node_index = {v: k for k, v in node_index.items()}
        self.scaler = scaler
        self.window_size = window_size
        
        self.num_nodes = len(node_index)
        self.num_features = len(model.in_features) if hasattr(model, 'in_features') else 6
        
        # Buffer to keep the recent window_size observations
        self.observation_buffer = deque(maxlen=window_size)
        
        # Buffer to keep the recent reconstruction errors for rolling z-score
        self.error_history = {i: deque(maxlen=z_window) for i in range(self.num_nodes)}
        
        self._last_raw_scores = {}
        self._last_z_scores = {}
        
        # Expected feature order, should match dataset.py
        self.feature_columns = [
            "queue_pcu", 
            "receiving_occupancy", 
            "mean_speed_mps", 
            "occupancy", 
            "wait_time_s", 
            "vehicle_count"
        ]

    def update(self, tick_features: dict[str, dict[str, float]]) -> None:
        """Update the detector with new observations.
        
        Args:
            tick_features: Dictionary mapping edge_id to a dictionary of features.
        """
        # Create a tensor for the current tick
        current_obs = np.zeros((self.num_nodes, self.num_features), dtype=np.float32)
        
        for edge_id, features in tick_features.items():
            if edge_id in self.node_index:
                idx = self.node_index[edge_id]
                for f_idx, col in enumerate(self.feature_columns):
                    current_obs[idx, f_idx] = features.get(col, 0.0)
                    
        # Scale the observation
        # reshape to fit scaler [1, N, F]
        scaled_obs = self.scaler.transform(current_obs.reshape(1, self.num_nodes, self.num_features))
        
        # Add to buffer
        self.observation_buffer.append(scaled_obs[0])
        
        if len(self.observation_buffer) == self.window_size:
            self._compute_scores()

    def _compute_scores(self) -> None:
        """Compute anomaly scores for the current window."""
        # Stack buffer to shape [T, N, F]
        window_data = np.stack(self.observation_buffer, axis=0)
        
        # Convert to tensor and add batch dim: [1, T, N, F]
        x = torch.from_numpy(window_data).float().unsqueeze(0).to(self.device)
        
        with torch.no_grad():
            reconstructed = self.model(x, self.edge_index)
            
        # Calculate reconstruction error per node (MSE across features, for the latest timestep)
        # We focus on the error of the most recent timestep: T-1
        # x shape: [1, T, N, F], reconstructed shape: [1, T, N, F]
        diff = x[0, -1, :, :] - reconstructed[0, -1, :, :]
        # MSE per node: shape [N]
        mse_per_node = torch.mean(diff ** 2, dim=-1).cpu().numpy()
        
        self._last_raw_scores = {}
        self._last_z_scores = {}
        
        for i in range(self.num_nodes):
            err = float(mse_per_node[i])
            edge_id = self.reverse_node_index[i]
            
            self._last_raw_scores[edge_id] = err
            
            history = self.error_history[i]
            if len(history) > 1:
                mean_err = np.mean(history)
                std_err = np.std(history)
                if std_err < 1e-6:
                    std_err = 1e-6
                z_score = (err - mean_err) / std_err
            else:
                z_score = 0.0
                
            self._last_z_scores[edge_id] = z_score
            history.append(err)

    def score(self) -> dict[str, float]:
        """Get the current z-scores per edge.
        
        Returns:
            dict: Mapping from edge ID to z-score.
        """
        return self._last_z_scores

    def score_raw(self) -> dict[str, float]:
        """Get the current raw reconstruction errors per edge.
        
        Returns:
            dict: Mapping from edge ID to raw reconstruction error.
        """
        return self._last_raw_scores
