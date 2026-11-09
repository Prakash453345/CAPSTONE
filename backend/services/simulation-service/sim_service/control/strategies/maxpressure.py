"""Plain max-pressure (Varaiya 2013), the baseline CC-A-CAMP builds on.

Paper-A baseline, added 2026-10-28. Deliberately the textbook rule and
nothing of CC-A-CAMP's: no anticipation, no green ceiling, no gap-out, no
demand memory, no switching cost.

    pressure(p) = sum over movements m shown green in p of
                  s_m * (q_in(m) - q_out(m))

`q_in` is the halted queue on m's approach lanes (`ctx.queue_pcu`), `q_out`
the halted queue on its receiving lanes (`ctx.receiving_queue_pcu`), `s_m`
the movement's saturation flow. Each phase is held for a fixed slot (at
least its minimum green, `slot_s`), after which the phase with the highest
pressure is chosen; ties keep the current phase.

One safety addition, shared by every controller in the benchmark: a
movement close to the junction's I5 maximum-wait bound is served first (the
same margin rule as CC-A-CAMP, `acamp._wait_margin_s`). Without it the
safety kernel rejects the plan and forces all-red, which would count as an
interlock violation against the baseline for a reason unrelated to its
decision rule. Recorded in the decision stats as `i5_guard`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from itms_domain import JunctionContext, PlanStep, SignalPlan, Tier0Config

from .acamp import _wait_margin_s


@dataclass
class MaxPressure:
    slot_s: float = 10.0
    tick_s: float = 1.0
    stats: dict[str, int] = field(default_factory=dict)

    def _count(self, k: str) -> None:
        self.stats[k] = self.stats.get(k, 0) + 1

    def pressure(self, cfg: Tier0Config, ctx: JunctionContext, p: str) -> float:
        total = 0.0
        for m in cfg.phases[p].green_movements:
            s = cfg.sat_flow_pcu_s.get(m, 0.5)
            total += s * (ctx.queue_pcu.get(m, 0.0) - ctx.receiving_queue_pcu.get(m, 0.0))
        return total

    def __call__(self, cfg: Tier0Config, ctx: JunctionContext) -> SignalPlan:
        cur = ctx.current_phase_id
        el = ctx.current_phase_elapsed_s
        hold = PlanStep(phase_id=cur, green_s=self.tick_s)
        live = [p for p in cfg.ring_order if p not in ctx.faulted_phases]
        if cur not in ctx.faulted_phases and el < max(cfg.min_green_s.get(cur, 0.0), self.slot_s):
            return SignalPlan(cfg.intersection_id, (hold,), source="maxpressure")
        margin = _wait_margin_s(cfg)
        urgent = []
        for p in live:
            ms = [cfg.max_wait_s - ctx.wait_times_s.get(m, 0.0)
                  for m in cfg.phases[p].green_movements if ctx.has_demand.get(m, False)]
            if ms and min(ms) <= margin:
                urgent.append((min(ms), p))
        if urgent:
            target = min(urgent)[1]
            if target != cur:
                self._count("i5_guard")
        elif live:
            best = max(live, key=lambda p: (self.pressure(cfg, ctx, p), p == cur))
            target = cur if (cur in live and self.pressure(cfg, ctx, cur)
                             >= self.pressure(cfg, ctx, best)) else best
        else:
            target = cur
        if target == cur and cur not in ctx.faulted_phases:
            return SignalPlan(cfg.intersection_id, (hold,), source="maxpressure")
        self._count("switch")
        green_s = 0.0 if cur in ctx.faulted_phases else max(
            self.tick_s, cfg.min_green_s.get(cur, 0.0) - el)
        return SignalPlan(cfg.intersection_id, (
            PlanStep(cur, green_s, cfg.yellow_s, cfg.all_red_s),
            PlanStep(target, cfg.min_green_s.get(target, 0.0)),
        ), source="maxpressure")
