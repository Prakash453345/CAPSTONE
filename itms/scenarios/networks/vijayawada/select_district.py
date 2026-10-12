"""Choose what the district network keeps, from a first-pass netconvert build.

Two decisions, both deterministic so `build_district.sh` reproduces them:

1. **Edges: the largest strongly connected component** of the routable road
   graph (edges as nodes, SUMO connections as arcs). A bbox crop leaves
   one-way stubs and dead ends at the box edge that cannot reach the rest of
   the network, or cannot be reached from it. Keeping only the strongly
   connected core guarantees that every road can reach every other road, so a
   route request between any two of them always has an answer and "no route"
   only ever comes from live conditions (a blockage), never from geometry.

2. **Signals: every real four-way crossing of named arterials** -- a junction
   with at least 3 incoming and 3 outgoing roads within the core, carrying at
   least two different street names. OSM tags only a couple of signals in
   this area, far fewer than the real city has; this rule picks the
   intersections a traffic authority would signalise (it reproduces all four
   MG Road junctions the corridor network already signalises) without
   hand-picking.

Usage:
    python select_district.py survey.net.xml keep_edges.txt tls_ids.txt
    python select_district.py --verify final.net.xml keep_edges.txt tls_ids.txt

`--verify` checks a finished network against those choices and exits non-zero
on any mismatch: every road reaches every other, the road set is exactly the
chosen core, and every chosen crossing is a signal.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "services" / "sim-service"))

from sim_service.routing import RoadGraph  # noqa: E402


def strongly_connected_core(graph: RoadGraph) -> list[str]:
    """Edges of the largest strongly connected component (Kosaraju, iterative)."""
    nodes = sorted(graph.edges)
    adj = {e: [ge.to_edge for ge in graph.neighbours(e)] for e in nodes}
    radj: dict[str, list[str]] = {e: [] for e in nodes}
    for a, bs in adj.items():
        for b in bs:
            radj[b].append(a)

    order: list[str] = []
    seen: set[str] = set()
    for s in nodes:
        if s in seen:
            continue
        seen.add(s)
        stack = [(s, iter(adj[s]))]
        while stack:
            v, it = stack[-1]
            for w in it:
                if w not in seen:
                    seen.add(w)
                    stack.append((w, iter(adj[w])))
                    break
            else:
                order.append(v)
                stack.pop()

    comp: dict[str, str] = {}
    for s in reversed(order):
        if s in comp:
            continue
        comp[s] = s
        todo = [s]
        while todo:
            v = todo.pop()
            for w in radj[v]:
                if w not in comp:
                    comp[w] = s
                    todo.append(w)

    root, _ = Counter(comp.values()).most_common(1)[0]
    return sorted(e for e in nodes if comp[e] == root)


def arterial_crossings(net_path: Path, graph: RoadGraph, core: list[str]) -> list[str]:
    names = {
        e.get("id"): e.get("name") or ""
        for e in ET.parse(net_path).getroot().findall("edge")
        if not (e.get("id") or "").startswith(":")
    }
    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    streets: dict[str, set[str]] = defaultdict(set)
    for eid in core:
        info = graph.edges[eid]
        incoming[info.to_junction].add(eid)
        outgoing[info.from_junction].add(eid)
        for j in (info.to_junction, info.from_junction):
            if names.get(eid):
                streets[j].add(names[eid])
    return sorted(
        j
        for j in set(incoming) | set(outgoing)
        if len(incoming[j]) >= 3 and len(outgoing[j]) >= 3 and len(streets[j]) >= 2
    )


def missing_signals(graph: RoadGraph, tls_path: Path) -> list[str]:
    """Chosen crossings that are not yet a signal in `graph` (a joined
    junction counts as signalised when it shares an OSM node with a signal)."""
    chosen = [t for t in tls_path.read_text().strip().split(",") if t]
    signals = set(graph.signalised_junctions)
    missing = []
    for t in chosen:
        parts = set(t.removeprefix("cluster_").split("_"))
        hit = any(s == t or parts & set(s.removeprefix("cluster_").split("_")) for s in signals)
        if not hit:
            missing.append(t)
    return missing


def verify(net: Path, keep_path: Path, tls_path: Path) -> list[str]:
    """Problems with a finished network, or [] when it is what was chosen."""
    graph = RoadGraph.from_network(net)
    problems: list[str] = []
    core = strongly_connected_core(graph)
    if len(core) != len(graph.edges):
        problems.append(f"only {len(core)} of {len(graph.edges)} roads are mutually reachable")
    wanted = set(keep_path.read_text().split())
    have = set(graph.edges)
    if wanted != have:
        problems.append(f"road set differs from the chosen core: {len(wanted - have)} missing, {len(have - wanted)} extra")
    missing = missing_signals(graph, tls_path)
    if missing:
        problems.append(f"{len(missing)} chosen crossings are not signals: {missing}")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--missing", action="store_true", help="print the chosen crossings not yet signalised")
    ap.add_argument("net")
    ap.add_argument("keep_edges")
    ap.add_argument("tls_ids")
    args = ap.parse_args()
    net = Path(args.net)
    if args.missing:
        print(",".join(missing_signals(RoadGraph.from_network(net), Path(args.tls_ids))))
        return
    if args.verify:
        problems = verify(net, Path(args.keep_edges), Path(args.tls_ids))
        if problems:
            for p in problems:
                print("FAIL:", p)
            sys.exit(1)
        g = RoadGraph.from_network(net)
        print(f"ok: {len(g.edges)} roads, all mutually reachable; {len(g.signalised_junctions)} signals")
        return
    graph = RoadGraph.from_network(net)
    core = strongly_connected_core(graph)
    tls = arterial_crossings(net, graph, core)
    Path(args.keep_edges).write_text("\n".join(core) + "\n")
    Path(args.tls_ids).write_text(",".join(tls) + "\n")
    print(f"{len(core)}/{len(graph.edges)} edges in the connected core, {len(tls)} signalised crossings")


if __name__ == "__main__":
    main()
