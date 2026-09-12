import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path


def build_graph(net_path: str, output_path: str, network_name: str, db_write: bool = False):
    tree = ET.parse(net_path)
    root = tree.getroot()

    edges_set = set()
    adjacency = {}

    for conn in root.findall("connection"):
        from_edge = conn.get("from")
        to_edge = conn.get("to")

        if not from_edge or not to_edge:
            continue

        if from_edge.startswith(":") or to_edge.startswith(":"):
            continue

        edges_set.add(from_edge)
        edges_set.add(to_edge)

        if from_edge not in adjacency:
            adjacency[from_edge] = set()
        adjacency[from_edge].add(to_edge)

    nodes = sorted(list(edges_set))
    node_to_index = {node: i for i, node in enumerate(nodes)}

    edges = []
    adjacency_list = {}
    for node in nodes:
        adj = sorted(list(adjacency.get(node, set())))
        adjacency_list[node] = adj
        from_idx = node_to_index[node]
        for to_node in adj:
            to_idx = node_to_index[to_node]
            edges.append([from_idx, to_idx])

    output_data = {
        "network_name": network_name,
        "nodes": nodes,
        "edges": edges,
        "node_to_index": node_to_index,
        "adjacency_list": adjacency_list
    }

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"Graph built with {len(nodes)} nodes and {len(edges)} edges.")
    print(f"Saved to {output_path}")

    if db_write:
        print("Writing to db not implemented in this minimal version, would connect to postgres.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Graph from SUMO net")
    parser.add_argument("--net", required=True, help="Path to .net.xml")
    parser.add_argument("--output", required=True, help="Path to output JSON")
    parser.add_argument("--network-name", required=True, help="Network name")
    parser.add_argument("--db", action="store_true", help="Write to DB")
    args = parser.parse_args()

    build_graph(args.net, args.output, args.network_name, args.db)
