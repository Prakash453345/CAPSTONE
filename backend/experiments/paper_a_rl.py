"""PressLight-style reinforcement-learning baseline for paper A (2026-10-28).

Wei et al., "PressLight: Learning Max Pressure Control to Coordinate Traffic
Signals in Arterial Network", KDD 2019. One deep-Q agent per signalised
junction:
- state: one-hot current phase; vehicles on each incoming lane in three
  equal segments of its last 150 m (PressLight's segmented lanes); vehicles
  on each outgoing lane;
- action: the phase for the next 10 s (a change goes through the same yellow
  and all-red as every other controller in the benchmark);
- reward: minus the junction's pressure, |sum_in x(l) - sum_out x(m)| over its
  movements (vehicle counts per lane);
- DQN: MLP 2x64, gamma 0.8, replay 20k, batch 64, Adam 1e-3, target net synced
  every episode, epsilon 0.8 -> 0.05.

Phases, clearances and demand are the benchmark's own (`paper_a_baselines`
program: Webster's phases on the adopted layout, SIGNAL_ALL_RED honoured).
Trained only on training seeds 101-108, checkpoint chosen on 109-110, one
model per demand level. Evaluated on the benchmark's fresh seeds.

    ITMS_SCENARIO=scenarios/generated/ingolstadt python scripts/paper_a_rl.py train --level medium
    ITMS_SCENARIO=... python scripts/paper_a_rl.py eval --level medium --seeds 279,...,288 --out x.json
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import deque
from pathlib import Path

import m5_harness as H
import numpy as np
import paper_a_baselines as PB
import torch
from sim_service.control import metrics
from sim_service.control.runner import _ensure_sumo_home, _resolve_sumo_binary
from sim_service.signal_controller.traci_cabinet import TraCICabinet
from torch import nn

DELTA_S = 10
SEG_M = 150.0
TRAIN_SEEDS = list(range(101, 109))
VAL_SEEDS = [109, 110]
MODEL_DIR = Path(__file__).resolve().parent.parent / "baselines" / "2026-10-28_paper_a" / "rl_models"


class Junction:
    def __init__(self, tls: str, cfg, state_len: int):
        import traci  # noqa: PLC0415

        self.tls, self.cfg = tls, cfg
        self.cab = TraCICabinet(tls, cfg.phases, state_len)
        self.phases = list(cfg.ring_order)
        links = traci.trafficlight.getControlledLinks(tls)
        self.moves = sorted({(lk[0][0], lk[0][1]) for lk in links if lk})
        self.inl = sorted({a for a, _ in self.moves if not a.startswith(":")})
        self.outl = sorted({b for _, b in self.moves if not b.startswith(":")})
        self.len = {ln: traci.lane.getLength(ln) for ln in self.inl}
        self.cur = 0
        self.dim = len(self.phases) + 3 * len(self.inl) + len(self.outl)

    def observe(self):
        import traci  # noqa: PLC0415

        seg = []
        for ln in self.inl:
            L = self.len[ln]
            c = [0, 0, 0]
            for v in traci.lane.getLastStepVehicleIDs(ln):
                d = L - traci.vehicle.getLanePosition(v)
                if d < SEG_M:
                    c[min(2, int(d / (SEG_M / 3)))] += 1
            seg += c
        out = [traci.lane.getLastStepVehicleNumber(ln) for ln in self.outl]
        onehot = [1.0 if i == self.cur else 0.0 for i in range(len(self.phases))]
        return np.array(onehot + [x / 10 for x in seg] + [x / 10 for x in out], dtype=np.float32)

    def pressure(self):
        import traci  # noqa: PLC0415

        n = {}
        for ln in set(self.inl) | set(self.outl):
            n[ln] = traci.lane.getLastStepVehicleNumber(ln)
        return abs(sum(n.get(a, 0) - n.get(b, 0) for a, b in self.moves
                       if not a.startswith(":") and not b.startswith(":")))


def q_net(i: int, o: int) -> nn.Module:
    return nn.Sequential(nn.Linear(i, 64), nn.ReLU(), nn.Linear(64, 64), nn.ReLU(), nn.Linear(64, o))


def episode(level: str, seed: int, nets: dict, eps: float, learn=None, trip: Path | None = None):
    """One simulation. `learn(tls, s, a, r, s2)` receives each transition."""
    import sumolib  # noqa: PLC0415
    import traci  # noqa: PLC0415

    configs, _, _, paths = PB.baseline_inputs(level)
    _ensure_sumo_home()
    net = sumolib.net.readNet(str(H.NET_PATH), withPrograms=True)
    args = [_resolve_sumo_binary(), "-c", str(paths["sumocfg"]), "--step-length", "1.0",
            "--no-step-log", "true", "--time-to-teleport", "300", "--seed", str(seed)]
    if trip:
        args += ["--tripinfo-output", str(trip)]
    traci.start(args)
    try:
        js = {}
        for tls, cfg in configs.items():
            sl = len(next(iter(net.getTLS(tls).getPrograms().values())).getPhases()[0].state)
            js[tls] = Junction(tls, cfg, sl)
            js[tls].cab.command(js[tls].phases[0])
        conflicts = {tls: [(int(a[1:]), int(b[1:])) for a, bs in cfg.conflict_matrix.items()
                           for b in bs if a < b] for tls, cfg in configs.items()}
        # per junction: queue of (state string, seconds) still to show
        sched = {t: deque() for t in js}
        last = {t: None for t in js}
        step = teleports = viol = 0
        while traci.simulation.getMinExpectedNumber() > 0 and step < H.MAX_STEPS_SAFETY_CAP:
            for t, j in js.items():
                if not sched[t]:
                    s = j.observe()
                    if last[t] is not None and learn is not None:
                        ps, pa = last[t]
                        learn(t, ps, pa, -j.pressure() / 10.0, s)
                    if random.random() < eps:
                        a = random.randrange(len(j.phases))
                    else:
                        with torch.no_grad():
                            a = int(nets[t](torch.from_numpy(s)).argmax())
                    last[t] = (s, a)
                    if a != j.cur:
                        g = j.cab._state_by_phase[j.phases[j.cur]]  # noqa: SLF001
                        sched[t].append(("".join("y" if c in "Gg" else "r" for c in g),
                                         int(round(j.cfg.yellow_s))))
                        if j.cfg.all_red_s > 0:
                            sched[t].append(("r" * len(g), int(np.ceil(j.cfg.all_red_s))))
                        j.cur = a
                    sched[t].append((j.cab._state_by_phase[j.phases[a]], DELTA_S))  # noqa: SLF001
                st, n = sched[t][0]
                traci.trafficlight.setRedYellowGreenState(t, st)
                sched[t][0] = (st, n - 1)
                if n - 1 <= 0:
                    sched[t].popleft()
            traci.simulationStep()
            step += 1
            teleports += traci.simulation.getStartingTeleportNumber()
            for t, pairs in conflicts.items():
                s = traci.trafficlight.getRedYellowGreenState(t)
                if any(s[i] == "G" and s[j] == "G" for i, j in pairs):
                    viol += 1
        unfinished = traci.simulation.getMinExpectedNumber()
    finally:
        traci.close()
    return {"steps": step, "teleports": teleports, "interlock_violations": viol,
            "unfinished_at_cap": unfinished, "paths": paths}


def _dims(level: str):
    import sumolib  # noqa: PLC0415
    import traci  # noqa: PLC0415

    configs, _, _, paths = PB.baseline_inputs(level)
    _ensure_sumo_home()
    net = sumolib.net.readNet(str(H.NET_PATH), withPrograms=True)
    traci.start([_resolve_sumo_binary(), "-c", str(paths["sumocfg"]), "--no-step-log", "true"])
    try:
        out = {}
        for tls, cfg in configs.items():
            sl = len(next(iter(net.getTLS(tls).getPrograms().values())).getPhases()[0].state)
            j = Junction(tls, cfg, sl)
            out[tls] = (j.dim, len(j.phases))
    finally:
        traci.close()
    return out


def score(level, seed, nets, tag="rl"):
    trip = Path("/tmp/m8_tripinfo") / f"rl_{H.SCENARIO_NAME}_{level}_{seed}_{time.time_ns()}.xml"
    trip.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    r = episode(level, seed, nets, 0.0, trip=trip)
    m = metrics.compute_run_metrics(trip, r["paths"]["route"])
    trip.unlink(missing_ok=True)
    return {"scenario": H.SCENARIO_NAME, "controller": "presslight", "arm": tag,
            "demand_level": level, "seed": seed, "steps": r["steps"],
            "interlock_violations": r["interlock_violations"], "teleports": r["teleports"],
            "unfinished_at_cap": r["unfinished_at_cap"], "person_delay_s": m.person_delay_s,
            "n_trips_total": m.n_trips_total, "n_trips_scored": m.n_trips_scored,
            "entry_delay_s": m.entry_delay_person_s,
            "person_throughput_per_hour": m.person_throughput_per_hour,
            "stops_per_vehicle": m.stops_per_vehicle,
            "wait_time_s": {"mean_s": m.wait_time_s.mean_s, "p95_s": m.wait_time_s.p95_s,
                            "max_s": m.wait_time_s.max_s},
            "wall_s": round(time.time() - t0, 1)}


def train(level: str, episodes: int, seed: int = 0):
    random.seed(seed)
    torch.manual_seed(seed)
    dims = _dims(level)
    nets = {t: q_net(i, o) for t, (i, o) in dims.items()}
    tgt = {t: q_net(i, o) for t, (i, o) in dims.items()}
    for t in nets:
        tgt[t].load_state_dict(nets[t].state_dict())
    opt = {t: torch.optim.Adam(nets[t].parameters(), lr=1e-3) for t in nets}
    buf = {t: deque(maxlen=20000) for t in nets}
    gamma, batch = 0.8, 64
    log, best = [], (float("inf"), None)

    def learn(t, s, a, r, s2):
        buf[t].append((s, a, r, s2))
        if len(buf[t]) < 500:
            return
        b = random.sample(buf[t], batch)
        S = torch.from_numpy(np.stack([x[0] for x in b]))
        A = torch.tensor([x[1] for x in b])
        R = torch.tensor([x[2] for x in b], dtype=torch.float32)
        S2 = torch.from_numpy(np.stack([x[3] for x in b]))
        with torch.no_grad():
            y = R + gamma * tgt[t](S2).max(1).values
        q = nets[t](S).gather(1, A[:, None]).squeeze(1)
        loss = nn.functional.smooth_l1_loss(q, y)
        opt[t].zero_grad()
        loss.backward()
        opt[t].step()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for ep in range(episodes):
        eps = max(0.05, 0.8 * (1 - ep / (0.7 * episodes)))
        episode(level, TRAIN_SEEDS[ep % len(TRAIN_SEEDS)], nets, eps, learn=learn)
        for t in nets:
            tgt[t].load_state_dict(nets[t].state_dict())
        if ep >= episodes // 3 and (ep % 5 == 4 or ep == episodes - 1):
            v = float(np.mean([score(level, s, nets)["person_delay_s"] for s in VAL_SEEDS]))
            log.append({"episode": ep + 1, "eps": round(eps, 3), "val_person_delay": v})
            print(log[-1], flush=True)
            if v < best[0]:
                best = (v, ep + 1)
                torch.save({t: n.state_dict() for t, n in nets.items()},
                           MODEL_DIR / f"{H.SCENARIO_NAME}_{level}.pt")
    meta = {"level": level, "episodes": episodes, "best": {"val_person_delay": best[0],
            "episode": best[1]}, "log": log, "train_seeds": TRAIN_SEEDS, "val_seeds": VAL_SEEDS}
    (MODEL_DIR / f"{H.SCENARIO_NAME}_{level}.json").write_text(json.dumps(meta, indent=1))
    return meta


def load(level: str):
    dims = _dims(level)
    sd = torch.load(MODEL_DIR / f"{H.SCENARIO_NAME}_{level}.pt")
    nets = {t: q_net(i, o) for t, (i, o) in dims.items()}
    for t in nets:
        nets[t].load_state_dict(sd[t])
        nets[t].eval()
    return nets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train", "eval"])
    ap.add_argument("--level", required=True)
    ap.add_argument("--episodes", type=int, default=80)
    ap.add_argument("--seeds", default="279,280,281,282,283,284,285,286,287,288")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.cmd == "train":
        print(train(a.level, a.episodes)["best"])
    else:
        nets = load(a.level)
        recs = [score(a.level, int(s), nets) for s in a.seeds.split(",")]
        for r in recs:
            print(r["seed"], r["person_delay_s"], r["teleports"], r["interlock_violations"])
        if a.out:
            old = json.loads(Path(a.out).read_text()) if Path(a.out).exists() else {"records": []}
            old["records"] = [r for r in old["records"] if r["demand_level"] != a.level] + recs
            Path(a.out).write_text(json.dumps(old, indent=1))


if __name__ == "__main__":
    main()
