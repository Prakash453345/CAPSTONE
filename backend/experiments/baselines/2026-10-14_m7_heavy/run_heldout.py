"""Training seeds: reactive vs corridor on the current controller inputs (as Run B).
usage: python run_train.py <level> <seed...> > out.jsonl"""
import json, sys
sys.path.insert(0, "scripts")
import m7_corridor_benchmark as B
import m8_harness as M
import os
ARMS = os.environ.get("ARMS", "reactive,corridor").split(",")
level, seeds = sys.argv[1], [int(s) for s in sys.argv[2:]]
inputs = M.ccacamp_inputs(level)
for seed in seeds:
    for arm in ARMS:
        r = B.run_one(arm, level, seed, inputs=inputs)
        keep = {k: r.get(k) for k in ("arm", "demand_level", "seed", "interlock_violations", "person_delay_s",
                                      "n_ev_completed", "ev_duration_s", "ev_time_loss_s", "ev_waiting_time_s", "ev_stops")}
        keep["corridor"] = r.get("corridor"); keep["preempt_s"] = r.get("preempt_seconds_total")
        print(json.dumps(keep), flush=True)
