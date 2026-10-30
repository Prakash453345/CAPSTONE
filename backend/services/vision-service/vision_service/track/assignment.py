"""Optimal assignment (the Hungarian method) and IoU, vectorised in numpy.

ByteTrack's reference implementation uses the `lap` package (Jonker-Volgenant
in C). This is the classic O(n^3) shortest-augmenting-path Hungarian
algorithm with dual potentials, with its inner column scan vectorised, so it
stays fast at the tens-of-tracks scale one camera sees and adds no compiled
dependency. Exactness is pinned by a brute-force test.
"""

from __future__ import annotations

import numpy as np


def _hungarian_rows_le_cols(cost: np.ndarray) -> np.ndarray:
    """Min-cost assignment for `n <= m`. Returns `col_of_row` (length n)."""
    n, m = cost.shape
    inf = np.inf
    u = np.zeros(n + 1)
    v = np.zeros(m + 1)
    p = np.zeros(m + 1, dtype=np.int64)    # p[j]: row (1-based) assigned to column j
    way = np.zeros(m + 1, dtype=np.int64)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = np.full(m + 1, inf)
        used = np.zeros(m + 1, dtype=bool)
        while True:
            used[j0] = True
            i0 = p[j0]
            free = ~used[1:]
            cur = cost[i0 - 1] - u[i0] - v[1:]
            upd = free & (cur < minv[1:])
            minv[1:][upd] = cur[upd]
            way[1:][upd] = j0
            cand = np.where(free, minv[1:], inf)
            j1 = int(np.argmin(cand)) + 1
            delta = cand[j1 - 1]
            used_idx = np.nonzero(used)[0]
            u[p[used_idx]] += delta
            v[used_idx] -= delta
            minv[1:][free] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    col_of_row = np.full(n, -1, dtype=np.int64)
    for j in range(1, m + 1):
        if p[j] != 0:
            col_of_row[p[j] - 1] = j - 1
    return col_of_row


def linear_sum_assignment(cost: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Same contract as `scipy.optimize.linear_sum_assignment`: row and
    column index arrays of an optimal assignment of `min(n, m)` pairs."""
    c = np.asarray(cost, dtype=np.float64)
    if c.ndim != 2:
        raise ValueError("cost must be 2-D")
    n, m = c.shape
    if n == 0 or m == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    if not np.isfinite(c).all():
        big = np.nanmax(np.where(np.isfinite(c), np.abs(c), 0.0)) * 10 + 1e6
        c = np.where(np.isfinite(c), c, big)
    if n <= m:
        cols = _hungarian_rows_le_cols(c)
        rows = np.arange(n)
    else:
        rows_of_col = _hungarian_rows_le_cols(c.T)
        cols = np.arange(m)
        rows = rows_of_col
        order = np.argsort(rows)
        return rows[order], cols[order]
    return rows, cols


def _components(feasible: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """Connected components of the bipartite feasibility graph, as (rows,
    cols) index arrays. Rows or columns with no feasible partner are left out."""
    n, m = feasible.shape
    row_seen = np.zeros(n, dtype=bool)
    col_seen = np.zeros(m, dtype=bool)
    comps = []
    for start in range(n):
        if row_seen[start] or not feasible[start].any():
            continue
        rows, cols = {start}, set()
        frontier_r = [start]
        row_seen[start] = True
        while frontier_r:
            new_cols = set()
            for r in frontier_r:
                for c in np.nonzero(feasible[r] & ~col_seen)[0]:
                    col_seen[c] = True
                    new_cols.add(int(c))
            cols |= new_cols
            frontier_r = []
            for c in new_cols:
                for r in np.nonzero(feasible[:, c] & ~row_seen)[0]:
                    row_seen[r] = True
                    frontier_r.append(int(r))
                    rows.add(int(r))
        comps.append((np.array(sorted(rows)), np.array(sorted(cols))))
    return comps


def gated_assignment(
    cost: np.ndarray, threshold: float
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Optimal assignment over the pairs costing at most `threshold`, with
    every other pair infeasible -- the contract of `lap.lapjv(...,
    cost_limit=threshold)` that ByteTrack's `linear_assignment` relies on.
    Returns `(matches, unmatched_rows, unmatched_cols)`.

    Solved per connected component of the feasibility graph: in a camera
    frame most tracks overlap one or two detections at most, so this turns
    one 40x40 problem into forty 1x1s."""
    cost = np.asarray(cost, dtype=np.float64)
    n = cost.shape[0]
    m = cost.shape[1] if cost.ndim == 2 else 0
    if n == 0 or m == 0:
        return [], list(range(n)), list(range(m))
    feasible = cost <= threshold
    matches: list[tuple[int, int]] = []
    # Fast path: a row and a column that are each other's only feasible
    # partner are an isolated 1x1 component -- by far the common case.
    row_n = feasible.sum(axis=1)
    col_n = feasible.sum(axis=0)
    single = (row_n == 1)
    if single.any():
        cols_of = feasible.argmax(axis=1)
        solo = single & (col_n[cols_of] == 1)
        for i in np.nonzero(solo)[0]:
            matches.append((int(i), int(cols_of[i])))
        if solo.all() or not (row_n[~solo] > 0).any():
            mr = {i for i, _ in matches}
            mc = {j for _, j in matches}
            return (sorted(matches), [i for i in range(n) if i not in mr],
                    [j for j in range(m) if j not in mc])
        feasible = feasible.copy()
        feasible[solo] = False
        feasible[:, cols_of[solo]] = False
    penalty = threshold + 1.0 + float(np.abs(cost[np.isfinite(cost)]).max(initial=0.0))
    for rows, cols in _components(feasible):
        sub = np.where(feasible[np.ix_(rows, cols)], cost[np.ix_(rows, cols)], penalty)
        if sub.shape == (1, 1):
            matches.append((int(rows[0]), int(cols[0])))
            continue
        r, c = linear_sum_assignment(sub)
        for i, j in zip(r, c, strict=True):
            if sub[i, j] <= threshold:
                matches.append((int(rows[i]), int(cols[j])))
    mr = {i for i, _ in matches}
    mc = {j for _, j in matches}
    unmatched_rows = [i for i in range(n) if i not in mr]
    unmatched_cols = [j for j in range(m) if j not in mc]
    return sorted(matches), unmatched_rows, unmatched_cols


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU of `(N, 4)` and `(M, 4)` x1y1x2y2 boxes."""
    a = np.asarray(a, dtype=np.float64).reshape(-1, 4)
    b = np.asarray(b, dtype=np.float64).reshape(-1, 4)
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    ix1 = np.maximum(a[:, None, 0], b[None, :, 0])
    iy1 = np.maximum(a[:, None, 1], b[None, :, 1])
    ix2 = np.minimum(a[:, None, 2], b[None, :, 2])
    iy2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(ix2 - ix1, 0, None) * np.clip(iy2 - iy1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-12), 0.0)
