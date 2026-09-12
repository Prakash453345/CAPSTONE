"""Graph construction utilities from SUMO network."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path
import torch


def build_graph_from_net(net_path: str | Path) -> tuple[torch.Tensor, dict[str, int]]:
    """Parse SUMO net.xml to build a directed graph of road links.
    
    Args:
        net_path: Path to the SUMO network XML file.
        
    Returns:
        tuple:
            - edge_index (torch.Tensor): Tensor of shape [2, num_edges] with long integer indices.
            - node_index (dict[str, int]): Mapping from edge ID to integer node index.
    """
    tree = ET.parse(net_path)
    root = tree.getroot()
    
    edges = set()
    connections = []
    
    for conn in root.findall("connection"):
        from_edge = conn.get("from")
        to_edge = conn.get("to")
        
        if from_edge and to_edge and not from_edge.startswith(":") and not to_edge.startswith(":"):
            edges.add(from_edge)
            edges.add(to_edge)
            connections.append((from_edge, to_edge))
            
    # Create sorted node index for stable mapping
    node_index = {edge_id: idx for idx, edge_id in enumerate(sorted(edges))}
    
    # Build edge_index tensor
    src = [node_index[c[0]] for c in connections]
    dst = [node_index[c[1]] for c in connections]
    
    edge_index = torch.tensor([src, dst], dtype=torch.long)
    
    return edge_index, node_index


def save_adjacency_json(net_path: str | Path, out_path: str | Path) -> None:
    """Extract graph from net.xml and save to a JSON file.
    
    Args:
        net_path: Path to the SUMO network XML file.
        out_path: Path to save the resulting JSON file.
    """
    edge_index, node_index = build_graph_from_net(net_path)
    data = {
        "node_index": node_index,
        "edge_index": edge_index.tolist()
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def build_graph_from_json(json_path: str | Path) -> tuple[torch.Tensor, dict[str, int]]:
    """Load graph structure from a pre-saved JSON file.
    
    Args:
        json_path: Path to the JSON file.
        
    Returns:
        tuple:
            - edge_index (torch.Tensor): Tensor of shape [2, num_edges].
            - node_index (dict[str, int]): Mapping from edge ID to integer node index.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    node_index = data["node_index"]
    edge_index = torch.tensor(data["edge_index"], dtype=torch.long)
    
    return edge_index, node_index
