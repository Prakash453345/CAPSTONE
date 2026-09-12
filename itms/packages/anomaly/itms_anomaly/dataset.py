"""Dataset for training spatiotemporal models from Parquet logs."""

import json
from pathlib import Path

import torch
from torch.utils.data import Dataset
import pandas as pd
import numpy as np


class FeatureScaler:
    """Scales features using z-score normalization."""
    
    def __init__(self):
        self.means = None
        self.stds = None
        self.is_fitted = False
        
    def fit(self, data: np.ndarray) -> None:
        """Fit scaler on data of shape [..., F].
        
        Args:
            data: Data array from which to compute mean and standard deviation.
        """
        # Reshape to [N, F] to compute stats per feature
        flat_data = data.reshape(-1, data.shape[-1])
        self.means = np.mean(flat_data, axis=0)
        self.stds = np.std(flat_data, axis=0)
        self.stds[self.stds == 0] = 1.0  # Prevent division by zero
        self.is_fitted = True
        
    def transform(self, data: np.ndarray) -> np.ndarray:
        """Apply scaling to data.
        
        Args:
            data: Data array to scale.
            
        Returns:
            np.ndarray: Scaled data.
        """
        if not self.is_fitted:
            raise RuntimeError("Scaler has not been fitted.")
        return (data - self.means) / self.stds
        
    def fit_transform(self, data: np.ndarray) -> np.ndarray:
        """Fit and transform data.
        
        Args:
            data: Data array to fit and scale.
            
        Returns:
            np.ndarray: Scaled data.
        """
        self.fit(data)
        return self.transform(data)

    def save(self, path: str | Path) -> None:
        """Save scaler parameters to JSON."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "means": self.means.tolist(),
                "stds": self.stds.tolist(),
            }, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "FeatureScaler":
        """Load scaler parameters from JSON."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        scaler = cls()
        scaler.means = np.array(data["means"])
        scaler.stds = np.array(data["stds"])
        scaler.is_fitted = True
        return scaler


class TrafficDataset(Dataset):
    """PyTorch Dataset for spatiotemporal traffic data.
    
    Produces sliding windows of shape [T_window, N_nodes, F_features].
    """
    
    FEATURE_COLUMNS = [
        "queue_pcu", 
        "receiving_occupancy", 
        "mean_speed_mps", 
        "occupancy", 
        "wait_time_s", 
        "vehicle_count"
    ]
    
    def __init__(self, parquet_paths: list[str], node_index: dict[str, int], 
                 window_size: int = 10, stride: int = 1, scaler: FeatureScaler | None = None):
        """Initialize the dataset.
        
        Args:
            parquet_paths: List of paths to Parquet files containing traffic data.
            node_index: Mapping from edge ID to integer node index.
            window_size: Size of the temporal window.
            stride: Stride for sliding windows.
            scaler: Optional pre-fitted FeatureScaler. If None, fits a new one.
        """
        self.window_size = window_size
        self.stride = stride
        self.num_nodes = len(node_index)
        self.num_features = len(self.FEATURE_COLUMNS)
        
        # Load and combine all parquet files
        dfs = [pd.read_parquet(p) for p in parquet_paths]
        if not dfs:
            raise ValueError("No data provided.")
        df = pd.concat(dfs, ignore_index=True)
        
        # Ensure we only keep data for known nodes
        df = df[df["edge_id"].isin(node_index.keys())]
        
        # Determine ticks
        ticks = sorted(df["tick"].unique())
        self.num_ticks = len(ticks)
        
        # Create full tensor [T, N, F]
        raw_data = np.zeros((self.num_ticks, self.num_nodes, self.num_features), dtype=np.float32)
        
        # Fill data
        # Mapping tick to index
        tick_to_idx = {tick: idx for idx, tick in enumerate(ticks)}
        
        for _, row in df.iterrows():
            t_idx = tick_to_idx[row["tick"]]
            n_idx = node_index[row["edge_id"]]
            for f_idx, col in enumerate(self.FEATURE_COLUMNS):
                raw_data[t_idx, n_idx, f_idx] = row[col]
                
        # Scale data
        if scaler is None:
            self.scaler = FeatureScaler()
            self.data = self.scaler.fit_transform(raw_data)
        else:
            self.scaler = scaler
            self.data = self.scaler.transform(raw_data)
            
        # Convert to tensor
        self.data = torch.from_numpy(self.data).float()
        
        # Calculate valid window start indices
        self.valid_indices = list(range(0, self.num_ticks - window_size + 1, stride))

    def __len__(self) -> int:
        return len(self.valid_indices)

    def __getitem__(self, idx: int) -> torch.Tensor:
        start = self.valid_indices[idx]
        return self.data[start:start + self.window_size]
