import json, random
from collections import defaultdict
from audit_lib import largest_scc, RESULTS, dump
from sim_service.live.corridor import load_corridor
from sim_service.live.green_corridor import CorridorController
from sim_service.routing import RoadGraph, RoutePlanner
from itms_domain.scenario import current
g=RoadGraph.from_network(current().net); cfgs=load_corridor("light").configs
cc=CorridorController(g); pl=RoutePlanner(g); scc=largest_scc(g)
ps=CorridorController._phase_serving
def ok(c):
    cfg=cfgs.get(c.tl_id); 
    return cfg is not None and ps(cfg, frozenset(c.movements), prefer="") is not None
# classify unpreemptable moves
uturn=other=0; tot_u=tot_o=0
for e in g.edges:
    for n in g.neighbours(e):
        if not (n.signalised and n.tl_id): continue
        isU = (e.lstrip('-')==n.to_edge.lstrip('-') and e!=n.to_edge)
        wanted=frozenset(g.movements_for(n.tl_id,e,n.to_edge)); cfg=cfgs[n.tl_id]
        bad = not wanted or ps(cfg,wanted,prefer="") is None
        if isU: tot_u+=1; uturn+=bad
        else: tot_o+=1; other+=bad
print("U-turn moves unpreemptable",uturn,"/",tot_u,"; non-U-turn",other,"/",tot_o)
rng=random.Random(7); usable=sorted(e for e in scc if g.edges[e].length_m>=60 and g.neighbours(e))
n=0;rt_sig=0;rt_bad=0;cr=0;cr_bad=0;per_tl=defaultdict(lambda:[0,0])
for _ in range(1500):
    a,b=rng.sample(usable,2)
    r=pl.plan(a,b,{})[0]; cs=cc.planner.crossings(tuple(r.edges))
    n+=1
    if not cs: continue
    rt_sig+=1; bads=[c for c in cs if not ok(c)]
    rt_bad+= 1 if bads else 0
    cr+=len(cs); cr_bad+=len(bads)
    for c in cs: per_tl[c.tl_id][0]+=1; per_tl[c.tl_id][1]+= (0 if ok(c) else 1)
out={"routes":n,"routes_with_signal":rt_sig,"routes_with_>=1_unpreemptable_crossing":rt_bad,
     "crossings":cr,"crossings_unpreemptable":cr_bad,
     "uturn_unpreemptable":[uturn,tot_u],"nonuturn_unpreemptable":[other,tot_o],
     "worst_signals":sorted(((t,v[1],v[0]) for t,v in per_tl.items()), key=lambda x:-x[1]/max(x[2],1))[:8]}
dump(out,RESULTS/"G2_route_coverage.json"); print(json.dumps(out,indent=0))
