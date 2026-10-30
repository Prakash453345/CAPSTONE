import json,glob,statistics as st,math
from scipy.stats import t as T
L=['light','medium','heavy']; arms=['truth:c1.5:f20','truth:c2:f20','truth:c3:f20','truth:c10:f20','actuated']
print("vs current controller (1.25x ceiling), % person-delay, training seeds 101-103; teleports in ()")
print(f"{'net':22s}{'lvl':7s}"+"".join(f"{a.replace('truth:','').replace(':f20',''):>18s}" for a in arms))
allv={a:[] for a in arms}
for f in sorted(glob.glob('ceil_*.json')):
    d={}
    for r in json.load(open(f))['records']: d.setdefault(r['demand_level'],{}).setdefault(r['arm'],{})[r['seed']]=r
    net=f[5:-5]
    for l in L:
        if l not in d or 'truth' not in d[l]: continue
        o=d[l]['truth']; row=f"{net:22s}{l:7s}"
        for a in arms:
            b=d[l].get(a,{}); c=sorted(set(b)&set(o))
            if not c: row+=f"{'-':>18s}"; continue
            rel=[(b[s]['person_delay_s']/o[s]['person_delay_s']-1)*100 for s in c]; m=st.fmean(rel); allv[a].append(m)
            tp=sum(b[s]['teleports'] or 0 for s in c); row+=f"{m:+8.1f}% ({tp:4d})"[:18].rjust(18)
        row+=f"   ours tele {sum(o[s]['teleports'] or 0 for s in o)}"
        print(row)
print("\nmean over cells:", {a: round(st.fmean(v),1) for a,v in allv.items() if v}, "n cells", len(allv[arms[0]]))
