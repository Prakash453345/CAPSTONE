# M8 accident candidate (rear-end aftermath) — 2026-10-05

**Verdict: recall target MISSED (A2). Not adopted as default; opt-in operating point `accident` (`VISION_RULES=accident`).**
Candidates are for an operator to confirm (ADR-006); this never "detects accidents".

## What was built
- `IncidentInjector` kind `collision` (sim-service): leader brakes to 0, follower ignores it (speed mode 0, speed clamped to land on the leader's bumper), both held stopped from the **contact** tick for 60-120 s. Needs SUMO `--collision.action warn`. Unit tests in `test_anomaly_injector.py`.
- `collision_cue` contact mode (`RuleConfig.collision_contact_m`, red-lane skip, simultaneous-stop, isolation and abrupt-stop gates; defaults off) + `accident` operating point. Tests in `test_rules_and_health.py`.
- Gate `scripts/m8_accident_gate.py` (same harness as `m8_incident_gate.py`, 6 incidents/run, medium+heavy).

## Locked targets (`TARGETS_LOCKED.md`, written before the held-out run) vs held-out (seeds 1-3, medium+heavy, 4.6 h incident-off twins)
| # | Target | `itms6_640` | `itms6aug_640` | |
|---|---|---|---|---|
| A1 | false alarms on twins <= 2.0 /h | 0.44 (2 in 4.57 h) | 1.53 (7 in 4.57 h) | pass |
| A2 | in-view recall >= 30 % | 6.7 % (1/15) | 6.7 % (1/15) | **FAIL** |
| A3 | mean latency <= 45 s | 24 s | 27 s | pass (n=1) |
| A4 | A1+A2 under both presets | | | **FAIL** (A2) |
| A5 | existing rules/tests unchanged | 153 vision + 17 injector tests pass | | pass |

## What the numbers do and do not show
- Train seeds 101-103 gave 31 % (4/13) at 0 FA/h: that choice of five gates on 13 incidents did not generalise (held-out 1/15). Small samples both times.
- Contact gap alone: 22-380 false alarms/h on twins (dense queues put stopped cars bumper-to-bumper in the camera too). Red-lane exclusion removes most of them but also most injected crashes (3 of 4 landed on red-link lanes) — a crash in a red queue is indistinguishable from the queue.
- Recall is partly circular (the injector writes the contact the rule looks for). The real-world detection rate is **unknown**; no real crash footage exists. The false-alarm rate is the more trustworthy number, and only for SUMO traffic.
- First injector draft overlapped the pair by 65 % of a car length; camera merged them (0 detections). Contact version fixed that.
- Fire/vehicle detection are unaffected.
