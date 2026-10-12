"""M8 accident-candidate gate: the incident gate with a collision-aftermath
injector. Same harness, rules log and scoring as `m8_incident_gate.py`; only
the injected kind (`collision`: two moving vehicles end up stopped with
overlapping footprints) and SUMO's `--collision.action warn` differ.

The injector writes the very footprint overlap `collision_cue` looks for, so
recall here is a plumbing check, not evidence about real crashes. What it
measures honestly: false alarms per hour on incident-off twins and on dense
queues, and latency. Candidates are for an operator to confirm (ADR-006).

    python scripts/m8_accident_gate.py --out results/m8_accident_gate.json ...
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m8_incident_gate as G  # noqa: E402

G.KINDS = ("collision",)
G.EXTRA_SUMO_ARGS = ["--collision.action", "warn", "--collision.mingap-factor", "0"]
G.N_INCIDENTS = 6
# log every contact pair out to 3 m bumper gap, collision rule only; the
# operating gap / red exclusion are chosen offline on train seeds
G.LOGGING_RULES = dataclasses.replace(G.LOGGING_RULES, collision_contact_m=3.0,
                                      enabled=("collision_cue",))

if __name__ == "__main__":
    G.main()
