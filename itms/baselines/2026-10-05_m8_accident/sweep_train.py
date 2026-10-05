import json,sys,itertools,copy
sys.path.insert(0,'scripts')
import m8_accident_gate as A, m8_incident_gate as G
def filt(runs,f):
    out=[]
    for r in runs:
        r=dict(r); r['hits']=[h for h in r['hits'] if f(h[6])]; out.append(r)
    return out
def run(path,pol_kw,show=True):
    d=json.load(open(path)); on=[r for r in d['runs'] if r['inject']]; off=[r for r in d['runs'] if not r['inject']]
    return on,off
if __name__=='__main__':
    on,off=run(sys.argv[1],None)
    rows=[]
    for gap,dt,nb,v3,cs in itertools.product((0.5,1.0),(1,2,4,99),(0,1,2,99),(0,3,5),(10,20)):
        f=lambda fl:(fl['gap_m']<=gap and not fl['red'] and fl['dt_stop']<=dt and fl['nb']<=nb and fl['v3']>=v3)
        pol=dict(G.DEFAULT_POLICY,rules=['collision_cue'],collision_s=cs)
        a=G.summarise(filt(on,f),pol); b=G.summarise(filt(off,f),pol)
        rows.append((b['false_alarms_per_hour'],-(a['recall_in_view'] or 0),gap,dt,nb,v3,cs,a['recall_in_view'],a['mean_latency_s']))
    rows.sort()
    for r in rows[:14]: print('FA/h %.1f rec %.2f lat %s | gap %s dt %s nb %s v3 %s cs %s'%(r[0],r[7] or 0,r[8] and round(r[8]),r[2],r[3],r[4],r[5],r[6]))
    print('--- best recall with FA<=2:')
    ok=[r for r in rows if r[0]<=2.0]; ok.sort(key=lambda r:r[1])
    for r in ok[:5]: print('FA/h %.1f rec %.2f lat %s | gap %s dt %s nb %s v3 %s cs %s'%(r[0],r[7] or 0,r[8] and round(r[8]),r[2],r[3],r[4],r[5],r[6]))
