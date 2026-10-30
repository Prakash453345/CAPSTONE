"""Hexagon index over the road network (the H3 idea, in network metres).

The city is tiled with hexagons of `size_m` (centre to corner). Each cell
holds one aggregated number: the EV's seconds per metre through it, taken
from the last full sweep of live conditions. Uses:

1. **Search band.** A cheap Dijkstra over cells (a few hundred, vs
   thousands of edges) gives a corridor of cells from origin to
   destination; it is widened by `rings` cells, and the exact edge search
   runs only on edges inside it (`RoutePlanner.plan(allowed_edges=...)`).
2. **Cheap sampling.** Between full sweeps, live conditions are read only
   for edges in the band, so per-tick TraCI calls scale with the corridor,
   not the city.

Hexagons are used rather than squares because all six neighbours are the
same distance from the centre, so cell-path lengths have no diagonal bias.
Uber's H3 does the same on lat/lon; here the network is already in metres,
so a planar axial grid is enough and needs no extra library.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable, Mapping

from sim_service.routing.cost import EdgeConditions
from sim_service.routing.graph import RoadGraph

Cell = tuple[int, int]
_DIRS: tuple[Cell, ...] = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))
_SQRT3 = math.sqrt(3.0)


def cell_of(x: float, y: float, size: float) -> Cell:
    q = (_SQRT3 / 3.0 * x - y / 3.0) / size
    r = (2.0 / 3.0 * y) / size
    # cube rounding
    cx, cz = q, r
    cy = -cx - cz
    rx, ry, rz = round(cx), round(cy), round(cz)
    dx, dy, dz = abs(rx - cx), abs(ry - cy), abs(rz - cz)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy <= dz:
        rz = -rx - ry
    return (int(rx), int(rz))


def disk(c: Cell, k: int) -> set[Cell]:
    out = set()
    for dq in range(-k, k + 1):
        for dr in range(max(-k, -dq - k), min(k, -dq + k) + 1):
            out.add((c[0] + dq, c[1] + dr))
    return out


class HexIndex:
    def __init__(self, graph: RoadGraph, size_m: float | None = None):
        """`size_m` defaults to the median junction-to-junction distance
        (clamped to 150-600 m), so one cell is about one city block and a
        2-ring band reaches the parallel streets on either side."""
        self.graph = graph
        if size_m is None:
            ds = sorted(
                math.hypot(e.end_xy[0] - e.start_xy[0], e.end_xy[1] - e.start_xy[1])
                for e in graph.edges.values()
            )
            size_m = min(600.0, max(150.0, ds[len(ds) // 2] if ds else 175.0))
        self.size = size_m
        self.edge_cells: dict[str, tuple[Cell, ...]] = {}
        self.cell_edges: dict[Cell, set[str]] = {}
        step = size_m / 2.0
        for eid, e in graph.edges.items():
            (x0, y0), (x1, y1) = e.start_xy, e.end_xy
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step))
            cells: list[Cell] = []
            for i in range(n + 1):
                t = i / n
                c = cell_of(x0 + t * (x1 - x0), y0 + t * (y1 - y0), size_m)
                if not cells or cells[-1] != c:
                    cells.append(c)
            self.edge_cells[eid] = tuple(cells)
            for c in cells:
                self.cell_edges.setdefault(c, set()).add(eid)
        # directed cell graph: along each edge, and across each connection
        adj: dict[Cell, set[Cell]] = {}
        for cells in self.edge_cells.values():  # type: ignore[assignment]
            for a, b in zip(cells, cells[1:], strict=False):
                adj.setdefault(a, set()).add(b)
        for a, ges in graph.adjacency.items():  # type: ignore[assignment]
            if a not in self.edge_cells:
                continue
            ca = self.edge_cells[a][-1]  # type: ignore[index]
            for ge in ges:
                if ge.to_edge in self.edge_cells:
                    cb = self.edge_cells[ge.to_edge][0]
                    if cb != ca:
                        adj.setdefault(ca, set()).add(cb)
        self.adj = adj
        v_free = max((e.speed_limit_mps for e in graph.edges.values()), default=13.9)
        self._default_spm = 1.0 / v_free
        self.cell_spm: dict[Cell, float] = {}

    @property
    def n_cells(self) -> int:
        return len(self.cell_edges)

    def update_state(self, conditions: Mapping[str, EdgeConditions], speed_fn) -> None:
        """Full sweep: cell seconds-per-metre = length-weighted mean of
        1 / speed_fn(edge, cond) over the cell's edges."""
        acc: dict[Cell, list[float]] = {}
        for eid, cells in self.edge_cells.items():
            e = self.graph.edges[eid]
            cond = conditions.get(eid) or EdgeConditions()
            spm = 1.0 / max(0.5, speed_fn(e, cond))
            if cond.is_blocked:
                spm *= 10.0
            for c in cells:
                a = acc.setdefault(c, [0.0, 0.0])
                a[0] += spm * e.length_m
                a[1] += e.length_m
        self.cell_spm = {c: a[0] / a[1] for c, a in acc.items() if a[1] > 0}

    def band(
        self,
        source_edge: str,
        target_edge: str,
        rings: int = 1,
        avoid_edges: Iterable[str] = (),
    ) -> set[str] | None:
        """Edges in the widened cheapest cell corridor; None if the cell graph
        has no path (caller then searches the full graph). Cells holding an
        `avoid_edges` edge (live anomalies, newer than the last sweep) cost
        10x, so the corridor can bend around a fresh incident."""
        hot: set[Cell] = set()
        for e in avoid_edges:
            hot |= set(self.edge_cells.get(e, ()))
        if source_edge not in self.edge_cells or target_edge not in self.edge_cells:
            return None
        src = self.edge_cells[source_edge][-1]
        dst = self.edge_cells[target_edge][0]
        width = _SQRT3 * self.size
        best = {src: 0.0}
        prev: dict[Cell, Cell] = {}
        pq = [(0.0, src)]
        while pq:
            d, c = heapq.heappop(pq)
            if c == dst:
                break
            if d > best.get(c, math.inf):
                continue
            for n in self.adj.get(c, ()):
                spm = self.cell_spm
                w = width * 0.5 * (spm.get(c, self._default_spm) + spm.get(n, self._default_spm))
                if n in hot and n != dst:
                    w *= 10.0
                nd = d + w
                if nd < best.get(n, math.inf):
                    best[n] = nd
                    prev[n] = c
                    heapq.heappush(pq, (nd, n))
        if dst not in best:
            return None
        path = [dst]
        while path[-1] != src:
            path.append(prev[path[-1]])
        cells: set[Cell] = set()
        for c in path:
            cells |= disk(c, rings)
        cells |= set(self.edge_cells[source_edge]) | set(self.edge_cells[target_edge])
        return self.edges_in(cells)

    def edges_in(self, cells: Iterable[Cell]) -> set[str]:
        out: set[str] = set()
        for c in cells:
            out |= self.cell_edges.get(c, set())
        return out
