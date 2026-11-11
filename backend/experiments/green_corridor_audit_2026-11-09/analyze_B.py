import json, glob, random, statistics, collections
from audit_lib import RESULTS
random.seed(5)
R={}
for f in glob.glob(str(RESULTS/"B_*_s*_*.json")):
    d=json.load(open(f)); R[(d['level'],d['seed'],d['arm'])]=d
def boot(xs,n=4000):
    if not xs: return None
    ms=sorted(statistics.fmean(random.choices(xs,k=len(xs))) for _ in range(n))
    return round(statistics.fmean(xs),1), round(ms[int(.025*n)],1), round(ms[int(.975*n)],1)
out={}
lines=[]
for lv in ("light","medium","heavy"):
    row={}
    for arm in ("plain","route_only","full","retimed"):
        rs=[R[k] for k in R if k[0]==lv and k[2]==arm]
        evs=[e for r in rs for e in r['evs']]
        row[arm]={"runs":len(rs),"evs":len(evs),"completed":sum(1 for e in evs if 'travel_s' in e),
                  "dnf":sum(1 for e in evs if 'travel_s' not in e),
                  "mean_travel":round(statistics.fmean([e['travel_s'] for e in evs if 'travel_s' in e]),1) if evs else None,
                  "stop_signal_s_total":sum(e['stop_signal_s'] for e in evs),
                  "stop_other_s_total":sum(e['stop_other_s'] for e in evs),
                  "evs_stuck_gt300s_nonsignal":sum(1 for e in evs if e['stop_other_s']>300),
                  "collisions":sum(r['collisions'] for r in rs),"teleports":sum(r['teleports'] for r in rs),
                  "conflicting_green":sum(r['safety'].get('conflicting_green',0) for r in rs),
                  "green_to_red":sum(r['safety'].get('green_to_red_no_yellow',0) for r in rs),
                  "max_red_s_max":max((r['max_red_s'] for r in rs),default=None),
                  "corridors_left":sum(len(r['corridors_left']) for r in rs),
                  "tick_exc":sum(r['n_tick_exceptions'] for r in rs),
                  "reroutes_mean":round(statistics.fmean([e.get('reroutes',0) for e in evs]),2) if evs else None,
                  "armed_of_signal_trips":[sum(1 for e in evs if e.get('crossings0',0)>=1 and e.get('corridor_armed')),sum(1 for e in evs if e.get('crossings0',0)>=1)]}
    # paired comparisons
    def pairs(a,b,censor=False):
        xs=[]
        for (l,s,arm),r in R.items():
            if l!=lv or arm!=a: continue
            rb=R.get((l,s,b))
            if not rb: continue
            ea={e['rid']:e for e in r['evs']}; eb={e['rid']:e for e in rb['evs']}
            for rid,x in ea.items():
                y=eb.get(rid)
                if not y: continue
                def tt(e):
                    if 'travel_s' in e: return e['travel_s']
                    if censor and 'spawn_t' in e: return r['end_s']-e['spawn_t']
                    return None
                tx,ty=tt(x),tt(y)
                if tx is None or ty is None or ty<=0: continue
                xs.append(100*(tx-ty)/ty)
        return xs
    for a,b,name in (("full","plain","full_vs_plain"),("route_only","plain","route_vs_plain"),("full","route_only","full_vs_route")):
        row[name]={"both_completed":dict(zip(("n","mean","lo","hi"),[len(pairs(a,b))]+list(boot(pairs(a,b)) or []))),
                   "dnf_censored":dict(zip(("n","mean","lo","hi"),[len(pairs(a,b,True))]+list(boot(pairs(a,b,True)) or [])))}
    # stop_signal ratio
    sp=row['plain']['stop_signal_s_total']; sf=row['full']['stop_signal_s_total']
    row['stop_signal_full_over_plain']=round(sf/sp,2) if sp else None
    out[lv]=row
json.dump(out,open(RESULTS/"B_summary.json","w"),indent=1)
for lv,row in out.items():
    print("==",lv)
    for arm in ("plain","route_only","full","retimed"):
        r=row[arm]; print(f" {arm:10s} runs {r['runs']} ev {r['evs']} done {r['completed']} dnf {r['dnf']} mean_travel {r['mean_travel']} sigstop {r['stop_signal_s_total']} otherstop {r['stop_other_s_total']} stuck>300 {r['evs_stuck_gt300s_nonsignal']} coll {r['collisions']} tele {r['teleports']} confl {r['conflicting_green']} g2r {r['green_to_red']} maxred {r['max_red_s_max']} reroutes/ev {r['reroutes_mean']} armed {r['armed_of_signal_trips']} left {r['corridors_left']} exc {r['tick_exc']}")
    for k in ("full_vs_plain","route_vs_plain","full_vs_route"): print(f"  {k}: completed-pairs {row[k]['both_completed']} | dnf-censored {row[k]['dnf_censored']}")
    print("  stop-at-signal full/plain:", row['stop_signal_full_over_plain'])
