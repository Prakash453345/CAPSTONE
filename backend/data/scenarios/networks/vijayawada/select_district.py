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

3. **The rest of a split crossing.** OSM draws one real crossing as several
   junctions a few metres apart (a stub of road, a divided road's two
   carriageways). The rule above lights only the one that has the three
   roads each way, so traffic entering by the others never stops for it.
   Any junction reached from a chosen crossing over roads of at most
   `LINK_M` that has at least two roads in and out within the core is
   signalised too. A junction with one road in or one road out is only a
   road splitting or merging, and stays as it is.

4. **Only routes that reach a signal.** The busy routes added beyond the district
   (`filter_district.py --extend`) are kept only as far as they are worth it: from
   the district outward, each signal in the extension keeps the shortest road to it
   and back (and every road meeting it); the spurs and loops with no signal on them
   are dropped. The district itself is never pruned.

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

# backend/data/scenarios/networks/vijayawada/ -> backend/
_BACKEND = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_BACKEND / "services" / "simulation-service"))

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


# Roads this short between two junctions mean they are one crossing (the district's
# nearest unrelated signals are 70 m apart).
LINK_M = 30.0

# Beyond the district a busy route is kept only while a signal follows within this
# many metres of the district or of the last signal: a long road with none is dropped.
MAX_GAP_M = 1200.0
# ...except along a street that has this many signals on it (Karl Marx Road has seven),
# where the signals are the street's own and the road between them is kept.
SIGNALISED_STREET_MIN = 3
ARTERIAL_GAP_M = 3000.0


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
    chosen = {
        j
        for j in set(incoming) | set(outgoing)
        if len(incoming[j]) >= 3 and len(outgoing[j]) >= 3 and len(streets[j]) >= 2
    }
    # Grow each chosen crossing over short roads to the other junctions that make it up.
    length = {
        e.get("id"): float(e.find("lane").get("length"))
        for e in ET.parse(net_path).getroot().findall("edge")
        if e.find("lane") is not None
    }
    near: dict[str, set[str]] = defaultdict(set)
    for eid in core:
        if length.get(eid, 1e9) <= LINK_M:
            info = graph.edges[eid]
            near[info.from_junction].add(info.to_junction)
            near[info.to_junction].add(info.from_junction)
    crossing, todo = set(chosen), list(chosen)
    while todo:
        for m in near[todo.pop()]:
            if m not in crossing and len(incoming[m]) >= 2 and len(outgoing[m]) >= 2:
                crossing.add(m)
                todo.append(m)
    return sorted(crossing)


def outer_crossings(graph: RoadGraph, core: list[str], extension_ways: set[str]) -> set[str]:
    """Junctions of the extension alone where busy roads cross: three roads in and
    out is enough (the extension keeps no side streets, and many of its roads
    are unnamed, so the street-name test would find nothing)."""
    way = lambda e: e.lstrip("-").split("#")[0]  # noqa: E731
    ins: dict[str, int] = defaultdict(int)
    outs: dict[str, int] = defaultdict(int)
    district: set[str] = set()
    for e in core:
        info = graph.edges[e]
        ins[info.to_junction] += 1
        outs[info.from_junction] += 1
        if way(e) not in extension_ways:
            district.update((info.from_junction, info.to_junction))
    return {j for j in set(ins) | set(outs) if j not in district and ins[j] >= 3 and outs[j] >= 3}


