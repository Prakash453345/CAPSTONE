"""`EtaCostModel` -- route cost in seconds of emergency-vehicle (EV) time.

The older `RouteCostModel` adds six normalised, weighted terms. Three of them
count congestion again on top of the slower travel time, and one charges
for length a second time. Its signal term is a fixed guess by phase, which
ignores that ITMS preempts the signal for the EV. This model has a single
unit (seconds), so its terms add up to the expected arrival time and need
no weights to balance:

    cost(enter e from f) =  L_e / v_ev,e                              travel
                          + J(f -> e)                                  junction
                          + tau(turn)                                  turn
                          + A_e                                        anomaly
                          + lambda * sigma_e                           reliability

    v_ev,e = v_lim,e * k_ev * (s_e + (1 - s_e) * rho_e)
        s_e     live mean speed / limit (traffic speed fraction)
        rho_e   how freely traffic can move aside for the EV:
                rho_0 + rho_lane * (lanes - 1), capped at 1
        k_ev    EV speed factor over the limit

    queue Q_f = halting_f * h / lanes_f * (1 - rho_f)   seconds the EV spends
                                                        behind the queue on f
    J(f -> e) = signalised and preemptable:  max(0, t0 + Q_f - T_lead) + c_x
                signalised, no preemption:   W(phase) + Q_f
                unsignalised:                Q_f + c_y
        T_lead  how early ITMS turns the EV's signal green (the corridor's
                prepare lead). If the queue clears before the EV arrives,
                the junction costs only the crossing time c_x.

    A_e = (severity_penalty - 1) * L_e / v_ev,e + impact * anomaly_impact_s
    sigma_e = (L_e / v_ev,e) * min(1, 2 * sqrt(congestion_variance))

Admissible A* heuristic: straight-line distance / (v_max * k_ev). Every term
is >= 0 and travel >= L / (v_max * k_ev), so the heuristic never
overestimates the remaining cost.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sim_service.routing.cost import EdgeConditions, EdgeCostParts
from sim_service.routing.graph import EdgeInfo, GraphEdge, RoadGraph


@dataclass(frozen=True)
class EtaCostConfig:
    ev_speed_factor: float = 1.2      # k_ev
    rho_single_lane: float = 0.15     # rho_0
    rho_per_extra_lane: float = 0.25  # rho_lane
    min_ev_speed_mps: float = 1.5
    headway_s: float = 2.0            # h, saturation headway per lane
    startup_s: float = 2.0            # t0, queue start-up loss
    crossing_s: float = 1.5           # c_x, crossing a preempted junction
    yield_s: float = 1.0              # c_y, unsignalised junction
    preemption: bool = True           # ITMS can preempt signalised junctions
    preempt_lead_s: float = 15.0      # T_lead (= corridor_prepare_lead_s)
    wait_by_phase_s: tuple[tuple[str, float], ...] = (
        ("green", 2.0), ("yellow", 6.0), ("red", 22.0), ("unknown", 12.0),
    )
    # turn penalties; "cross" = the turn across the opposing stream
    # (right when driving on the left, left when driving on the right)
    turn_straight_s: float = 0.0
    turn_near_s: float = 2.0
    turn_cross_s: float = 4.0
    turn_uturn_s: float = 15.0
    severity_penalty: tuple[tuple[str, float], ...] = (
        ("low", 1.25), ("medium", 2.0), ("high", 4.0), ("blocked", 10.0),
    )
    anomaly_impact_s: float = 60.0
    reliability_lambda: float = 0.5
    # reroute only when it saves this much: max(abs, frac * new ETA) + switch cost
    reroute_min_saving_s: float = 15.0
    reroute_min_saving_frac: float = 0.10
    reroute_switch_cost_s: float = 5.0


class EtaCostModel:
    def __init__(self, config: EtaCostConfig | None = None, *, lefthand: bool = False):
        self.config = config or EtaCostConfig()
        self.lefthand = lefthand
        self._wait = dict(self.config.wait_by_phase_s)
        self._sev = dict(self.config.severity_penalty)

    # ---- pieces ---------------------------------------------------

    def rho(self, edge: EdgeInfo) -> float:
        c = self.config
        return min(1.0, c.rho_single_lane + c.rho_per_extra_lane * max(0, edge.num_lanes - 1))

    def ev_speed(self, edge: EdgeInfo, cond: EdgeConditions) -> float:
        s = cond.mean_speed_frac
        if s is None:
            s = 1.0 - 0.7 * min(1.0, max(0.0, cond.congestion))
        s = min(1.0, max(0.0, s))
        r = self.rho(edge)
        v = edge.speed_limit_mps * self.config.ev_speed_factor * (s + (1.0 - s) * r)
        return max(self.config.min_ev_speed_mps, v)

    def queue_s(self, edge: EdgeInfo | None, cond: EdgeConditions | None) -> float:
        if edge is None or cond is None or cond.halting <= 0:
            return 0.0
        return cond.halting * self.config.headway_s / max(1, edge.num_lanes) * (
            1.0 - self.rho(edge)
        )

    def turn_s(self, turn: str) -> float:
        c = self.config
        t = (turn or "s").lower()
        if t == "s":
            return c.turn_straight_s
        if t == "t":
            return c.turn_uturn_s
        cross = "r" if self.lefthand else "l"
        return c.turn_cross_s if t == cross else c.turn_near_s

    def junction_s(
        self,
        ge: GraphEdge | None,
        from_edge: EdgeInfo | None,
        from_cond: EdgeConditions | None,
        cond: EdgeConditions,
    ) -> float:
        c = self.config
        q = self.queue_s(from_edge, from_cond)
        signalised = (ge.signalised if ge is not None else False) or cond.entry_is_signalised
        if not signalised:
            return q + (c.yield_s if ge is not None else 0.0)
        if c.preemption:
            return max(0.0, c.startup_s + q - c.preempt_lead_s) + c.crossing_s
        phase = cond.entry_signal_phase or "unknown"
        return self._wait.get(phase, self._wait.get("unknown", 12.0)) + q

    # ---- the RouteCostModel interface --------------------------------

    def edge_cost(
        self,
        edge: EdgeInfo,
        cond: EdgeConditions | None,
        ge: GraphEdge | None = None,
        from_edge: EdgeInfo | None = None,
        from_cond: EdgeConditions | None = None,
    ) -> EdgeCostParts:
        c = self.config
        cond = cond or EdgeConditions()
        travel = edge.length_m / self.ev_speed(edge, cond)
        junction = self.junction_s(ge, from_edge, from_cond, cond)
        turn = self.turn_s(ge.turn) if ge is not None else 0.0
        anomaly = 0.0
        if cond.has_active_anomaly:
            pen = self._sev.get(cond.anomaly_severity or "", 1.0)
            if not math.isfinite(pen):
                pen = self._sev.get("blocked", 10.0)
            anomaly = max(0.0, pen - 1.0) * travel + min(1.0, max(0.0, cond.anomaly_impact)) * (
                c.anomaly_impact_s
            )
        sigma = travel * min(1.0, 2.0 * math.sqrt(max(0.0, cond.congestion_variance)))
        rel = c.reliability_lambda * sigma
        total = travel + junction + turn + anomaly + rel
        return EdgeCostParts(
            travel_time_s=travel,
            congestion_cost=0.0,
            anomaly_cost=anomaly,
            signal_delay_s=junction + turn,
            disruption_cost=0.0,
            reliability_cost=rel,
            weighted_total=total,
        )

    def heuristic(self, graph: RoadGraph, target: str):
        """Admissible lower bound (seconds) from the end of an edge to `target`."""
        v_max = max((e.speed_limit_mps for e in graph.edges.values()), default=13.9)
        v_max *= self.config.ev_speed_factor
        tx, ty = graph.edges[target].start_xy

        def h(edge_id: str) -> float:
            ex, ey = graph.edges[edge_id].end_xy
            # 0.9: lane lengths leave out junction interiors, so keep a margin
            return 0.9 * math.hypot(ex - tx, ey - ty) / v_max

        return h


def should_reroute(current_s: float, alternative_s: float, config: EtaCostConfig) -> bool:
    """Switch only if the saving beats a margin plus the cost of switching
    (cancelling granted preemptions, new ones to set up). The margin stops
    the route flip-flopping on noisy live data."""
    margin = max(config.reroute_min_saving_s, config.reroute_min_saving_frac * alternative_s)
    return current_s - alternative_s > margin + config.reroute_switch_cost_s
