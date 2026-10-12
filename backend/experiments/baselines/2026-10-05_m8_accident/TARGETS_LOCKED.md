# Accident-candidate targets — LOCKED 2026-10-05, before any held-out scoring

Scope: a camera-visible **rear-end aftermath** (two vehicles that were moving,
now stopped in contact, off a red-light queue). Output is a *candidate for an
operator to confirm* (ADR-006), never "accident detected".

Procedure: operating point (contact gap, red exclusion) chosen on TRAIN seeds
101-103 (medium+heavy). Held-out seeds 1-3 (medium+heavy, incident-on and
incident-off twins) scored ONCE. Targets never change after this file.

| # | Target | Bar | Anchor |
|---|---|---|---|
| A1 | False alarms on incident-off twins (held-out) | <= 2.0 /h | `quiet` point: 1.75 /h |
| A2 | In-view recall of injected rear-end aftermaths | >= 30 % | generic rules: ~19 % |
| A3 | Mean latency, contact -> candidate | <= 45 s | gate grace 45 s |
| A4 | A1 and A2 hold under both detector presets (`itms6_640`, `itms6aug_640`) | both | v3 default |
| A5 | Existing rules + 283-test suite unchanged (new behaviour off unless enabled) | pass | |

Not claimed, whatever the result: that real crashes look like the injected
aftermath; recall is a plumbing check because the injector writes the contact
the rule looks for. A crash that happens on a red-lane queue is
indistinguishable from the queue and is excluded by design.

## Operating point chosen on TRAIN seeds 101-103 (13 in-view injected, 4.6 h twins)
Contact gap <= 1.0 m, pair stopped within 2 s of each other, <= 1 other stopped
vehicle within 20 m on the lane, speed >= 5 m/s in the 3 s before stopping,
not on a red/yellow-link lane, stopped >= 20 s. Train: 31 % in-view recall
(4/13), 0.0 false alarms/h, 24 s latency. Contact gap alone: 22-380 FA/h.
Small sample; the held-out run decides.
