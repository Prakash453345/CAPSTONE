import json,glob,statistics as st,math
rows=[];viol=0;tp=tr=0
for f in sorted(glob.glob('results/*.json')):
    d=json.load(open(f));R={}
    for r in d['records']: R.setdefault(r['arm'],{})[r['seed']]=r
    seeds=sorted(R['truth']);assert seeds==sorted(R['truth:rest']),f
    pc=[100*(R['truth:rest'][s]['person_delay_s']/R['truth'][s]['person_delay_s']-1) for s in seeds]
    m=st.fmean(pc);h=2.776*st.stdev(pc)/math.sqrt(len(pc))
    v=sum(R[a][s]['interlock_violations'] for a in R for s in seeds)
    a=sum(R['truth'][s]['teleports'] or 0 for s in seeds);b=sum(R['truth:rest'][s]['teleports'] or 0 for s in seeds)
    viol+=v;tp+=a;tr+=b
    sp=lambda x:st.fmean(R[x][s]['stops_per_vehicle'] for s in seeds)
    rows.append((f.split('/')[1][:-5],m,m-h,m+h,pc,a,b,sp('truth'),sp('truth:rest')))
    print(f"{rows[-1][0]:18s} {m:+6.1f}% [{m-h:+6.1f},{m+h:+6.1f}] better {sum(x<0 for x in pc)}/5 per-seed {[round(x,1) for x in pc]} tele {a}->{b} stops {sp('truth'):.2f}->{sp('truth:rest'):.2f}")
ms=[r[1] for r in rows];n=len(ms);m=st.fmean(ms);h=2.365*st.stdev(ms)/math.sqrt(n)
print(f"overall {m:+.1f}% [{m-h:+.1f},{m+h:+.1f}] over {n}")
print("M1 violations",viol,"| M2",m<=-2 and m+h<0,"| M3 worse-sig",[r[0] for r in rows if r[2]>0],"| M4 teleports",tp,"->",tr, tr<=tp+2)
