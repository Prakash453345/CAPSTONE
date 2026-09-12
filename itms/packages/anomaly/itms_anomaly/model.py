"""Spatiotemporal Graph Autoencoder model."""

import torch
import torch.nn as nn
from torch_geometric.nn import GATConv


class SpatioTemporalGAE(nn.Module):
    """Spatiotemporal Graph Autoencoder for traffic anomaly detection.
    
    Architecture:
      Input [batch, T, N, F] 
        -> GATConv (spatial, per-timestep, 2 heads) 
        -> GRU (temporal, per-node)
        -> Linear decoder -> reconstruct input [batch, T, N, F]
    
    Trained as reconstruction autoencoder on normal traffic.
    Anomaly score = per-node reconstruction error.
    """
    
    def __init__(
        self, 
        in_features: int = 6, 
        hidden_dim: int = 32, 
        gru_hidden: int = 32, 
        num_heads: int = 2, 
        dropout: float = 0.1
    ):
        """Initialize the model.
        
        Args:
            in_features: Number of input features per node.
            hidden_dim: Output dimension of the GATConv layer per head.
            gru_hidden: Hidden dimension of the GRU layer.
            num_heads: Number of attention heads in GATConv.
            dropout: Dropout probability.
        """
        super().__init__()
        self.in_features = in_features
        self.hidden_dim = hidden_dim
        self.gru_hidden = gru_hidden
        self.num_heads = num_heads
        
        # Spatial Layer: GAT
        self.gat = GATConv(
            in_channels=in_features, 
            out_channels=hidden_dim, 
            heads=num_heads, 
            dropout=dropout,
            concat=True
        )
        
        # Temporal Layer: GRU
        gat_out_dim = hidden_dim * num_heads
        self.gru = nn.GRU(
            input_size=gat_out_dim, 
            hidden_size=gru_hidden, 
            batch_first=True
        )
        
        # Decoder Layer
        self.decoder = nn.Sequential(
            nn.Linear(gru_hidden, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, in_features)
        )

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        """Forward pass.
        
        Args:
            x: Input tensor of shape [batch, T, N, F].
            edge_index: Graph connectivity of shape [2, E].
            
        Returns:
            torch.Tensor: Reconstructed input of shape [batch, T, N, F].
        """
        batch_size, time_steps, num_nodes, _ = x.size()
        
        # 1. Spatial embedding via GAT (applied per timestep)
        spatial_out = []
        for t in range(time_steps):
            # x_t shape: [batch, N, F]
            x_t = x[:, t, :, :]
            # Reshape for GAT: [(batch*N), F]
            x_t_flat = x_t.view(batch_size * num_nodes, self.in_features)
            
            # Since GAT is applied to the same graph for all items in batch,
            # we need to create a batched edge_index or just loop. 
            # For simplicity and standard PyG practice without a DataLoader,
            # we replicate the graph connectivity for the batched elements.
            # But the simplest way is to treat batch*N as a single disconnected graph 
            # containing 'batch' identical subgraphs.
            
            # Create batched edge_index
            batched_edge_index = edge_index.repeat(1, batch_size)
            offsets = torch.arange(batch_size, device=x.device).repeat_interleave(edge_index.size(1)) * num_nodes
            batched_edge_index = batched_edge_index + offsets.unsqueeze(0)
            
            # Apply GAT
            out_t = self.gat(x_t_flat, batched_edge_index)
            # Reshape back to [batch, N, gat_out_dim]
            out_t = out_t.view(batch_size, num_nodes, -1)
            spatial_out.append(out_t)
            
        # Stack spatial features: [batch, T, N, gat_out_dim]
        spatial_out = torch.stack(spatial_out, dim=1)
        
        # 2. Temporal embedding via GRU (applied per node)
        # Reshape to [batch * N, T, gat_out_dim] for GRU
        gat_out_dim = spatial_out.size(-1)
        temporal_in = spatial_out.transpose(1, 2).contiguous().view(batch_size * num_nodes, time_steps, gat_out_dim)
        
        gru_out, _ = self.gru(temporal_in)
        
        # 3. Decode
        # gru_out is [batch * N, T, gru_hidden]
        reconstructed = self.decoder(gru_out)
        
        # Reshape back to [batch, N, T, F] and transpose to [batch, T, N, F]
        reconstructed = reconstructed.view(batch_size, num_nodes, time_steps, self.in_features)
        reconstructed = reconstructed.transpose(1, 2).contiguous()
        
        return reconstructed
