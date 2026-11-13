"""Summarise m7_corridor_why.py runs: stop causes and claim timing per arm.
usage: python m7_corridor_why_summary.py <dir with <arm>_<seed>.json>"""
import collections
import glob
import json
import statistics as st
import sys

d = sys.argv[1]
runs = collections.defaultdict(dict)
for f in glob.glob(f"{d}/*_*.json"):
    r = json.load(open(f))
    runs[r["arm"]][r["seed"]] = r
seeds = sorted(set.intersection(*(set(v) for v in runs.values())))
print(f"seeds {seeds[0]}-{seeds[-1]} (n={len(seeds)})\n")


def cause(s):
    if s["tls"] is None or (s["dist"] or 0) > 60:
        return "mid-block (no signal within 60 m)"
    if s["light"] in "Gg":
        return "green, queued behind cars"
    if not s.get("tracked", True):
        return "red, EV no longer tracked"
    if s.get("reserved_for_ev"):
        return ("red, claimed but switch not finished" if s["jp_state"] != "dwell"
                else "red, claimed and in dwell")
    return "red, not claimed"


print("| arm | EV time s (4 EVs) | time lost | stops | waiting s |")
print("|---|---|---|---|---|")
for arm in sorted(runs):
    xs = [runs[arm][s]["summary"] for s in seeds]
    print(f"| {arm} | {st.fmean(x['ev_duration_s'] for x in xs):.0f} | "
          f"{st.fmean(x['ev_time_loss_s'] for x in xs):.0f} | "
          f"{st.fmean(x['ev_stops'] for x in xs):.1f} | "
          f"{st.fmean(x['ev_waiting_time_s'] for x in xs):.0f} |")
if {"reactive", "corridor"} <= set(runs):
    diff = [runs["corridor"][s]["summary"]["ev_duration_s"] - runs["reactive"][s]["summary"]["ev_duration_s"]
            for s in seeds]
    dstop = [runs["corridor"][s]["summary"]["ev_stops"] - runs["reactive"][s]["summary"]["ev_stops"]
             for s in seeds]
    print(f"\ncorridor - reactive per seed: EV time {diff} (mean {st.fmean(diff):+.1f} s); "
          f"stops {dstop} (mean {st.fmean(dstop):+.2f})")

print("\nStops by cause (count / total seconds stopped, summed over seeds):")
cats = sorted({cause(s) for a in runs for sd in seeds for s in runs[a][sd]["stops"]})
print("| cause | " + " | ".join(sorted(runs)) + " |")
print("|---|" + "---|" * len(runs))
for c in cats:
    row = []
    for arm in sorted(runs):
        ss = [s for sd in seeds for s in runs[arm][sd]["stops"] if cause(s) == c]
        row.append(f"{len(ss)} / {sum(s['dur'] or 0 for s in ss):.0f} s")
    print(f"| {c} | " + " | ".join(row) + " |")

print("\nWhere the green-but-queued stops are (junction: count, seconds), all arms:")
w = collections.Counter()
ws = collections.Counter()
for arm in runs:
    for sd in seeds:
        for s in runs[arm][sd]["stops"]:
            if cause(s) == "green, queued behind cars":
                w[(arm, s["tls"])] += 1
                ws[(arm, s["tls"])] += s["dur"] or 0
for k, n in w.most_common(8):
    print(f"  {k[0]:9s} {k[1]}: {n} stops, {ws[k]:.0f} s")

print("\nClaims (first claim per EV and junction):")
for arm in sorted(runs):
    cl = [c for sd in seeds for c in runs[arm][sd]["claims"]]
    if not cl:
        continue
    dist = [c["dist_at_grant"] for c in cl if c["dist_at_grant"] is not None]
    lead = [c["crossed_s"] - c["granted_s"] for c in cl if c["crossed_s"] is not None]
    reached = [any(s == "dwell" for _, s in c["states"]) for c in cl]
    rel = collections.Counter()
    for c in cl:
        rel.update(c.get("release_counts") or {})
    print(f"  {arm}: {len(cl)} claims; distance at claim median {st.median(dist):.0f} m "
          f"(p10 {sorted(dist)[len(dist) // 10]:.0f}, p90 {sorted(dist)[9 * len(dist) // 10]:.0f}); "
          f"claim-to-crossing median {st.median(lead):.0f} s; reached dwell {sum(reached)}/{len(cl)}; "
          f"re-claimed {sum(c['n'] > 1 for c in cl)}")
    stats = collections.Counter()
    for sd in seeds:
        stats.update({k: v for k, v in (runs[arm][sd]["corridor_stats"] or {}).items()
                      if k.startswith(("release_", "defer_")) and v})
    print(f"    releases/defers: {dict(stats)}")
