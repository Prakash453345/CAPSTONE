"""Round 2: reactive vs 260 m corridor vs queue-aware, held-out seeds 11-19."""
import json, glob, random, statistics
from audit_lib import RESULTS
random.seed(9)
R = {}
for f in glob.glob(str(RESULTS / "B_*_s*_*.json")):
    d = json.load(open(f))
    if d["seed"] <= 9 and d["arm"] in ("full", "q260", "la400"):
        R[(d["level"], d["seed"], d["arm"])] = d
def boot(xs, n=4000):
    if len(xs) < 2: return None
    ms = sorted(statistics.fmean(random.choices(xs, k=len(xs))) for _ in range(n))
    return round(statistics.fmean(xs), 1), round(ms[int(.025*n)], 1), round(ms[int(.975*n)], 1)
def pairs(lv, a, b, censor):
    xs = []
    for (l, s, arm), r in R.items():
        if l != lv or arm != a or (l, s, b) not in R: continue
        rb = R[(l, s, b)]
        eb = {e["rid"]: e for e in rb["evs"]}
        for e in r["evs"]:
            y = eb.get(e["rid"])
            if not y: continue
            def tt(e, rr):
                if "travel_s" in e: return e["travel_s"]
                return rr["end_s"] - e["spawn_t"] if censor and "spawn_t" in e else None
            tx, ty = tt(e, r), tt(y, rb)
            if tx is None or ty is None or ty <= 0: continue
            xs.append(100 * (tx - ty) / ty)
    return xs
for lv in ("light", "medium"):
    print("==", lv)
    for arm in ("full", "q260", "la400"):
        rs = [R[k] for k in R if k[0] == lv and k[2] == arm]
        evs = [e for r in rs for e in r["evs"]]
        done = [e["travel_s"] for e in evs if "travel_s" in e]
        print(f" {arm:9s} runs {len(rs)} done {len(done)}/{len(evs)} mean {statistics.fmean(done):.1f} sigstop {sum(e['stop_signal_s'] for e in evs):.0f} "
              f"maxred(mean of runs/max) {statistics.fmean(r['max_red_s'] for r in rs):.0f}/{max(r['max_red_s'] for r in rs)} "
              f"confl {sum(r['safety'].get('conflicting_green',0) for r in rs)} g2r {sum(r['safety'].get('green_to_red_no_yellow',0) for r in rs)} coll {sum(r['collisions'] for r in rs)} tele {sum(r['teleports'] for r in rs)}")
    for a, b in (("q260", "full"), ("la400", "full")):
        c, d = pairs(lv, a, b, False), pairs(lv, a, b, True)
        print(f"  {a} vs {b}: completed n={len(c)} {boot(c)} | censored n={len(d)} {boot(d)}")