def prune_extension(
    graph: RoadGraph, core: list[str], tls: list[str], extension_ways: set[str], names: dict[str, str] | None = None
) -> list[str]:
    """`core` without the extension's roads that lead to no signal, cut back to
    what is still mutually reachable."""
    import heapq  # noqa: PLC0415

    def way_of(edge_id: str) -> str:
        return edge_id.lstrip("-").split("#")[0]

    ext = {e for e in core if way_of(e) in extension_ways}
    signal_ids = set(tls)
    parts = [set(t.removeprefix("cluster_").split("_")) for t in tls]

    def is_signal(j: str) -> bool:
        return j in signal_ids or any(set(j.removeprefix("cluster_").split("_")) & p for p in parts)

    district_nodes: set[str] = set()
    out_of: dict[str, list[tuple[str, float, str]]] = defaultdict(list)  # junction -> (next, metres, edge)
    into: dict[str, list[tuple[str, float, str]]] = defaultdict(list)  # junction -> (previous, metres, edge)
    for e in core:
        info = graph.edges[e]
        out_of[info.from_junction].append((info.to_junction, info.length_m, e))
        into[info.to_junction].append((info.from_junction, info.length_m, e))
        if e not in ext:
            district_nodes.update((info.from_junction, info.to_junction))

    outer = {
        j
        for j in set(out_of) | set(into)
        if j not in district_nodes and is_signal(j)
    }

    def reach(links: dict[str, list[tuple[str, float, str]]]) -> dict[str, tuple[str, str]]:
        """Dijkstra over extension roads outward from the district, at most MAX_GAP_M
        between one signal and the next; each signal reached becomes a new start.
        For every junction reached, the (previous junction, edge) on its shortest road."""
        sources = set(district_nodes)
        via: dict[str, tuple[str, str]] = {}
        while True:
            dist = {j: 0.0 for j in sources}
            heap = [(0.0, j) for j in sources]
            heapq.heapify(heap)
            while heap:
                d, j = heapq.heappop(heap)
                if d > dist.get(j, 1e18):
                    continue
                for other, length, e in links[j]:
                    if e in ext and d + length <= MAX_GAP_M and d + length < dist.get(other, 1e18):
                        dist[other] = d + length
                        via[other] = (j, e)
                        heapq.heappush(heap, (d + length, other))
            found = {j for j in dist if j in outer} - sources
            if not found:
                return via
            sources |= found

    useful: set[str] = set()
    # a signal needs a road in from the district and a road back out, each the shortest
    for links in (out_of, into):
        via = reach(links)
        for j in list(via):
            if j not in outer:
                continue
            useful.update(e for _, _, e in out_of[j] if e in ext)  # every road meeting the signal
            useful.update(e for _, _, e in into[j] if e in ext)
            while j in via:
                j, e = via[j]
                useful.add(e)

    # A busy road that carries signals is kept from signal to signal (Karl Marx Road
    # runs along the district's north edge, through seven of them), whatever the
    # junction each sits at: the stretch between two signals at most MAX_GAP_M apart.
    signals = {j for j in set(out_of) | set(into) if is_signal(j)}
    # A street with SIGNALISED_STREET_MIN signals on it is a signalised arterial: along it
    # the gap between two signals may be as long as ARTERIAL_GAP_M, not MAX_GAP_M.
    on_street: dict[str, set[str]] = defaultdict(set)
    for j in signals:
        for e in [e for _, _, e in out_of[j] if e in ext] + [e for _, _, e in into[j] if e in ext]:
            if (names or {}).get(e):
                on_street[names[e]].add(j)  # type: ignore[index]
    arterials = {n for n, js in on_street.items() if len(js) >= SIGNALISED_STREET_MIN}

    def gap(e: str) -> float:
        return ARTERIAL_GAP_M if (names or {}).get(e) in arterials else MAX_GAP_M

    for links in (out_of, into):
        for start in sorted(signals):
            dist = {start: 0.0}
            via: dict[str, tuple[str, str]] = {}
            heap = [(0.0, start)]
            while heap:
                d, j = heapq.heappop(heap)
                if d > dist.get(j, 1e18):
                    continue
                for other, length, e in links[j]:
                    if e in ext and d + length <= gap(e) and d + length < dist.get(other, 1e18):
                        dist[other] = d + length
                        via[other] = (j, e)
                        heapq.heappush(heap, (d + length, other))
            for j in dist:
                if j != start and j in signals:
                    while j in via:
                        j, e = via[j]
                        useful.add(e)

    keep = [e for e in core if e not in ext or e in useful]
    # pruning can strand a one-way ramp: keep the largest set that still reaches itself
    while True:
        sub = graph.without_edges(set(graph.edges) - set(keep))
        scc = strongly_connected_core(sub)
        if len(scc) == len(keep):
            return sorted(keep)
        keep = scc


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
    ap.add_argument("--extension", help="file of the OSM way ids that are the district's extension")
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
    if args.extension and Path(args.extension).exists():
        before = len(core)
        tls = sorted(set(tls) | outer_crossings(graph, core, set(Path(args.extension).read_text().split())))
        names = {e.get("id"): e.get("name") or "" for e in ET.parse(net).getroot().findall("edge")}
        core = prune_extension(graph, core, tls, set(Path(args.extension).read_text().split()), names)
        left = {j for e in core for j in (graph.edges[e].from_junction, graph.edges[e].to_junction)}
        tls = [t for t in tls if t in left]  # a crossing whose roads were dropped is gone
        print(f"extension pruned: {before - len(core)} roads that reach no signal dropped")
    Path(args.keep_edges).write_text("\n".join(core) + "\n")
    Path(args.tls_ids).write_text(",".join(tls) + "\n")
    print(f"{len(core)}/{len(graph.edges)} edges in the connected core, {len(tls)} signalised crossings")


if __name__ == "__main__":
    main()
