"""Does a trained combiner of traffic context and the vision rules find
injected incidents better than the vision rules alone? (M8 + M6)

The vision incident rules (`vision_service/incidents/rules.py`) judge each
camera's scene on its own: a vehicle stopped mid-block, a lane stuck on green.
At their shipped operating point (`quiet`) they catch about one in five
in-view incidents at under two false alarms an hour
(`baselines/2026-09-25_m8_review`, Gate 4). This asks whether three additions
do better, all scored on the same injected incidents:

1. **What is normal here.** Every traffic feature is also expressed as a
   z-score against the same link's own normal behaviour -- the same demand
   level, the same 10-minute slot of the run, from incident-free runs of the
   TRAINING seeds. (A deployment would use the same weekday and time from
   past weeks; the demand level plays the part of the day type.)
2. **Upstream / downstream contrast.** An incident looks different from a
   red-light queue: the lane stays stopped while it has green, its sibling
   lanes on the same green keep moving, the road it feeds stays empty, and
   its queue never clears over a whole cycle. These are computed as
   features.
3. **A trained combiner.** An L2 logistic regression turns the features into
   one probability per link per second; a candidate is raised when it stays
   above a threshold for `K` seconds, with the rules' own clear (20 s) and
   cooldown (120 s) semantics.

Traffic features come in two flavours, reported as separate arms because
only one of them exists on the real corridor:

* `lane` -- M6's per-link features straight from SUMO (whole-lane halting,
  mean speed, queue): perfect lane sensors, what M6 was designed on.
* `cam`  -- what M8's cameras report per link each second (queue,
  approaching, receiving occupancy, their confidence): what a camera-only
  deployment has.

Arms: `A_quiet` (the rules at `quiet`), `A_hand` (the hand-set rules),
`A_rules@b` (the rules re-tuned on these TRAIN runs at budget b, same search
as `m8_incident_analysis.py` but with the strict false-alarm count below),
`C_lane`, `C_lane_noz` (no normal baseline), `C_cam`, `D_vis` (the rule
evidence alone, learned), `E_lane` and `E_cam` (traffic + vision).

Honesty: everything -- the baselines, the models, thresholds, persistence --
is fitted on TRAIN seeds (101+); thresholds and persistence are picked on
out-of-fold predictions (leave one seed out); EVAL seeds (1+) are scored
once. The bar below was fixed before any result existed.

Scoring (stricter than the gate's). A candidate *detects* an incident if it
lands on one of the incident's links between its start and 45 s after it
ends. Every other candidate is a **false alarm**, wherever it is -- a second
candidate on the same incident is ignored, not counted either way. (The
gate's own count, "lenient", also forgives any candidate raised anywhere
while some incident is on; it is reported too, for comparison with Gate 4.)
False alarms per hour are over every run, incident and incident-free twin.
Precision and F1 are over the incident runs only, whose density (six
incidents in 40-50 minutes) is far above a real corridor's, so a real
deployment's precision at the same false alarms per hour would be lower.

Bar (set before the runs): `E_cam` -- the deployable one -- becomes the
incident stream's candidate if, on EVAL, at the point TRAIN chose for
1 false alarm/h, (a) it detects a larger share of in-view incidents than
`A_rules@1` with a cluster-bootstrap 95 % interval of the difference above
zero (clusters: seed x level), and (b) its EVAL false alarms stay at or
below 2 per hour.

**Version 2.** Version 1 (`--v1`, EVAL seeds 1-5) failed that bar on (b):
3.1 false alarms/h held out against 0.5 on TRAIN. Reading where they came
from (EVAL diagnostics, so everything below is post hoc) found two faults
of the *counting*, not the model: links that share an approach lane raised
one alarm each for one event (three alarms for a three-link lane), where
the rules raise one per lane, rule and track; and alarms in the first minutes of a run,
while the network fills from empty -- a phase a real corridor never has,
and in which no incident is ever scheduled. Version 2 raises **one
candidate per approach lane** (its links' highest score) and raises
**nothing in the first 300 s** for every arm, the rules included. It also
adds what the tracker reports on each approach lane (`cam2`: tracks in
view, stopped, moving), because version 1's camera arm had no speed signal
while the lane-sensor arm's strongest features were speed-based. Having
looked at EVAL seeds 1-5, version 2 is judged on **fresh EVAL seeds 6-10**,
recorded after these changes were fixed, with the same bar applied to
`E_cam2` (camera-only: camera traffic + tracker + rule evidence).

**An artefact found afterwards.** SUMO reports an *empty* lane's mean speed as
the lane's current limit, and the injector blocks a lane by setting that
limit to 0.1 m/s -- so the lane-sensor features saw an empty blocked lane
"crawl". `--empty-lane-free` reads a lane with nothing halted, queued or
approaching as free-flowing; the lane arms were re-run with it (post hoc;
off by default so the recorded results reproduce). The artefact does not
arise for stalls, and the camera arms do not read these features.

    python scripts/m8_incident_fusion.py data/m8_fusion/train_v2.json \\
        data/m8_fusion/eval_v2.json --eval-seeds 6,7,8,9,10 --out fusion_v2.json
    python scripts/m8_incident_fusion.py data/m8_fusion/train.json data/m8_fusion/eval.json \\
        --v1 --out fusion_v1.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics as st
import sys
import time
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m5_harness as H  # noqa: E402
import m8_incident_analysis as A  # noqa: E402
from m8_incident_gate import (  # noqa: E402
    CLEAR_S,
    COOLDOWN_S,
    DEFAULT_POLICY,
    LATENCY_GRACE_S,
    MAX_STEPS,
    candidates_under,
)
from sim_service.control.anomaly.graph_features import FEATURE_NAMES, AnomalyGraph  # noqa: E402

# `quiet` (vision_service.incidents.rules.OPERATING_POINTS) in the gate's policy terms:
# raise_persist_s 4 s == persist_ticks 5 (the replay counts from the first tick)
QUIET_POLICY = {**DEFAULT_POLICY, "midblock_s": 45.0, "midblock_dwell_s": 60.0,
                "midblock_impact_s": 20.0, "persist_ticks": 5, "rules": ["midblock_stop"]}

BIN_S = 600          # the normal baseline's time slot
NEG_RATE = 0.03      # share of negative (link, second) rows kept to train on, re-weighted
L2 = 1e-3            # ridge on standardised coefficients; fixed, not tuned
# persistence (s) and the rules' search grid were widened after a TRAIN-only
# dry run chose values at the old grids' edge (K 20-30); EVAL was not looked at
K_GRID = (1, 5, 10, 20, 30, 45, 60)
RULE_GRIDS = {
    "stuck_on_green": {"stuck_sibling_s": [10.0, 15.0, 20.0, 30.0, 45.0, 60.0],
                       "stuck_alone_s": [30.0, 45.0, 60.0, 90.0, 120.0, 1e9]},
    "midblock_stop": {"midblock_s": [15.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0],
                      "midblock_dwell_s": [60.0, 90.0, 120.0, 180.0],
                      "midblock_impact_s": [10.0, 15.0, 20.0, 30.0, 45.0, 60.0]},
    "flow_void": {"void_s": [60.0, 90.0, 120.0, 180.0], "void_min_swerves": [0, 2, 3, 5],
                  "void_min_share": [0.0, 0.2, 0.3, 0.5],
                  "void_min_from_stop_line_m": [0.0, 30.0, 60.0]},
    "collision_cue": {"collision_s": [5.0, 10.0, 20.0, 30.0]},
    "wrong_way": {"wrong_way_s": [3.0, 5.0]},
}
RULE_PERSIST = [1, 3, 5, 10, 20]
N_THETA = 40
BUDGETS = (1.0, 5.0)
BAR_BUDGET, BAR_MAX_EVAL_FA = 1.0, 2.0
N_BOOT = 10000
# version 2 (see the docstring); --v1 restores version 1's counting
WARMUP_S = 300.0      # no candidate from any arm before this far into a run
LANE_CANDIDATES = True  # one candidate per approach lane, not per link
# found by the fact-check after version 2: see base_features. Off by default so
# that the recorded version 1 and 2 results reproduce; --empty-lane-free turns it on
EMPTY_LANE_FREE = False

LANE = ("queue", "halting", "slowness", "recv_occupancy", "approaching", "recv_queue",
        "halting_min90", "never_free90", "green_stuck30", "green_still60", "down_empty30",
        "sibling_gap30", "halting_mean180", "queue_mean180")
CAM = ("cam_queue", "cam_approaching", "cam_recv_occupancy", "cam_recv_queue",
       "cam_confidence", "cam_seen", "cam_queue_min90", "cam_green_queue30",
       "cam_down_empty30", "cam_sibling_gap30", "cam_queue_mean180", "cam_queue_rise30")
CAM_Z = tuple(c for c in CAM if c not in ("cam_confidence", "cam_seen"))
CAM2 = ("trk_tracks", "trk_stopped", "trk_moving", "trk_stopped_share", "trk_green_stopped30",
        "trk_green_nomove60", "trk_stopped_min90", "trk_sibling_stopped_gap30",
        "trk_moving_mean60")
VIS = ("stuck_sibling", "stuck_alone", "midblock", "midblock_impact", "midblock_dwell",
       "void", "void_strong", "collision", "wrong_way", "vision_score")
CTX = ("green", "phase_age")

# which feature blocks each learned arm sees, and whether an incident no camera
# could see is a positive to learn from (lane sensors see it; cameras cannot)
ARMS: dict[str, dict] = {
    "C_lane": {"blocks": ("ctx", "lane", "lane_z"), "uncovered": True},
    "C_lane_noz": {"blocks": ("ctx", "lane"), "uncovered": True},
    "C_cam": {"blocks": ("ctx", "cam", "cam_z"), "uncovered": False},
    "D_vis": {"blocks": ("ctx", "vis"), "uncovered": False},
    "E_lane": {"blocks": ("ctx", "lane", "lane_z", "vis"), "uncovered": True},
    "E_cam": {"blocks": ("ctx", "cam", "cam_z", "vis"), "uncovered": False},
    "C_cam2": {"blocks": ("ctx", "cam", "cam_z", "cam2", "cam2_z"), "uncovered": False},
    "E_cam2": {"blocks": ("ctx", "cam", "cam_z", "cam2", "cam2_z", "vis"), "uncovered": False},
}
BLOCK_NAMES = {"ctx": CTX, "lane": LANE, "lane_z": tuple(f"z_{n}" for n in LANE),
               "cam": CAM, "cam_z": tuple(f"z_{n}" for n in CAM_Z), "vis": VIS,
               "cam2": CAM2, "cam2_z": tuple(f"z_{n}" for n in CAM2)}
V1_ARMS = ("C_lane", "C_lane_noz", "C_cam", "D_vis", "E_lane", "E_cam")


# ---- rolling helpers (causal: row t sees rows <= t only) ----------------------------------

def roll_mean(a: np.ndarray, w: int) -> np.ndarray:
    c = np.cumsum(a, axis=0, dtype=np.float64)
    out = c.copy()
    out[w:] = c[w:] - c[:-w]
    n = np.minimum(np.arange(1, len(a) + 1), w).reshape((-1,) + (1,) * (a.ndim - 1))
    return (out / n).astype(np.float32)


def roll_ext(a: np.ndarray, w: int, fn) -> np.ndarray:
    pad = np.inf if fn is np.min else -np.inf
    p = np.concatenate([np.full((w - 1,) + a.shape[1:], pad, dtype=a.dtype), a])
    return fn(np.lib.stride_tricks.sliding_window_view(p, w, axis=0), axis=-1)


def lag(a: np.ndarray, k: int) -> np.ndarray:
    out = np.empty_like(a)
    out[k:] = a[:-k]
    out[:k] = a[:1]
    return out


# ---- the graph ---------------------------------------------------------------------------

class Topo:
    def __init__(self) -> None:
        g = AnomalyGraph.from_network(H.NET_PATH)
        self.node_ids = list(g.node_ids)
        self.index = {n: i for i, n in enumerate(self.node_ids)}
        tls = np.array(g.tls_of)
        lane = np.array(g.approach_lane_of)
        # siblings: same junction, a different approach lane
        self.sib = ((tls[:, None] == tls[None, :]) & (lane[:, None] != lane[None, :])).astype(
            np.float32)
        groups: dict[str, list[int]] = {}
        for i, ln in enumerate(lane):
            groups.setdefault(str(ln), []).append(i)
        self.lane_groups = list(groups.values())

    def nodes_of(self, tls: str, links) -> list[int]:
        return [self.index[f"{tls}::{lk}"] for lk in links if f"{tls}::{lk}" in self.index]

    def sib_mean(self, val: np.ndarray, green: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        num = (green * val) @ self.sib.T
        den = green @ self.sib.T
        return num / np.maximum(den, 1e-9), den > 0


# ---- per-run features --------------------------------------------------------------------

def _vision(run: dict, topo: Topo, t0: float, T: int) -> np.ndarray:
    V = np.zeros((T, len(topo.node_ids), len(VIS) - 1), dtype=np.float32)
    col = {n: i for i, n in enumerate(VIS)}
    for t, rule, _lane, _anchor, measure, links, flags in run["hits"]:
        i = int(round(t - t0))
        if not 0 <= i < T:
            continue
        if rule == "stuck_on_green":
            cats = ["stuck_sibling" if flags.get("sibling_flowing") else "stuck_alone"]
        elif rule == "midblock_stop":
            cats = ["midblock"]
            if flags.get("queued_behind", 0) >= 2:
                cats.append("midblock_impact")
            if flags.get("class") in ("bus", "auto_rickshaw"):
                cats.append("midblock_dwell")
        elif rule == "flow_void":
            cats = ["void"]
            if flags.get("swerves", 0) >= 2 and flags.get("share", 0.0) >= 0.2:
                cats.append("void_strong")
        elif rule == "collision_cue":
            cats = ["collision"]
        elif rule == "wrong_way":
            cats = ["wrong_way"]
        else:
            continue
        v = float(np.log1p(max(measure, 0.0)))
        for tls, lk in links:
            n = topo.index.get(f"{tls}::{lk}")
            if n is None:
                continue
            for c in cats:
                if v > V[i, n, col[c]]:
                    V[i, n, col[c]] = v
    # a hit that flickers off for a tick or two is still the same evidence
    return roll_ext(V, int(CLEAR_S), np.max)


def base_features(run: dict, topo: Topo) -> dict:
    d = np.load(run["features_file"])
    t = d["t"].astype(np.float64)
    assert list(d["node_ids"]) == topo.node_ids, "node order differs from the graph"
    assert np.all(np.diff(t) == 1.0), "features are not one per second"
    assert np.array_equal(d["cam_t"], d["t"]), "camera and lane features are not aligned"
    x = d["x"].astype(np.float32)
    cam = d["cam"].astype(np.float32)
    f = {n: x[..., i] for i, n in enumerate(FEATURE_NAMES)}
    g = f["is_green"]
    h, v, q = f["halting_frac"], f["mean_speed_frac"], f["queue_pcu"]
    if EMPTY_LANE_FREE:
        # SUMO reports an empty lane's mean speed as the lane's *current* speed
        # limit, so an empty blocked lane (limit 0.1 m/s) reads as crawling:
        # the injection itself, not traffic. With nothing halted, queued or
        # approaching, read the lane as free-flowing, as a real sensor with no
        # vehicle over it would be.
        empty = (h == 0) & (q == 0) & (f["approaching_pcu"] == 0)
        v = np.where(empty, 1.0, v).astype(np.float32)
    ro = f["receiving_occupancy"]
    sib_v, has_sib = topo.sib_mean(v, g)
    lane = np.stack([
        q, h, 1.0 - v, ro, f["approaching_pcu"], f["receiving_queue_pcu"],
        roll_ext(h, 90, np.min),                        # the queue never cleared in a cycle
        1.0 - roll_ext(v, 90, np.max),                  # the lane never ran free in a cycle
        roll_mean(g * h * (1.0 - v), 30),               # halted while it has green
        roll_mean(g * (v < 0.2) * (h > 0.05), 60),      # share of green spent standing
        roll_mean(g * h * (1.0 - ro), 30),              # halted on green, road ahead empty
        roll_mean(g * has_sib * (sib_v - v), 30),       # slower than its green siblings
        roll_mean(h, 180), roll_mean(q, 180),
    ], axis=-1)
    cq, cap, cro, crq, conf, seen, vscore = (cam[..., i] for i in range(7))
    sib_q, has_csib = topo.sib_mean(cq, g)
    camf = np.stack([
        cq, cap, cro, crq, conf, np.log1p(seen),
        roll_ext(cq, 90, np.min),
        roll_mean(g * cq, 30),
        roll_mean(g * cq * (1.0 - cro), 30),
        roll_mean(g * has_csib * (cq - sib_q), 30),
        roll_mean(cq, 180),
        cq - lag(cq, 30),
    ], axis=-1)
    out_cam2 = None
    if cam.shape[-1] >= 11:  # version 2 recordings: the tracker per approach lane
        n, ns, nm = cam[..., 7], cam[..., 8], cam[..., 9]
        share = ns / np.maximum(n, 1.0)
        sib_share, has_s = topo.sib_mean(share, g)
        out_cam2 = np.stack([
            n, ns, nm, share,
            roll_mean(g * share, 30),                              # stopped while it has green
            roll_mean(g * (nm == 0) * (ns > 0), 60),               # green, stopped, none moving
            roll_ext(ns, 90, np.min),                              # someone stopped all cycle
            roll_mean(g * has_s * (share - sib_share), 30),        # more stopped than siblings
            roll_mean(nm, 60),
        ], axis=-1).astype(np.float32)
    vis = np.concatenate([_vision(run, topo, t[0], len(t)),
                          roll_ext(vscore, int(CLEAR_S), np.max)[..., None]], axis=-1)
    ctx = np.stack([g, f["phase_age_frac"]], axis=-1)
    return {"t": t, "bin": ((t - t[0]) // BIN_S).astype(int), "lane": lane.astype(np.float32),
            "cam": camf.astype(np.float32), "vis": vis.astype(np.float32),
            "ctx": ctx.astype(np.float32), "cam2": out_cam2}


# ---- layer 1: what is normal for this link, at this level, in this slot ---------------------

def _z_blocks(f: dict) -> list:
    out = [("lane", slice(None)), ("cam", [CAM.index(c) for c in CAM_Z])]
    if f.get("cam2") is not None:
        out.append(("cam2", slice(None)))
    return out


def fit_baseline(feats: list[dict], levels: list[str]) -> dict:
    """{level: {block: (mu[bin, N, F], sd[bin, N, F])}} from incident-free runs."""
    out: dict = {}
    for lv in sorted(set(levels)):
        mine = [f for f, lvl in zip(feats, levels, strict=True) if lvl == lv]
        out[lv] = {}
        for block, cols in _z_blocks(mine[0]):
            X = np.concatenate([f[block][..., cols] for f in mine])
            b = np.concatenate([f["bin"] for f in mine])
            node_mu, node_sd = X.mean(0), X.std(0)
            floor = 0.1 * X.reshape(-1, X.shape[-1]).std(0) + 1e-3
            nb = int(b.max()) + 1
            mu = np.empty((nb,) + X.shape[1:], dtype=np.float32)
            sd = np.empty_like(mu)
            for k in range(nb):
                sel = b == k
                if sel.sum() >= 120 * len(mine) // 2:
                    mu[k], sd[k] = X[sel].mean(0), X[sel].std(0)
                else:  # too little of this slot in the normal runs: the level-wide normal
                    mu[k], sd[k] = node_mu, node_sd
            out[lv][block] = (mu, np.maximum(sd, floor))
    return out


def zscores(f: dict, level: str, base: dict) -> dict:
    z = {}
    for block, cols in _z_blocks(f):
        mu, sd = base[level][block]
        b = np.minimum(f["bin"], len(mu) - 1)
        z[f"{block}_z"] = np.clip((f[block][..., cols] - mu[b]) / sd[b], -50, 50).astype(
            np.float16)
    return z


def design(f: dict, arm: str) -> np.ndarray:
    return np.concatenate([np.asarray(f[b], dtype=np.float32) for b in ARMS[arm]["blocks"]],
                          axis=-1)


# ---- labels ------------------------------------------------------------------------------

def labels(run: dict, topo: Topo, t: np.ndarray, uncovered: bool) -> np.ndarray:
    """+1 on an incident's links while it is on; -1 (not learned from) for the
    45 s after it ends, and throughout an incident the arm could not see."""
    y = np.zeros((len(t), len(topo.node_ids)), dtype=np.int8)
    t0 = t[0]
    for w in run["windows"]:
        nodes = topo.nodes_of(w["tls"], w["links"])
        s = int(w["start"] - t0)
        e = int((w["end"] or MAX_STEPS) - t0)
        g = min(len(t) - 1, e + LATENCY_GRACE_S)
        if s >= len(t) or not nodes:
            continue
        if w["covered"] or uncovered:
            y[s : e + 1, nodes] = 1
            blk = y[e + 1 : g + 1, nodes]
            y[e + 1 : g + 1, nodes] = np.where(blk == 1, 1, -1)
        else:
            blk = y[s : g + 1, nodes]
            y[s : g + 1, nodes] = np.where(blk == 1, 1, -1)
    return y


# ---- layer 3: the combiner ---------------------------------------------------------------

def fit_lr(X: np.ndarray, y: np.ndarray, w: np.ndarray, l2: float = L2) -> dict:
    mu = np.average(X, axis=0, weights=w)
    sd = np.sqrt(np.average((X - mu) ** 2, axis=0, weights=w))
    sd = np.where(sd < 1e-6, np.inf, sd)  # a constant column carries nothing: zero it
    Xb = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])
    W = w.sum()
    beta = np.zeros(Xb.shape[1])
    pbar = float(np.average(y, weights=w))
    beta[0] = np.log(pbar / (1 - pbar))
    pen = np.full(Xb.shape[1], l2)
    pen[0] = 1e-9

    def loss(b: np.ndarray) -> float:
        z = Xb @ b
        return float(np.sum(w * (np.logaddexp(0.0, z) - y * z)) / W + 0.5 * np.sum(pen * b * b))

    cur = loss(beta)
    for _ in range(200):  # Newton with backtracking: plain Newton overshoots on rare positives
        z = Xb @ beta
        p = 0.5 * (1.0 + np.tanh(0.5 * z))
        grad = Xb.T @ (w * (p - y)) / W + pen * beta
        hess = (Xb.T * (w * p * (1 - p))) @ Xb / W + np.diag(pen)
        step = np.linalg.solve(hess, grad)
        a = 1.0
        while a > 1e-6:
            new = loss(beta - a * step)
            if new <= cur - 1e-4 * a * float(grad @ step):
                break
            a *= 0.5
        else:
            break
        beta = beta - a * step
        done = cur - new < 1e-10
        cur = new
        if done:
            break
    return {"mu": mu, "sd": sd, "beta": beta, "loss": cur}


def predict(m: dict, X: np.ndarray) -> np.ndarray:
    """The log-odds (monotone in the probability, and it does not saturate,
    so thresholds stay distinct)."""
    return (((X - m["mu"]) / m["sd"]) @ m["beta"][1:] + m["beta"][0]).astype(np.float32)


# ---- candidates and scoring ----------------------------------------------------------------

def units(topo: Topo) -> list[list[int]]:
    """What one candidate stands for: an approach lane (all its links), or
    in version 1 a single link."""
    return topo.lane_groups if LANE_CANDIDATES else [[i] for i in range(len(topo.node_ids))]


def unit_scores(p: np.ndarray, topo: Topo) -> np.ndarray:
    if not LANE_CANDIDATES:
        return p
    return np.stack([p[:, g].max(1) for g in topo.lane_groups], axis=1)


def raise_candidates(p: np.ndarray, times: np.ndarray, theta: float, k: int,
                     groups: list[list[int]]) -> list[dict]:
    """`candidates_under`'s raise / clear / cooldown semantics on a score
    series per unit (column of `p`): present while the score is >= theta,
    raised after `k` ticks of presence (counted from the first, through gaps
    shorter than CLEAR_S), resolved after CLEAR_S without presence, then
    COOLDOWN_S before the same unit can raise again. A candidate raised
    before WARMUP_S is dropped (the engine still counts it as raised)."""
    persist_s = max(0, k - 1)
    out = []
    present = p >= theta
    for n in np.flatnonzero(present.any(0)):
        tt = times[present[:, n]]
        cuts = np.flatnonzero(np.diff(tt) >= CLEAR_S) + 1
        starts = np.concatenate([[0], cuts])
        ends = np.concatenate([cuts - 1, [len(tt) - 1]])
        cooldown_until = -1e18
        for a, b in zip(starts, ends, strict=True):
            need = max(tt[a] + persist_s, cooldown_until)
            i = a + int(np.searchsorted(tt[a : b + 1], need))
            if i <= b:
                if tt[i] >= WARMUP_S:
                    out.append({"t": float(tt[i]), "nodes": list(groups[n])})
                cooldown_until = tt[b] + CLEAR_S + COOLDOWN_S
    return out


def rule_candidates(run: dict, pol: dict, topo: Topo) -> list[dict]:
    out = []
    for c in candidates_under(run["hits"], pol):
        if c["t"] < WARMUP_S:
            continue
        nodes = [topo.index[f"{a}::{b}"] for a, b in c["links"] if f"{a}::{b}" in topo.index]
        out.append({"t": c["t"], "nodes": nodes, "rule": c["rule"]})
    return out


def score_run(run: dict, cands: list[dict], topo: Topo) -> dict:
    wins = []
    for w in run["windows"]:
        wins.append((w, set(topo.nodes_of(w["tls"], w["links"])), w["start"],
                     (w["end"] or MAX_STEPS) + LATENCY_GRACE_S))
    lat: dict[int, float] = {}
    fp = lenient = 0
    for c in cands:
        on = False
        for k, (_w, targets, lo, hi) in enumerate(wins):
            if lo <= c["t"] <= hi and targets.intersection(c["nodes"]):
                on = True
                lat[k] = min(lat.get(k, 1e18), c["t"] - lo)
        if not on:
            fp += 1
            lenient += not any(lo <= c["t"] <= hi for _w, _t, lo, hi in wins)
    rows = [{"kind": w["kind"], "covered": w["covered"], "detected": k in lat,
             "latency_s": lat.get(k)} for k, (w, *_rest) in enumerate(wins)]
    return {"windows": rows, "fp": fp, "fa_lenient": lenient, "hours": run["sim_hours"],
            "inject": run["inject"], "level": run["level"], "seed": run["seed"]}


def summarise(scored: list[dict]) -> dict:
    rows = [w for s in scored for w in s["windows"]]
    iv = [w for w in rows if w["covered"]]
    hours = sum(s["hours"] for s in scored)
    inc = [s for s in scored if s["inject"]]
    twin = [s for s in scored if not s["inject"]]
    fp_inc = sum(s["fp"] for s in inc)
    det = sum(w["detected"] for w in rows)
    lat = [w["latency_s"] for w in iv if w["detected"]]
    r_all = det / len(rows) if rows else 0.0
    r_iv = sum(w["detected"] for w in iv) / len(iv) if iv else 0.0
    prec = det / (det + fp_inc) if det + fp_inc else 0.0

    def f1(p: float, r: float) -> float:
        return 2 * p * r / (p + r) if p + r else 0.0

    return {
        "incidents": len(rows), "in_view": len(iv), "detected": det,
        "recall_all": r_all, "recall_in_view": r_iv,
        "by_kind_in_view": {k: [sum(w["detected"] for w in iv if w["kind"] == k),
                                sum(1 for w in iv if w["kind"] == k)]
                            for k in ("stall", "lane_block")},
        "latency_s_mean": st.fmean(lat) if lat else None,
        "latency_s_median": st.median(lat) if lat else None,
        "false_alarms": sum(s["fp"] for s in scored), "hours": hours,
        "fa_per_h": sum(s["fp"] for s in scored) / hours if hours else None,
        "fa_per_h_twins": (sum(s["fp"] for s in twin) / sum(s["hours"] for s in twin)
                           if twin else None),
        "fa_per_h_lenient_incident_runs": (sum(s["fa_lenient"] for s in inc)
                                           / sum(s["hours"] for s in inc) if inc else None),
        "precision_incident_runs": prec,
        "f1_all": f1(prec, r_all), "f1_in_view": f1(prec, r_iv),
    }


def pick(points: list[dict], budget: float | None) -> dict:
    """Most in-view recall within the budget (ties: fewer false alarms, then
    lower latency); with no budget, the highest in-view F1."""
    if budget is None:
        return max(points, key=lambda p: (p["train"]["f1_in_view"], -p["train"]["fa_per_h"]))
    ok = [p for p in points if p["train"]["fa_per_h"] <= budget]
    if not ok:
        return min(points, key=lambda p: p["train"]["fa_per_h"])
    return max(ok, key=lambda p: (p["train"]["recall_in_view"], -p["train"]["fa_per_h"],
                                  -(p["train"]["latency_s_mean"] or 1e9)))


def bootstrap_diff(a: list[dict], b: list[dict], name: str) -> dict:
    """In-view recall of a minus b on the same runs, resampling (seed, level)
    clusters (the resampling is seeded by the comparison's name, so an
    interval does not depend on which other comparisons ran before it)."""
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    clusters = sorted({(s["seed"], s["level"]) for s in a})

    def per(scored):
        out = {}
        for s in scored:
            c = out.setdefault((s["seed"], s["level"]), [0, 0])
            for w in s["windows"]:
                if w["covered"]:
                    c[0] += w["detected"]
                    c[1] += 1
        return np.array([out.get(c, [0, 0]) for c in clusters], dtype=float)

    pa, pb = per(a), per(b)
    idx = rng.integers(0, len(clusters), size=(N_BOOT, len(clusters)))
    da = pa[idx, 0].sum(1) / np.maximum(pa[idx, 1].sum(1), 1)
    db = pb[idx, 0].sum(1) / np.maximum(pb[idx, 1].sum(1), 1)
    d = da - db
    point = pa[:, 0].sum() / max(pa[:, 1].sum(), 1) - pb[:, 0].sum() / max(pb[:, 1].sum(), 1)
    return {"diff": point, "ci95": [float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975))],
            "clusters": len(clusters)}


# ---- the rules, re-tuned with the strict count ------------------------------------------------

def _rule_outcome_strict(runs, by_rule_hits, rule, pol):
    det: dict = {}
    fa = 0
    for i, r in enumerate(runs):
        cands = candidates_under(by_rule_hits[i].get(rule, []), {**pol, "rules": [rule]})
        for c in cands:
            if c["t"] < WARMUP_S:
                continue
            on = False
            for k, w in enumerate(r["windows"]):
                end = (w["end"] or MAX_STEPS) + LATENCY_GRACE_S
                targets = {(w["tls"], lk) for lk in w["links"]}
                if w["start"] <= c["t"] <= end and any(tuple(lk) in targets for lk in c["links"]):
                    on = True
                    det[(i, k)] = min(det.get((i, k), 1e18), c["t"] - w["start"])
            fa += not on
    return det, fa


# ---- main ----------------------------------------------------------------------------------

def _load(path: str) -> list[dict]:
    raw = Path(path).read_bytes()
    if path.endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw)["runs"]


def run_arm(arm: str, train: list[dict], evl: list[dict], tf: list[dict], ef: list[dict],
            topo: Topo, rng_seed: int = 0) -> dict:
    cfg = ARMS[arm]
    groups = units(topo)
    seeds = sorted({r["seed"] for r in train})
    # training rows: every positive, a fixed random share of negatives
    rows = []
    for i, (r, f) in enumerate(zip(train, tf, strict=True)):
        y = labels(r, topo, f["t"], cfg["uncovered"])
        rng = np.random.default_rng(rng_seed * 1000 + i)
        pos = np.argwhere(y == 1)
        neg = np.argwhere((y == 0) & (rng.random(y.shape) < NEG_RATE))
        X = design(f, arm)
        rows.append((r["seed"], np.concatenate([X[pos[:, 0], pos[:, 1]], X[neg[:, 0], neg[:, 1]]]),
                     np.concatenate([np.ones(len(pos)), np.zeros(len(neg))]),
                     np.concatenate([np.ones(len(pos)), np.full(len(neg), 1 / NEG_RATE)])))

    def fit(keep):
        sel = [x for x in rows if keep(x[0])]
        return fit_lr(np.concatenate([x[1] for x in sel]), np.concatenate([x[2] for x in sel]),
                      np.concatenate([x[3] for x in sel]))

    oof = [None] * len(train)
    for s in seeds:
        m = fit(lambda seed, s=s: seed != s)
        for i, r in enumerate(train):
            if r["seed"] == s:
                oof[i] = unit_scores(predict(m, design(tf[i], arm)), topo)
    final = fit(lambda seed: True)
    t0 = time.perf_counter()
    ev = [unit_scores(predict(final, design(f, arm)), topo) for f in ef]
    ticks = sum(len(f["t"]) for f in ef)
    ms_per_tick = (time.perf_counter() - t0) * 1000 / ticks
    allp = np.concatenate([p.ravel() for p in oof])
    fracs = np.logspace(-5.5, -1.5, N_THETA)
    thetas = sorted({float(np.quantile(allp, 1 - fr)) for fr in fracs})
    points = []
    for th in thetas:
        for k in K_GRID:
            s_tr = [score_run(r, raise_candidates(p, f["t"], th, k, groups), topo)
                    for r, p, f in zip(train, oof, tf, strict=True)]
            s_ev = [score_run(r, raise_candidates(p, f["t"], th, k, groups), topo)
                    for r, p, f in zip(evl, ev, ef, strict=True)]
            points.append({"theta": th, "K": k, "train": summarise(s_tr), "eval": summarise(s_ev),
                           "_eval_scored": s_ev})
    names = [n for b in cfg["blocks"] for n in BLOCK_NAMES[b]]
    coef = sorted(zip(names, final["beta"][1:].tolist(), strict=True), key=lambda x: -abs(x[1]))
    return {"points": points, "coefficients": coef, "ms_per_tick_73_links": ms_per_tick,
            "train_rows": int(sum(len(x[2]) for x in rows)),
            "train_positive_rows": int(sum(x[2].sum() for x in rows))}


def _by(scored: list[dict], key: str) -> dict:
    return {v: summarise([s for s in scored if s[key] == v])
            for v in sorted({s[key] for s in scored})}


def selftest() -> None:
    """`raise_candidates` must raise exactly what `candidates_under` raises
    for the same presence pattern."""
    rng = np.random.default_rng(1)
    for trial in range(300):
        T = 600
        p = (rng.random(T) < rng.uniform(0.02, 0.6)).astype(np.float32)[:, None]
        times = np.arange(1, T + 1, dtype=float)
        k = int(rng.choice(K_GRID))
        hits = [[float(t), "wrong_way", "x", "a", 10.0, [["j", "L0"]], {}]
                for t, v in zip(times, p[:, 0], strict=True) if v]
        ref = [c["t"] for c in candidates_under(hits, {**DEFAULT_POLICY, "persist_ticks": k,
                                                      "rules": ["wrong_way"],
                                                      "wrong_way_s": 3.0})]
        ref = [t for t in ref if t >= WARMUP_S]
        got = [c["t"] for c in raise_candidates(p, times, 0.5, k, [[0]])]
        assert ref == got, (trial, k, ref, got)
    print("selftest: raise_candidates == candidates_under on 300 random patterns")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("train", nargs="?")
    ap.add_argument("eval", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--arms", default=None, help="default: every arm the recordings support")
    ap.add_argument("--eval-seeds", default=None, help="score only these EVAL seeds (1,2,...)")
    ap.add_argument("--bar-arm", default=None, help="default: E_cam2 (v2), E_cam (--v1)")
    ap.add_argument("--v1", action="store_true",
                    help="version 1's counting: a candidate per link, none suppressed early")
    ap.add_argument("--empty-lane-free", action="store_true",
                    help="read an empty lane as free-flowing (removes a SUMO artefact that "
                         "lets lane sensors see a blocked lane with no vehicle on it)")
    ap.add_argument("--post-hoc", action="store_true",
                    help="these EVAL seeds informed the design: the bar verdict is not a test")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    global WARMUP_S, LANE_CANDIDATES, EMPTY_LANE_FREE
    if args.v1:
        WARMUP_S, LANE_CANDIDATES = 0.0, False
    EMPTY_LANE_FREE = args.empty_lane_free
    if args.selftest:
        selftest()
        return
    selftest()
    t_start = time.time()
    topo = Topo()
    train, evl = _load(args.train), _load(args.eval)
    if args.eval_seeds:
        keep = {int(x) for x in args.eval_seeds.split(",")}
        evl = [r for r in evl if r["seed"] in keep]
    print(f"{len(train)} TRAIN runs, {len(evl)} EVAL runs", flush=True)
    tf = [base_features(r, topo) for r in train]
    t_feat = time.perf_counter()
    ef = [base_features(r, topo) for r in evl]
    feat_ms_per_tick = (time.perf_counter() - t_feat) * 1000 / sum(len(f["t"]) for f in ef)
    # layer 1: a TRAIN run is normalised by the normal runs of the *other*
    # TRAIN seeds; EVAL runs by all TRAIN normal runs
    twins = [(r, f) for r, f in zip(train, tf, strict=True) if not r["inject"]]
    for r, f in zip(train, tf, strict=True):
        others = [(q, g) for q, g in twins if q["seed"] != r["seed"]]
        f.update(zscores(f, r["level"], fit_baseline([g for _, g in others],
                                                     [q["level"] for q, _ in others])))
    base_all = fit_baseline([g for _, g in twins], [q["level"] for q, _ in twins])
    for r, f in zip(evl, ef, strict=True):
        f.update(zscores(f, r["level"], base_all))
    has_cam2 = all(f["cam2"] is not None for f in tf + ef)
    arms = (args.arms.split(",") if args.arms else
            [a for a in ARMS if (a in V1_ARMS or has_cam2)])
    bar_arm = args.bar_arm or ("E_cam2" if has_cam2 and not args.v1 else "E_cam")
    print(f"features ready ({time.time() - t_start:.0f}s); arms {arms}; bar arm {bar_arm}",
          flush=True)

    report: dict = {"meta": {"train_runs": len(train), "eval_runs": len(evl),
                             "train_seeds": sorted({r["seed"] for r in train}),
                             "eval_seeds": sorted({r["seed"] for r in evl}),
                             "levels": sorted({r["level"] for r in train}),
                             "preset": sorted({r["preset"] for r in train}),
                             "bin_s": BIN_S, "neg_rate": NEG_RATE, "l2": L2,
                             "k_grid": K_GRID, "budgets": BUDGETS,
                             "rule_grids": RULE_GRIDS, "rule_persist": RULE_PERSIST,
                             "feature_ms_per_tick_73_links_batch": feat_ms_per_tick,
                             "version": 1 if args.v1 else 2, "warmup_s": WARMUP_S,
                             "empty_lane_free": EMPTY_LANE_FREE, "post_hoc": args.post_hoc,
                             "candidate_unit": "approach lane" if LANE_CANDIDATES else "link",
                             "bar": {"arm": bar_arm, "vs": f"A_rules@{BAR_BUDGET:g}",
                                     "budget": BAR_BUDGET, "max_eval_fa_per_h": BAR_MAX_EVAL_FA}},
                    "arms": {}}
    scored_at: dict[str, list[dict]] = {}

    # the rules
    for name, pol in (("A_quiet", QUIET_POLICY), ("A_hand", DEFAULT_POLICY)):
        s_tr = [score_run(r, rule_candidates(r, pol, topo), topo) for r in train]
        s_ev = [score_run(r, rule_candidates(r, pol, topo), topo) for r in evl]
        report["arms"][name] = {"policy": pol, "train": summarise(s_tr),
                                "eval": summarise(s_ev), "eval_by_level": _by(s_ev, "level")}
        scored_at[name] = s_ev
        print(f"{name}: eval {_fmt(report['arms'][name]['eval'])}", flush=True)
    # the same search as m8_incident_analysis.py, with the strict count and the wider grid
    A._rule_outcome = _rule_outcome_strict
    A.GRIDS, A.PERSIST = RULE_GRIDS, RULE_PERSIST
    for b in BUDGETS:
        name = f"A_rules@{b:g}"
        pol, pareto = A.search(train, b)
        s_tr = [score_run(r, rule_candidates(r, pol, topo), topo) for r in train]
        s_ev = [score_run(r, rule_candidates(r, pol, topo), topo) for r in evl]
        report["arms"][name] = {"policy": pol, "train": summarise(s_tr), "eval": summarise(s_ev),
                                "eval_by_level": _by(s_ev, "level"), "train_pareto": pareto}
        scored_at[name] = s_ev
        print(f"{name}: eval {_fmt(report['arms'][name]['eval'])} ({time.time() - t_start:.0f}s)",
              flush=True)

    # the learned arms
    for arm in arms:
        res = run_arm(arm, train, evl, tf, ef, topo)
        chosen = {}
        for label, b in [(f"@{x:g}", x) for x in BUDGETS] + [("@f1", None)]:
            p = pick(res["points"], b)
            chosen[label] = {k: v for k, v in p.items() if k != "_eval_scored"}
            chosen[label]["eval_by_level"] = _by(p["_eval_scored"], "level")
            scored_at[f"{arm}{label}"] = p["_eval_scored"]
        # TRAIN Pareto frontier, with what each of its points scored held out
        pts = sorted(res["points"], key=lambda p: (p["train"]["fa_per_h"],
                                                   -p["train"]["recall_in_view"]))
        frontier, top = [], -1.0
        for p in pts:
            if p["train"]["recall_in_view"] > top:
                top = p["train"]["recall_in_view"]
                frontier.append({"theta": p["theta"], "K": p["K"],
                                 "fa_per_h_train": p["train"]["fa_per_h"],
                                 "recall_in_view_train": p["train"]["recall_in_view"],
                                 "fa_per_h_eval": p["eval"]["fa_per_h"],
                                 "recall_in_view_eval": p["eval"]["recall_in_view"],
                                 "recall_all_eval": p["eval"]["recall_all"]})
        report["arms"][arm] = {"chosen": chosen, "coefficients": res["coefficients"],
                               "ms_per_tick_73_links": res["ms_per_tick_73_links"],
                               "train_rows": res["train_rows"],
                               "train_positive_rows": res["train_positive_rows"],
                               "train_frontier": frontier}
        for label, c in chosen.items():
            print(f"{arm}{label}: theta {c['theta']:.4g} K {c['K']} train FA/h "
                  f"{c['train']['fa_per_h']:.2f} | eval {_fmt(c['eval'])}", flush=True)
        print(f"  ({time.time() - t_start:.0f}s)", flush=True)

    comps = {}
    for a, b in [(f"{bar_arm}@1", "A_rules@1"), (f"{bar_arm}@1", "A_quiet"),
                 ("E_cam@1", "A_rules@1"), ("E_cam@1", "A_quiet"), ("E_lane@1", "A_rules@1"),
                 ("C_cam@1", "A_rules@1"), ("C_cam2@1", "A_rules@1"), ("D_vis@1", "A_rules@1"),
                 ("E_cam@1", "C_cam@1"), ("E_cam2@1", "C_cam2@1"), ("E_cam2@1", "E_cam@1"),
                 ("E_cam@1", "D_vis@1"), ("E_lane@1", "C_lane@1"), ("C_lane@1", "C_lane_noz@1"),
                 ("E_cam@5", "A_rules@5"), ("E_cam2@5", "A_rules@5"), ("E_lane@5", "A_rules@5")]:
        key = f"{a} - {b}"
        if a in scored_at and b in scored_at and key not in comps:
            comps[key] = bootstrap_diff(scored_at[a], scored_at[b], key)
    report["comparisons_recall_in_view"] = comps
    if f"{bar_arm}@1" in scored_at:
        c = comps[f"{bar_arm}@1 - A_rules@1"]
        e_fa = report["arms"][bar_arm]["chosen"]["@1"]["eval"]["fa_per_h"]
        report["bar_verdict"] = {
            "recall_gain_ci_above_zero": bool(c["ci95"][0] > 0),
            "eval_fa_per_h": e_fa, "fa_within": bool(e_fa <= BAR_MAX_EVAL_FA),
            "passes": bool(c["ci95"][0] > 0 and e_fa <= BAR_MAX_EVAL_FA),
            "valid_test": not args.post_hoc}
        print("bar:", report["bar_verdict"], flush=True)
    for k, v in comps.items():
        print(f"{k}: {v['diff']:+.3f} [{v['ci95'][0]:+.3f}, {v['ci95'][1]:+.3f}]")
    report["meta"]["wall_min"] = round((time.time() - t_start) / 60, 1)
    Path(args.out).write_text(json.dumps(report, indent=1, default=float))
    print(f"wrote {args.out}")


def _fmt(s: dict) -> str:
    def n(v):
        return "--" if v is None else f"{v:.2f}"

    return (f"recall in view {n(s['recall_in_view'])} ({s['by_kind_in_view']}) all "
            f"{n(s['recall_all'])}  FA/h {n(s['fa_per_h'])} (twins {n(s['fa_per_h_twins'])}, "
            f"lenient {n(s['fa_per_h_lenient_incident_runs'])})  "
            f"P {n(s['precision_incident_runs'])}  F1(iv) {n(s['f1_in_view'])}  "
            f"lat {n(s['latency_s_mean'])}")


if __name__ == "__main__":
    main()
