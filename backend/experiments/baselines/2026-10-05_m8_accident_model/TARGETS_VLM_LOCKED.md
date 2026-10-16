# Accident detector V: zero-shot open VLM on sliding windows — targets LOCKED 2026-10-11, before the run

Why (research, 2026): the 2026 ACCIDENT-challenge papers that beat hand-built pipelines use frozen VLMs zero-shot (Qwen3-VL / Gemini two-pass: time score ~0.50); a small trained
transformer reaches 88% on a curated balanced set, Gemini 90% (arXiv 2512.11350). Our tracker trigger (Stage A) failed: recall 53%, located 22%. Those papers localise a
KNOWN accident and use paid APIs; none measures false alarms. This run measures them with an open model on a T4.

Model: Qwen2.5-VL-7B-Instruct, 4-bit, no fine-tuning. Input: 6-s window (8 frames, longest side 448), stride 3 s, over [0, impact+10 s] (the end bound only limits compute; the model never sees the annotation).
Score: p(Yes) for "does a vehicle collision/crash happen in this clip?". Alarm time = window END. One prompt + one threshold, chosen on 100 VALIDATION clips (train in BOTH splits, so no test clip is
ever used for choosing), frozen, then 300 random clips per test split (seed 0) scored once. Rule: max detection subject to early <= 5 % on validation; else max(detected - 2*early).

Targets = the same B1-B5 as v1/v2 (TARGETS_LOCKED.md), unchanged:
| # | Target | Bar |
|---|---|---|
| B1 | alarm within 10 s after impact, in-distribution test sample | >= 70 % |
| B2 | alarm before impact (window ends before it), in-distribution | <= 5 % |
| B3 | median delay | <= 5 s |
| B4 | geo-aware test sample | >= 60 % detect and <= 8 % early |
| B5 | nothing tuned on test | by construction |
Judged on the point estimate; Wilson 95 % CIs are reported (n=300, about +-5 points); a pass whose CI crosses the bar is called MARGINAL, not a pass.
Reported, not judged: windows/s, per-window p(Yes) on pre-impact windows (false-alarm proxy), day/night and quality breakdowns.
Limits: all-accident clips (no long normal footage, so no false alarms per camera-day); ~80 % US footage; 7B VLM is too heavy to run on every stream, so if it passes it is a confirmer on
triggered windows (candidate for an operator, ADR-006), not a continuous detector.
