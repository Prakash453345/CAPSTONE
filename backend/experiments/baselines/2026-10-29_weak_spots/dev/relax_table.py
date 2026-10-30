import json,glob,statistics as st
L=['light','medium','heavy']
base={}
for f in glob.glob('ceil_*.json'):
    for r in json.load(open(f))['records']:
        base.setdefault((r['scenario'],r['demand_level'],r['arm']),{})[r['seed']]=r
agg={}
print("vs current controller, % person-delay (teleports)")
for f in sorted(glob.glob('relax_*.json')):
    d={}
    for r in json.load(open(f))['records']: d.setdefault((r['scenario'],r['demand_level']),{}).setdefault(r['arm'],{})[r['seed']]=r
    for k in sorted(d,key=lambda k:(k[0],L.index(k[1]))):
        o=base.get((k[0],k[1],'truth'),{}); a_=base.get((k[0],k[1],'actuated'),{}); row=[]
        for arm,b in sorted(d[k].items()):
            c=sorted(set(b)&set(o));
            if not c: continue
            m=st.fmean((b[s]['person_delay_s']/o[s]['person_delay_s']-1)*100 for s in c); agg.setdefault(arm,[]).append(m)
            row.append(f"{arm.replace('truth:s.ceiling_relax_factor=','R').replace(':s.ceiling_relax_below=','<').replace(':s.kappa_switch=','+k')} {m:+.1f}({sum(b[s]['teleports'] or 0 for s in c)})")
        if a_: am=st.fmean((a_[s]['person_delay_s']/o[s]['person_delay_s']-1)*100 for s in a_); row.append(f"actuated {am:+.1f}"); agg.setdefault('actuated',[]).append(am)
        print(f"{k[0]:20s}{k[1]:7s} ours-tele {sum(o[s]['teleports'] or 0 for s in o):4d} | "+" | ".join(row))
print("\nmean over cells:", {a: round(st.fmean(v),1) for a,v in agg.items()}, {a: len(v) for a,v in agg.items()})
