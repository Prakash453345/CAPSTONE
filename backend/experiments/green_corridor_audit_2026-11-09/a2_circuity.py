import random, statistics
from audit_lib import *
from audit_lib import largest_scc, dist_m
from sim_service.routing import RoadGraph, RoutePlanner
from sim_service.routing.search import GraphSearchEngine
from itms_domain.scenario import current
g=RoadGraph.from_network(current().net); scc=largest_scc(g); pl=RoutePlanner(g); eng=GraphSearchEngine(g)
usable=sorted(e for e in scc if g.edges[e].length_m>=60 and g.neighbours(e))
rng=random.Random(7); pairs=[tuple(rng.sample(usable,2)) for _ in range(600)]
lenf=lambda _f,ge: g.edges[ge.to_edge].length_m
rows=[]
for a,b in pairs:
    d=dist_m(g,a,b)
    if d<300: continue
    r=pl.plan(a,b,{})[0]; L=sum(g.edges[e].length_m for e in r.edges)
    s=eng.shortest_path(a,b,lenf); 
    Ls=sum(g.edges[e].length_m for e in s.edges) if getattr(s,'edges',None) else None
    if Ls is None: continue
    rows.append((L/d, Ls/d, L/Ls))
q=lambda xs,p: sorted(xs)[int(len(xs)*p)]
print("n",len(rows))
print("planner circuity median/p95", round(q([r[0] for r in rows],.5),2), round(q([r[0] for r in rows],.95),2))
print("shortest-length circuity median/p95", round(q([r[1] for r in rows],.5),2), round(q([r[1] for r in rows],.95),2))
print("planner/shortest length ratio median/p95/max", round(q([r[2] for r in rows],.5),3), round(q([r[2] for r in rows],.95),3), round(max(r[2] for r in rows),3))
print("planner route == shortest-length route share", round(sum(1 for r in rows if abs(r[2]-1)<1e-6)/len(rows),3))
