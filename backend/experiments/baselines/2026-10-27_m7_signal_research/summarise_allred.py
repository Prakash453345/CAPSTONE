import json,glob,statistics as st,os
def load(f):
    return {(r['demand_level'],r['seed']):(r['person_delay_s'],r['stops_per_vehicle'],r['interlock_violations'],r['teleports']) for r in json.load(open(f))['records']}
allp={'light':[],'medium':[]}
print("| network | level | change in person-delay (mean) | per seed | n | teleports fixed→ITE |")
print("|---|---|---|---|---|---|")
for fx in sorted(glob.glob('baselines/2026-10-27_m7_signal_research/results/*_fixed.json')):
    net=os.path.basename(fx)[:-11]; it=fx.replace('_fixed','_ite')
    if not os.path.exists(it): continue
    a,b=load(fx),load(it)
    for lv in ('light','medium'):
        ks=sorted(k for k in a if k[0]==lv and k in b)
        if not ks: continue
        pct=[100*(b[k][0]-a[k][0])/a[k][0] for k in ks]; allp[lv].append(st.fmean(pct))
        print(f"| {net} | {lv} | {st.fmean(pct):+.1f} % | {', '.join(f'{p:+.1f}' for p in pct)} | {len(ks)} | {sum(a[k][3] for k in ks)}→{sum(b[k][3] for k in ks)} |")
for lv,v in allp.items():
    if v: print(lv,'mean of network means',round(st.fmean(v),1),'networks',len(v))
