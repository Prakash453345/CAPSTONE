"""usage: python audit_run.py <test> [args]
  A                         static map/routing sanity (no SUMO)
  B <level> <seed> <arm>    4 sequential EVs, one arm
"""
from __future__ import annotations

import random
import sys
import time

from audit_lib import *  # noqa: F401,F403
from audit_lib import RESULTS, World, dist_m, dump, largest_scc, sample_pairs  # noqa: E402

T0, GAP = 500.0, 300.0


def test_A() -> dict:
    from sim_service.live.green_corridor import GreenCorridorPlanner
    from sim_service.routing import RoadGraph, RoutePlanner
    from itms_domain.scenario import current
    g = RoadGraph.from_network(current().net)
    scc = largest_scc(g)
    pl = RoutePlanner(g)
    cp = GreenCorridorPlanner(g)
    out = {"edges": len(g.edges), "scc": len(scc),
           "outside_scc": sorted(set(g.edges) - scc)}
    rng = random.Random(7)
    usable = sorted(e for e in scc if g.edges[e].length_m >= 60 and g.neighbours(e))
    pairs = [tuple(rng.sample(usable, 2)) for _ in range(600)]
    fails, loops, discon, circ, nsig = 0, 0, 0, [], []
    for a, b in pairs:
        try:
            r = pl.plan(a, b, {})[0]
        except Exception as e:  # noqa: BLE001
            fails += 1
            continue
        es = list(r.edges)
        if len(set(es)) != len(es):
            loops += 1
        for x, y in zip(es, es[1:]):
            if y not in {n.to_edge for n in g.neighbours(x)}:
                discon += 1
                break
        L = sum(g.edges[e].length_m for e in es)
        d = max(dist_m(g, a, b), 1.0)
        if d > 300:
            circ.append(L / d)
        nsig.append(len(cp.crossings(tuple(es))))
    circ.sort()
    out.update(pairs=len(pairs), unroutable=fails, loops=loops, disconnected=discon,
               circuity_median=circ[len(circ) // 2], circuity_p95=circ[int(len(circ) * .95)],
               circuity_max=circ[-1], signals_per_route_mean=sum(nsig) / len(nsig),
               routes_with_no_signal=sum(1 for n in nsig if n == 0))
    # all edge pairs inside SCC are routable by definition of SCC; verify a dense random sample vs search
    return out


def test_B(level: str, seed: int, arm: str) -> dict:
    w = World(level, seed, arm, end_s=T0 + 4 * GAP + 250)
    scc = largest_scc(w.graph)
    pairs = sample_pairs(w.graph, scc, random.Random(1000 + seed), 4)
    for i, (a, b, d, k) in enumerate(pairs):
        w.at(T0 + i * GAP, "dispatch", rid=f"ev{i}", vid=f"EV{i}", src=a, dst=b, tag=f"d{d}_s{k}")
    t = time.time()
    res = w.run()
    res["wall_s"] = round(time.time() - t, 1)
    res["pairs"] = pairs
    return res


if __name__ == "__main__":
    test = sys.argv[1]
    if test == "A":
        dump(test_A(), RESULTS / "A_static.json")
        print("A done")
    elif test == "B":
        level, seed, arm = sys.argv[2], int(sys.argv[3]), sys.argv[4]
        r = test_B(level, seed, arm)
        dump(r, RESULTS / f"B_{level}_s{seed}_{arm}.json")
        print(f"B {level} s{seed} {arm}: wall {r['wall_s']}s; "
              + " ".join(f"{e['rid']}:{e.get('travel_s','DNF')}" for e in r['evs'])
              + f" safety={r['safety']} coll={r['collisions']} exc={r['n_tick_exceptions']}")
