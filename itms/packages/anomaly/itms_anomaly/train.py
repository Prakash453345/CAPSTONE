"""Training loop for the SpatioTemporalGAE model."""

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
import copy


def train_model(
    model: nn.Module, 
    dataset: Dataset, 
    edge_index: torch.Tensor, 
    epochs: int = 50, 
    lr: float = 1e-3, 
    batch_size: int = 32,
    patience: int = 5,
    val_split: float = 0.2
) -> dict:
    """Train the SpatioTemporalGAE model.
    
    Args:
        model: The model to train.
        dataset: The dataset containing normal traffic data.
        edge_index: The graph connectivity tensor.
        epochs: Maximum number of epochs.
        lr: Learning rate.
        batch_size: Batch size.
        patience: Early stopping patience.
        val_split: Fraction of dataset to use for validation.
        
    Returns:
        dict: Training history containing 'train_losses', 'val_losses', and 'best_epoch'.
    """
    device = next(model.parameters()).device
    edge_index = edge_index.to(device)
    
    # Split dataset
    dataset_size = len(dataset)
    val_size = int(dataset_size * val_split)
    train_size = dataset_size - val_size
    
    if val_size == 0 or train_size == 0:
        # Fallback if dataset is too small
        train_loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)
    else:
        train_dataset, val_dataset = torch.utils.data.random_split(dataset, [train_size, val_size])
        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
        
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.MSELoss()
    
    history = {
        "train_losses": [],
        "val_losses": [],
        "best_epoch": 0
    }
    
    best_val_loss = float('inf')
    best_model_state = None
    patience_counter = 0
    
    for epoch in range(epochs):
        # Training phase
        model.train()
        train_loss = 0.0
        
        for batch in train_loader:
            batch = batch.to(device)
            optimizer.zero_grad()
            
            reconstructed = model(batch, edge_index)
            loss = criterion(reconstructed, batch)
            
            loss.backward()
            optimizer.step()
            
            train_loss += loss.item() * batch.size(0)
            
        train_loss /= len(train_loader.dataset)
        history["train_losses"].append(train_loss)
        
        # Validation phase
        model.eval()
        val_loss = 0.0
        
        with torch.no_grad():
            for batch in val_loader:
                batch = batch.to(device)
                reconstructed = model(batch, edge_index)
                loss = criterion(reconstructed, batch)
                val_loss += loss.item() * batch.size(0)
                
        val_loss /= len(val_loader.dataset)
        history["val_losses"].append(val_loss)
        
        print(f"Epoch {epoch+1}/{epochs} - Train Loss: {train_loss:.6f}, Val Loss: {val_loss:.6f}")
        
        # Early stopping
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_model_state = copy.deepcopy(model.state_dict())
            history["best_epoch"] = epoch + 1
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= patience:
                print(f"Early stopping triggered at epoch {epoch+1}")
                break
                
    # Restore best model
    if best_model_state is not None:
        model.load_state_dict(best_model_state)
        
    return history
