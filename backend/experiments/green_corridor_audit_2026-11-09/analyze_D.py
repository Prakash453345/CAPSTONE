import json, glob, statistics, collections
from audit_lib import RESULTS
def load(pat):
    out=[]
    for f in sorted(glob.glob(str(RESULTS/pat))):
        out.append((f.split('/')[-1][:-5], json.load(open(f))))
    return out
print("=== D reroute ===")
rows=collections.defaultdict(list)
for name,d in load("D_*.json"):
    _,lv,s,v=name.split('_'); rows[(lv,v)].append(d)
for lv in ("light","medium","heavy"):
    for v in ("none","ahead2","ahead3","ahead4","ahead5","cutoff","flap"):
        rs=rows.get((lv,v),[])
        if not rs: continue
        ev=[r['evs'][0] for r in rs if r['evs']]
        D=[r['D'] for r in rs]
        left=[x['time_to_leave_blocked_s'] for x in D if x.get('time_to_leave_blocked_s') is not None]
        alt=[x for x in D if x.get('alt_exists')]
        print(f"{lv:6s} {v:7s} n={len(rs)} done={sum(1 for e in ev if e.get('final_state')=='completed')}/{len(ev)} travel_mean={round(statistics.fmean([e['travel_s'] for e in ev if 'travel_s' in e]),0) if any('travel_s' in e for e in ev) else None} "
              f"reroutes_mean={round(statistics.fmean([e.get('reroutes',0) for e in ev]),1)} left_blocked_s={left} alt_exists={len(alt)}/{len(D)} "
              f"entered_blocked={[x['entered_blocked'] for x in D]} armed_after={[x.get('armed_after') for x in D if x.get('alt_exists')]} flap_events={[x['flap_events'] for x in D if v=='flap']} "
              f"teleports={[r['teleports'] for r in rs]} exc={sum(r['n_tick_exceptions'] for r in rs)} "
              f"warn={sorted({k[:60] for r in rs for k in r['warnings'] if 'no phase' not in k})}")
print("=== E1 crossing EVs ===")
for name,d in load("E1_*.json"):
    ev={e['rid']:e for e in d['evs']}
    n=len(d['trials']); ok=sum(1 for t in d['trials'] if ev[t['A']].get('final_state')=='completed' and ev[t['B']].get('final_state')=='completed')
    print(name,"trials",n,"both_completed",ok,"safety",d['safety'],"coll",d['collisions'],"tele",d['teleports'],"exc",d['n_tick_exceptions'],"left",d['corridors_left'])
print("=== E2 concurrent ===")
for name,d in load("E2_*.json"):
    ev={e['rid']:e for e in d['evs']}
    s=[]
    for w in d['waves']:
        es=[ev[i] for i in w['ids'] if i in ev]
        s.append((w['n'],sum(1 for e in es if e.get('state_after_create')!='cancelled'),sum(1 for e in es if e.get('final_state')=='completed'),[e['rid'] for e in es if e.get('final_state') not in('completed','cancelled')]))
    print(name,"waves(n,routed,completed,stuck)",s,"safety",d['safety'],"coll",d['collisions'],"tele",d['teleports'],"exc",d['n_tick_exceptions'],"left",d['corridors_left'],"peak",d['corridor_peak'])
print("=== E3 command races ===")
for name,d in load("E3_*.json"):
    print(name,"two_live_trip_ticks",d['inv']['two_live_trips'],"exc",d['tick_exceptions'][:3],"left",d['corridors_left'],"safety",d['safety'])
