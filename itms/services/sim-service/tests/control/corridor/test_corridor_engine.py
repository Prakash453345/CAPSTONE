"""Green Corridor Engine -- corridor-scope behaviour: arbitration, track
ageing, lead time, budget ledger, and the two pressure terms.

The arbitration group is the reason this file exists separately from
`test_corridor_junction.py`. D1 (two emergency vehicles, conflicting
approaches, within a second of each other) is the single most dangerous
scenario in the EVP literature and the one the standards specify least;
D7 records that the sources actively contradict each other about which
direction a precedence numbering runs, and that the recommended
mitigation is to bench-test every pairwise combination rather than trust
any document. `test_every_class_pair_has_a_stated_winner` is that bench
test.
"""

from __future__ import annotations

import itertools

from itms_domain import JunctionContext, Phase, Tier0Config
from sim_service.control.corridor import (
    CorridorConfig,
    CorridorEngine,
    DebtLedger,
    PreemptionClass,
    VehicleReport,
)
from sim_service.control.safety import interlocks
from sim_service.control.strategies import acamp


def _config(intersection_id: str = "J1") -> Tier0Config:
    phases = {
        "P0": Phase("P0", frozenset({"m0"})),
        "P1": Phase("P1", frozenset({"m1"})),
    }
    return Tier0Config(
        intersection_id=intersection_id,
        phases=phases,
        ring_order=("P0", "P1"),
        conflict_matrix={"m0": frozenset({"m1"}), "m1": frozenset({"m0"})},
        min_green_s={"P0": 10.0, "P1": 10.0},
        max_green_s={"P0": 90.0, "P1": 90.0},
        yellow_s=6.0,
        all_red_s=2.0,
        max_wait_s=250.0,
        sat_flow_pcu_s={"m0": 0.5, "m1": 0.5},
    )


def _ctx(cfg: Tier0Config, **kwargs) -> JunctionContext:
    base = dict(
        intersection_id=cfg.intersection_id,
        current_phase_id="P0",
        current_phase_elapsed_s=30.0,
    )
    base.update(kwargs)
    return JunctionContext(**base)


def _report(
    vehicle_id: str,
    now_s: float,
    *,
    junctions=("J1",),
    distance_m: float = 60.0,
    speed_mps: float = 10.0,
    movement: str = "m1",
    response_id: str | None = None,
) -> VehicleReport:
    return VehicleReport(
        vehicle_id=vehicle_id,
        observed_at_s=now_s,
        route=tuple(junctions),
        distance_to_m=dict.fromkeys(junctions, distance_m),
        speed_mps=speed_mps,
        movement_at=dict.fromkeys(junctions, movement),
        response_id=response_id,
    )


def _engine(**kwargs) -> CorridorEngine:
    engine = CorridorEngine(CorridorConfig(**kwargs))
    for name, klass in (
        ("FIRE1", PreemptionClass.FIRE),
        ("FIRE2", PreemptionClass.FIRE),
        ("AMB1", PreemptionClass.AMBULANCE),
        ("POL1", PreemptionClass.POLICE),
        ("BUS1", PreemptionClass.TRANSIT),
        ("RAIL1", PreemptionClass.RAIL),
    ):
        engine.authorize(name, klass)
    return engine


def _feed(engine: CorridorEngine, reports, now_s: float) -> None:
    for report in reports:
        engine.submit(report)
    engine.begin_tick(now_s)


# ---------------------------------------------------------------------
# Request integrity
# ---------------------------------------------------------------------


def test_an_unauthorized_vehicle_id_cannot_assert_a_class():
    """E13. Homemade infrared transmitters reproducing a vendor's
    pulse-length-modulated protocol are demonstrated, not theoretical --
    an Arduino Nano and an LED array -- and the legal deterrent (SAFETEA,
    August 2005) is deterrence, not prevention. So class is looked up
    from an authorization table rather than taken from the request, and
    the rejection is counted so it can be audited (H2)."""
    engine = _engine()
    assert engine.submit(_report("MIRT-KIDDIE", 0.0)) is False
    assert engine.counters["unauthorized"] == 1
    engine.begin_tick(0.0)
    assert engine.propose(_config(), _ctx(_config())) is None


def test_a_request_must_persist_before_it_is_honoured():
    """E8. St. Paul's two-second dwell requirement for call acceptance,
    adopted specifically "to reduce the number of inadvertent preemptions
    triggered when preemption equipped vehicles make turns in areas with
    closely spaced parallel streets" -- a turning vehicle sweeps its
    emitter across detectors for junctions it never intends to use."""
    cfg = _config()
    engine = _engine(acceptance_dwell_s=2.0)
    _feed(engine, [_report("FIRE1", 0.0)], 0.0)
    assert engine.propose(cfg, _ctx(cfg)) is None, "accepted a call that had not persisted"
    _feed(engine, [_report("FIRE1", 1.0)], 1.0)
    assert engine.propose(cfg, _ctx(cfg)) is None
    _feed(engine, [_report("FIRE1", 2.0)], 2.0)
    assert engine.propose(cfg, _ctx(cfg)) is not None


def test_a_track_that_goes_quiet_is_released_not_coasted():
    """E10, the failure route-based preemption takes on that point
    detection is structurally immune to: a corridor held for an ETA that
    expired while nobody was looking. WSDOT names the converse limitation
    of the legacy design in the same breath -- "point detection systems
    cannot recognize speed changes or stops before intersection arrival"
    -- and the pair is the real tradeoff between reacting late and
    committing to a prediction."""
    cfg = _config()
    engine = _engine(report_ttl_s=6.0)
    for t in (0.0, 1.0, 2.0, 3.0):
        _feed(engine, [_report("FIRE1", t)], t)
    assert engine.propose(cfg, _ctx(cfg)) is not None
    assert engine.active_at("J1")
    engine.begin_tick(10.0)  # nothing new submitted
    assert not engine.active_at("J1")
    assert engine.propose(cfg, _ctx(cfg)) is None


def test_a_stopped_vehicle_releases_its_corridor():
    """E7 at the scene: an emergency vehicle parked within detection
    range with its emitter live. FHWA's own statement of the consequence
    is that the signal is held "indefinitely, causing significant traffic
    problems" -- at an incident, which is exactly when the surrounding
    network most needs to keep working. The grace period is what tells
    that apart from a vehicle momentarily held in the queue it is about
    to be given a green through."""
    cfg = _config()
    engine = _engine(stopped_grace_s=5.0, stopped_speed_mps=1.0)
    for t in (0.0, 1.0, 2.0, 3.0):
        _feed(engine, [_report("FIRE1", t)], t)
    assert engine.active_at("J1") or engine.propose(cfg, _ctx(cfg)) is not None
    for t in range(4, 30):
        _feed(engine, [_report("FIRE1", float(t), speed_mps=0.0)], float(t))
    assert engine.propose(cfg, _ctx(cfg)) is None
    assert not engine.active_at("J1")


def test_a_route_that_shortens_releases_the_junctions_it_dropped():
    """G4: preemption of junctions the vehicle never traverses is pure
    cost with no benefit, and multiplied across every call it is where
    public tolerance for EVP is spent. Released on the tick the route
    changes rather than on a timeout."""
    cfg1, cfg2 = _config("J1"), _config("J2")
    engine = _engine()
    for t in (0.0, 1.0, 2.0, 3.0):
        _feed(engine, [_report("FIRE1", t, junctions=("J1", "J2"))], t)
    engine.propose(cfg1, _ctx(cfg1))
    engine.propose(cfg2, _ctx(cfg2))
    assert engine.active_at("J2")
    _feed(engine, [_report("FIRE1", 4.0, junctions=("J1",))], 4.0)
    assert not engine.active_at("J2"), "held a junction the vehicle has left the route for"
    assert engine.propose(cfg2, _ctx(cfg2)) is None


# ---------------------------------------------------------------------
# Arbitration -- D1, D6, D7, G5
# ---------------------------------------------------------------------


def test_the_last_junction_of_a_route_releases_as_passed_not_as_stale():
    """The end of a response is not a lost vehicle, and the release
    reason has to be able to tell them apart.

    Found by giving the emergency vehicles a real destination. Until then
    the benchmark route ran off the bounding box, and `ev_detection`
    stopped submitting reports the moment no junctions remained ahead --
    so the *final* junction of every response released on `report_ttl_s`
    with reason `stale_report`, 41 of 281 releases over the recorded
    medium gate. Nothing unsafe: the bounded release is exactly the
    mechanism for a track that goes quiet, and it fired correctly. But
    the junction stayed held for the whole timeout after the vehicle had
    cleared it, and the release-reason distribution -- which exists to
    answer "is this working" -- was reporting a detection failure on
    every single successful response.

    A report whose route is empty is not an absent report. It says the
    true thing, the whole previous route has been driven, and the
    positional rule in `_Track.dropped_by_passing` reads a fully-dropped
    prefix as a passage."""
    cfg = _config()
    engine = _engine(report_ttl_s=6.0)
    for t in (0.0, 1.0, 2.0, 3.0):
        _feed(engine, [_report("FIRE1", t)], t)
    assert engine.propose(cfg, _ctx(cfg)) is not None
    assert engine.active_at("J1")

    # The vehicle is through: still observed, no junctions left ahead.
    _feed(engine, [_report("FIRE1", 4.0, junctions=())], 4.0)
    assert not engine.active_at("J1")
    stats = engine.stats()
    assert stats.get("release_passed", 0) == 1
    assert stats.get("release_stale_report", 0) == 0, (
        "a completed response was counted as a lost vehicle"
    )


def test_every_class_pair_has_a_stated_winner():
    """D7's bench test, in code.

    The catalogue's warning is that the sources contradict each other:
    the NEMA TS2 specification says low-numbered preemptors override
    higher-numbered, and Florida LTAP's course material says the
    opposite. A designer who assumes the wrong one inverts the entire
    safety hierarchy, and ITS lessons-learned records that exact failure
    reaching deployment -- transit priority granted equal precedence to
    emergency preemption. The mitigation the literature gives is to
    bench-test every pairwise combination rather than trust any document.

    So every ordered pair is enumerated here and its winner asserted
    against MUTCD 11th Ed. §4F.18's Guidance order, whose rationale is
    controllability rather than urgency: "a vehicle that is more
    difficult to control supersedes" one that is easier."""
    expected = [
        PreemptionClass.RAIL,
        PreemptionClass.FIRE,
        PreemptionClass.AMBULANCE,
        PreemptionClass.POLICE,
        PreemptionClass.LIGHT_RAIL,
        PreemptionClass.TRANSIT,
    ]
    names = {c: f"V{i}" for i, c in enumerate(expected)}
    for a, b in itertools.permutations(expected, 2):
        cfg = _config()
        engine = CorridorEngine(CorridorConfig(acceptance_dwell_s=0.0))
        engine.authorize(names[a], a)
        engine.authorize(names[b], b)
        # Deliberately submitted lower-priority-first, so a
        # first-come-first-served implementation would produce the wrong
        # answer and be caught rather than accidentally agreeing.
        first, second = (b, a) if int(a) < int(b) else (a, b)
        _feed(
            engine,
            [_report(names[first], 0.0), _report(names[second], 0.0)],
            0.0,
        )
        engine.propose(cfg, _ctx(cfg))
        winner = min(a, b, key=int)
        held = engine._junctions["J1"].reservation  # noqa: SLF001
        assert held is not None
        assert held.priority is winner, (
            f"{a.name} vs {b.name}: expected {winner.name}, got {held.priority.name}"
        )


def test_an_equal_priority_tie_is_broken_deterministically():
    """D1's scenario with the classes equal. The answer is arbitrary --
    two fire appliances have equal claim -- but it must be the *same*
    arbitrary answer every time, because a tie-break that falls through
    to dictionary ordering is a tie-break that can differ between two
    runs of the same input, and this is the scenario that produced the
    1972 St. Paul fatality. The loser is not dropped: it gets a flashing
    confirmation, which is the signal the crew is trained to yield on."""
    cfg = _config()
    for order in ([("FIRE1", "FIRE2")], [("FIRE2", "FIRE1")]):
        engine = _engine(acceptance_dwell_s=0.0)
        _feed(engine, [_report(v, 0.0) for v in order[0]], 0.0)
        engine.propose(cfg, _ctx(cfg))
        held = engine._junctions["J1"].reservation  # noqa: SLF001
        assert held is not None and held.vehicle_id == "FIRE1"


def test_first_seen_wins_within_a_class():
    """NEMA TS2's rule for equal-priority calls, served in the order
    received. Safe here only because no call is permanent: a track
    expires on `report_ttl_s` and a dwell on `max_dwell_s`, so D6's
    failure -- a continuously asserted call starving an equal-priority
    one forever -- has no way to arise."""
    cfg = _config()
    engine = _engine(acceptance_dwell_s=0.0)
    _feed(engine, [_report("FIRE2", 0.0)], 0.0)
    _feed(engine, [_report("FIRE1", 5.0), _report("FIRE2", 5.0)], 5.0)
    engine.propose(cfg, _ctx(cfg))
    held = engine._junctions["J1"].reservation  # noqa: SLF001
    assert held is not None and held.vehicle_id == "FIRE2"


def test_a_multi_unit_response_is_one_interruption_per_junction():
    """G5. A multi-alarm response puts several units on converging routes
    over a few minutes; treated as N independent requests that is N
    sequential preemptions with no recovery between them (F8), which is
    how a corridor spends an entire peak in transition. Units sharing a
    dispatch response are one claimant."""
    cfg = _config()
    engine = _engine(acceptance_dwell_s=0.0)
    _feed(
        engine,
        [
            _report("FIRE1", 0.0, distance_m=200.0, response_id="INCIDENT-7"),
            _report("FIRE2", 0.0, distance_m=80.0, response_id="INCIDENT-7"),
        ],
        0.0,
    )
    engine.propose(cfg, _ctx(cfg))
    assert engine.counters["coalesced"] == 1
    held = engine._junctions["J1"].reservation  # noqa: SLF001
    assert held is not None and held.vehicle_id == "FIRE2", "nearest unit should represent"


def test_unknown_response_ids_never_merge_with_each_other():
    """`None` means "dispatch did not say", and merging two genuinely
    separate emergencies would hold a junction for a vehicle that is not
    coming."""
    cfg = _config()
    engine = _engine(acceptance_dwell_s=0.0)
    _feed(engine, [_report("FIRE1", 0.0), _report("FIRE2", 0.0)], 0.0)
    engine.propose(cfg, _ctx(cfg))
    assert engine.counters["coalesced"] == 0


def test_one_vehicle_holds_every_junction_on_its_route_at_once():
    """D11. One unit on the arterial and another on a cross street,
    arriving at neighbouring junctions seconds apart: independent
    controllers grant A at junction n and B at n+1, each correct on its
    own information, and A is released into a junction being held
    against it. Arbitration happens once per corridor, from one view of
    the tracks, so the two junctions cannot disagree."""
    engine = _engine(acceptance_dwell_s=0.0)
    cfgs = [_config("J1"), _config("J2"), _config("J3")]
    _feed(engine, [_report("FIRE1", 0.0, junctions=("J1", "J2", "J3"))], 0.0)
    for cfg in cfgs:
        engine.propose(cfg, _ctx(cfg))
    holders = {
        jid: jp.reservation.vehicle_id
        for jid, jp in engine._junctions.items()  # noqa: SLF001
        if jp.reservation is not None
    }
    assert holders == {"J1": "FIRE1", "J2": "FIRE1", "J3": "FIRE1"}


# ---------------------------------------------------------------------
# Lead time -- E1, E2, G2, G3, G4
# ---------------------------------------------------------------------


def test_a_distant_vehicle_does_not_claim_the_junction_yet():
    """G4's other half. The claim is made on lead *time*, not detection
    range: fixed ranges (Fairfax County ~1,600 ft, St. Paul up to ~2,300
    ft for fast-accelerating police vehicles) are proxies for whether the
    junction can be ready in time, and they fail in both directions."""
    cfg = _config()
    engine = _engine(acceptance_dwell_s=0.0, max_lead_s=45.0)
    _feed(engine, [_report("FIRE1", 0.0, distance_m=2000.0, speed_mps=10.0)], 0.0)
    assert engine.propose(cfg, _ctx(cfg)) is None
    _feed(engine, [_report("FIRE1", 1.0, distance_m=60.0, speed_mps=10.0)], 1.0)
    assert engine.propose(cfg, _ctx(cfg)) is not None


def test_a_queue_ahead_of_the_vehicle_lengthens_the_lead_time():
    """G2, the argument for corridor preemption over the reactive kind.
    A preemption granted on arrival gives a green to an approach whose
    queue then has to discharge with the emergency vehicle behind it --
    the vehicle blocked by the traffic its own preemption released. The
    remedy is starting earlier by the queue's discharge time, which is
    computable from what the junction already samples."""
    cfg = _config()
    empty = _ctx(cfg)
    queued = _ctx(cfg, queue_pcu={"m1": 8.0})  # 8 PCU / 0.5 PCU/s = 16 s
    engine_a = _engine(acceptance_dwell_s=0.0, base_lead_s=0.0)
    engine_b = _engine(acceptance_dwell_s=0.0, base_lead_s=0.0)
    far = _report("FIRE1", 0.0, distance_m=250.0, speed_mps=10.0)  # ETA 25 s
    _feed(engine_a, [far], 0.0)
    _feed(engine_b, [far], 0.0)
    assert engine_a.propose(cfg, empty) is None, "claimed with no queue to clear"
    assert engine_b.propose(cfg, queued) is not None, "ignored the queue ahead"


def test_a_loaded_receiving_link_lengthens_the_lead_time_further():
    """G3, short-link coupling: the clearance movement at junction n
    discharges into a link to n+1 that is still red, fills it, and
    gridlocks the junction with the emergency vehicle inside it --
    structurally the Fox River Grove failure with a signal in place of a
    railroad. Handled by starting n earlier so the pair clears in
    sequence, rather than by refusing to open n, which would leave the
    vehicle stopped just as surely."""
    cfg = _config()
    clear = _ctx(cfg, receiving_occupancy={"m1": 0.1}, receiving_queue_pcu={"m1": 6.0})
    blocked = _ctx(cfg, receiving_occupancy={"m1": 0.8}, receiving_queue_pcu={"m1": 6.0})
    far = _report("FIRE1", 0.0, distance_m=200.0, speed_mps=10.0)  # ETA 20 s
    a = _engine(acceptance_dwell_s=0.0, base_lead_s=0.0)
    b = _engine(acceptance_dwell_s=0.0, base_lead_s=0.0)
    _feed(a, [far], 0.0)
    _feed(b, [far], 0.0)
    assert a.propose(cfg, clear) is None
    assert b.propose(cfg, blocked) is not None


def test_latency_margin_shifts_the_trigger_upstream():
    """E2. Li et al.'s compensated-distance strategy for connected-vehicle
    EVP: budget the end-to-end delay from request to controller action
    explicitly and trigger far enough upstream to absorb it, rather than
    discovering it at the stop line."""
    cfg = _config()
    report = _report("FIRE1", 0.0, distance_m=100.0, speed_mps=10.0)  # ETA 10 s
    tight = _engine(acceptance_dwell_s=0.0, latency_margin_s=0.0, base_lead_s=0.0)
    generous = _engine(acceptance_dwell_s=0.0, latency_margin_s=5.0, base_lead_s=0.0)
    _feed(tight, [report], 0.0)
    _feed(generous, [report], 0.0)
    assert tight.propose(cfg, _ctx(cfg)) is None
    assert generous.propose(cfg, _ctx(cfg)) is not None


# ---------------------------------------------------------------------
# The budget ledger -- making a dormant interlock reachable
# ---------------------------------------------------------------------


def test_the_rolling_hour_ledger_accumulates_and_then_forgets():
    """`JunctionContext.preempt_seconds_last_hour` has existed since M2
    and has been zero in every run ever made, so `interlocks.
    preempt_budget_ok` -- written specifically for this requester -- was
    correct and structurally unable to fire. This is the measurement that
    makes it reachable."""
    cfg = _config()
    engine = _engine(acceptance_dwell_s=0.0)
    for t in range(20):
        # Distance chosen so the claim is actually made: with the target
        # phase already green the transfer time is zero, so the lead time
        # collapses to the latency margin alone and the engine correctly
        # declines to claim -- and burn max-dwell and budget -- until the
        # vehicle is at the line. Holding an already-correct green ahead
        # of that is `A(p)`'s job, not preemption's.
        _feed(engine, [_report("FIRE1", float(t), distance_m=5.0)], float(t))
        engine.propose(cfg, _ctx(cfg, current_phase_id="P1"))
    spent = engine.preempt_seconds_last_hour("J1", 20.0)
    assert spent > 0.0
    assert engine.preempt_seconds_last_hour("J1", 20.0 + 3601.0) == 0.0


def test_a_denied_plan_is_never_a_fault_at_the_arbiter():
    """The rung-3 contract, end to end through the real arbiter.

    A preemption plan that fails the interlocks must fall through to the
    strategy below, not command all-red. H1 requires the denial to be
    audible rather than silent, so a `preempt_denied` fault event rides
    along with the successful decision."""
    from sim_service.control.strategies import fixed_time
    from sim_service.signal_controller import arbiter
    from sim_service.signal_controller.cabinet import FakeCabinet

    cfg = _config()
    ctx = _ctx(cfg)

    class AlwaysIllegal:
        def propose(self, cfg_t0, ctx_):
            from itms_domain import PlanStep, SignalPlan

            return SignalPlan(
                intersection_id=cfg_t0.intersection_id,
                steps=(PlanStep("P0", 1.0), PlanStep("P1", 10.0)),  # no clearance
                source="corridor_preemption",
            )

        def denied(self, cfg_t0, ctx_, violations):
            self.violations = violations

        def begin_tick(self, now_s):
            pass

        def preempt_seconds_last_hour(self, junction_id, now_s):
            return 0.0

    requester = AlwaysIllegal()
    decision = arbiter.tick(
        cfg,
        ctx,
        FakeCabinet(),
        strategy=fixed_time.propose,
        corridor=requester,
    )
    assert decision.mode in arbiter.SUCCESS_MODES, "a denial must not become a fault"
    assert decision.plan is not None and decision.plan.source != "corridor_preemption"
    assert any(e.get("fault_type") == "preempt_denied" for e in decision.events)
    assert requester.violations


def test_a_legal_preemption_is_commanded_and_reported_as_success():
    from sim_service.control.strategies import fixed_time
    from sim_service.signal_controller import arbiter
    from sim_service.signal_controller.cabinet import FakeCabinet

    cfg = _config()
    engine = _engine(acceptance_dwell_s=0.0)
    _feed(engine, [_report("FIRE1", 0.0, distance_m=50.0)], 0.0)
    cabinet = FakeCabinet()
    decision = arbiter.tick(
        cfg, _ctx(cfg), cabinet, strategy=fixed_time.propose, corridor=engine
    )
    assert decision.mode == "corridor_preemption"
    assert decision.plan is not None and decision.plan.source == "corridor_preemption"
    assert interlocks.check(decision.plan, _ctx(cfg), cfg) == []


# ---------------------------------------------------------------------
# Pressure terms A(p) and D(p)
# ---------------------------------------------------------------------


def test_anticipation_is_identically_zero_with_no_response_running():
    """The property that makes the term's effect attributable: on every
    ordinary tick the controller is bit-for-bit its M5 self."""
    cfg = _config()
    ctx = _ctx(cfg, queue_pcu={"m0": 4.0, "m1": 4.0})
    acfg = acamp.AcampConfig()
    for phase in ("P0", "P1"):
        assert acamp.anticipation(cfg, ctx, acfg, phase, {}) == 0.0
        assert acamp.pressure(cfg, ctx, acfg, phase) == acamp.pressure(
            cfg, ctx, acfg, phase, {}, {}
        )


def test_anticipation_promotes_the_path_ahead_of_the_vehicle():
    cfg = _config()
    ctx = _ctx(cfg, queue_pcu={"m0": 4.0, "m1": 4.0})
    acfg = acamp.AcampConfig(lambda_anticipation=1.0)
    base = acamp.pressure(cfg, ctx, acfg, "P1")
    boosted = acamp.pressure(cfg, ctx, acfg, "P1", {"m1": 1.0}, {})
    assert boosted > base
    assert boosted == base + 0.5 * 1.0 * 4.0


def test_anticipation_cannot_invent_a_reason_to_serve_an_empty_approach():
    """The term is a multiplier on discharge benefit, not an additive
    bonus. A movement with nothing waiting scores zero however imminent
    the arrival -- which is what stops `A(p)` from reproducing M4's
    `S(p)` failure, a constant deciding a comparison that scales."""
    cfg = _config()
    ctx = _ctx(cfg, queue_pcu={"m0": 6.0})
    acfg = acamp.AcampConfig(lambda_anticipation=5.0)
    assert acamp.anticipation(cfg, ctx, acfg, "P1", {"m1": 1.0}) == 0.0


def test_debt_is_incurred_by_the_movements_a_preemption_stops():
    """H9: the cost is not paid by the network, it is paid by an
    identifiable set of movements, and the same ones every time.
    Recorded per movement so it can be reported as a distribution rather
    than averaged into a corridor mean."""
    cfg = _config()
    engine = _engine(acceptance_dwell_s=0.0)
    for t in range(10):
        _feed(engine, [_report("FIRE1", float(t), distance_m=5.0)], float(t))
        engine.propose(cfg, _ctx(cfg, current_phase_id="P1"))
    assert engine.debt.owed("J1", "m0") > 0.0
    assert engine.debt.owed("J1", "m1") == 0.0, "the served movement was not stopped"
    assert engine.debt.report()["J1/m0"] > 0.0


def test_debt_decays_so_repayment_ends():
    """The decay is what keeps it a repayment rather than a grudge.
    Without one, a movement near a fire station accumulates unbounded
    priority and the controller optimises the corridor for the cross
    street of its busiest EVP junction."""
    ledger = DebtLedger(half_life_s=10.0)
    ledger.incur("J1", ["m0"], 20.0)
    ledger.decay_to(10.0)
    assert abs(ledger.owed("J1", "m0") - 10.0) < 1e-6
    ledger.decay_to(30.0)
    assert abs(ledger.owed("J1", "m0") - 2.5) < 1e-6
    ledger.decay_to(1000.0)
    assert ledger.owed("J1", "m0") == 0.0
    assert ledger.report()["J1/m0"] == 20.0, "the raw total must survive decay"


def test_debt_raises_pressure_without_a_live_queue():
    """Deliberately asymmetric with `A(p)`. A movement held on red long
    enough for its own arrivals to divert to parallel streets (G6) is
    still owed the service, precisely because the demand it lost is
    invisible to any live measurement."""
    cfg = _config()
    ctx = _ctx(cfg)
    acfg = acamp.AcampConfig(lambda_debt=0.5)
    # 15 s owed against a 60 s phase horizon: a quarter of a green lost.
    assert acamp.pressure(cfg, ctx, acfg, "P0", {}, {"m0": 15.0}, 60.0) == (
        0.5 * 0.5 * 0.25
    )


def test_debt_saturates_at_one_lost_green():
    """The clip that keeps `D(p)` from reproducing M4's `S(p)`.

    Raw seconds times saturation flow is dimensionally PCU and was
    argued for on exactly that basis -- but dimensional agreement is not
    magnitude agreement. Debt accrues one second per tick for every
    movement a preemption holds, so a 20-second preemption at the
    corridor's biggest junction produced `D(p) = 44.9` against a
    `pressure_scale` whose median at decision ticks is 0.21. The M7 gate
    measured the result: the full corridor arm lost to plain reactive
    preemption on both axes at once.

    Clipped, `D(p)` is bounded by `λ_D · Σ_m s_m` however long anything
    has been held -- the same bound `fairness` gets from clipping
    `wait / max_wait`, and the reason fairness has never had this
    failure."""
    cfg = _config()
    acfg = acamp.AcampConfig(lambda_debt=0.5)
    bound = 0.5 * 0.5  # lambda_D * sat_flow of the single movement in P0
    for owed in (60.0, 600.0, 6000.0):
        assert acamp.debt_recovery(cfg, acfg, "P0", {"m0": owed}, 60.0) == bound


def test_low_confidence_shortens_the_commitment_but_never_refuses_it():
    """E14/E11/E4. Degraded detection is the normal condition of a real
    corridor, not an exception -- GPS is worst where junctions are
    densest, an optical receiver loses a genuine signal to heavy rain or
    direct sun, and a truck breaks line of sight for seconds at a time.

    So low confidence is never grounds to refuse an emergency request,
    and always grounds to commit less: claim later, hold shorter. This
    test exists because the claim was in `VehicleReport.confidence`'s
    docstring before it was in the code -- the field was documented as
    shortening the commitment horizon and was never read."""
    cfg = _config()
    far = dict(distance_m=300.0, speed_mps=10.0)  # ETA 30 s

    def engine_with(confidence: float) -> CorridorEngine:
        engine = _engine(acceptance_dwell_s=0.0, max_lead_s=45.0, confidence_floor=0.4)
        report = _report("FIRE1", 0.0, **far)
        engine.submit(
            VehicleReport(
                vehicle_id=report.vehicle_id,
                observed_at_s=0.0,
                route=report.route,
                distance_to_m=report.distance_to_m,
                speed_mps=report.speed_mps,
                movement_at=report.movement_at,
                confidence=confidence,
            )
        )
        engine.begin_tick(0.0)
        return engine

    # A queue that makes the computed lead time exceed max_lead_s, so the
    # ceiling -- and therefore the confidence scaling of it -- is what
    # decides.
    queued = _ctx(cfg, queue_pcu={"m1": 30.0})
    assert engine_with(1.0).propose(cfg, queued) is not None
    assert engine_with(0.5).propose(cfg, queued) is None, "full commitment on a poor fix"

    # Still served, just later: closer in, the degraded track claims too.
    engine = _engine(acceptance_dwell_s=0.0, confidence_floor=0.4)
    engine.submit(
        VehicleReport(
            vehicle_id="FIRE1",
            observed_at_s=0.0,
            route=("J1",),
            distance_to_m={"J1": 60.0},
            speed_mps=10.0,
            movement_at={"J1": "m1"},
            confidence=0.5,
        )
    )
    engine.begin_tick(0.0)
    assert engine.propose(cfg, _ctx(cfg)) is not None, "refused a degraded request outright"


def test_the_confidence_floor_keeps_a_commitment_long_enough_to_use():
    """Below the floor the claim window gets shorter than a right-of-way
    transfer, which spends the entry cost and never reaches the dwell --
    the worst of both."""
    cfg = _config()
    engine = _engine(acceptance_dwell_s=0.0, confidence_floor=0.4, max_dwell_s=40.0)
    engine.submit(
        VehicleReport(
            vehicle_id="FIRE1",
            observed_at_s=0.0,
            route=("J1",),
            distance_to_m={"J1": 30.0},
            speed_mps=10.0,
            movement_at={"J1": "m1"},
            confidence=0.0,
        )
    )
    engine.begin_tick(0.0)
    assert engine.propose(cfg, _ctx(cfg)) is not None
    held = engine._junctions["J1"].reservation  # noqa: SLF001
    assert held is not None
    assert held.expires_at_s == 40.0 * 0.4


def test_the_base_lead_is_a_floor_under_the_computed_terms():
    """The floor the M7 ablation forced into existence.

    `transfer + discharge + downstream + latency` is a *lower bound on
    sufficiency*, not a target: it is the least advance at which the
    junction could possibly be ready, and triggering on it leaves no
    margin for the ETA error that is guaranteed to exist. Measured with
    both pressure terms zeroed so only the trigger differed, that cost
    the emergency vehicle +111.5 s of travel time [+93.5, +129.5]
    against a plain 300 m fixed range.

    The computed terms still do their job -- they *raise* the lead above
    the floor when a queue has to be dissipated or a short downstream
    link cleared. They just no longer set it on their own."""
    cfg = _config()
    ctx = _ctx(cfg)  # nothing queued: computed lead is yellow + all-red + latency = 9 s
    report = _report("FIRE1", 0.0, distance_m=150.0, speed_mps=10.0)  # ETA 15 s

    without = _engine(acceptance_dwell_s=0.0, base_lead_s=0.0)
    _feed(without, [report], 0.0)
    assert without.propose(cfg, ctx) is None

    withfloor = _engine(acceptance_dwell_s=0.0, base_lead_s=20.0)
    _feed(withfloor, [report], 0.0)
    assert withfloor.propose(cfg, ctx) is not None

    # And the ceiling still binds: the floor cannot claim the corridor
    # minutes ahead for a vehicle that may turn off it (G4).
    distant = _engine(acceptance_dwell_s=0.0, base_lead_s=20.0, max_lead_s=45.0)
    _feed(distant, [_report("FIRE1", 0.0, distance_m=2000.0, speed_mps=10.0)], 0.0)
    assert distant.propose(cfg, ctx) is None


def test_debt_is_extinguished_by_actually_serving_the_movement():
    """The distinction `D(p)` exists to make, and could not make before
    `repay` existed: owed, versus already repaid.

    With only time-decay, a movement served ten times carried the same
    debt as one never served at all, and a 120 s half-life meant debt
    from a preemption at t=300 outlived the scenario. Instrumented on one
    seed, `D(p)` was non-zero on 82.9% of ticks -- a persistent
    phase-asymmetric bias underneath every decision, which is M4's `S(p)`
    failure arrived at from the other direction."""
    ledger = DebtLedger(half_life_s=1e9)  # decay effectively off
    ledger.incur("J1", ["m0", "m1"], 10.0)
    assert ledger.owed("J1", "m0") == 10.0
    ledger.repay("J1", ["m0"], 4.0)
    assert ledger.owed("J1", "m0") == 6.0
    assert ledger.owed("J1", "m1") == 10.0, "repaying one movement must not touch another"
    ledger.repay("J1", ["m0"], 6.0)
    assert ledger.owed("J1", "m0") == 0.0, "fully repaid debt must clear, not linger"
    ledger.repay("J1", ["m0"], 100.0)
    assert ledger.owed("J1", "m0") == 0.0, "over-repayment must not go negative"
    assert ledger.report()["J1/m0"] == 10.0, "the raw total must survive repayment"


def test_the_engine_repays_from_ordinary_green_not_only_while_preempting():
    """Most of the seconds that settle a debt are ordinary green from the
    ordinary controller, long after the preemption ended. A repayment
    hook that only fired while a preemption was running would never
    settle anything, so it sits before every early return in `propose`."""
    cfg = _config()
    engine = _engine(acceptance_dwell_s=0.0)
    for t in range(10):
        _feed(engine, [_report("FIRE1", float(t), distance_m=5.0)], float(t))
        engine.propose(cfg, _ctx(cfg, current_phase_id="P1"))
    owed = engine.debt.owed("J1", "m0")
    assert owed > 0.0

    # Emergency vehicle gone. The first few ticks still carry a live
    # track -- `report_ttl_s` is 6 s and the last report was at t=9 -- so
    # the preemption keeps running and keeps incurring. Repayment only
    # starts once the reservation releases, which is the point: the debt
    # is settled by ordinary green afterwards, not during.
    for t in range(10, 60):
        engine.begin_tick(float(t))
        engine.propose(cfg, _ctx(cfg, current_phase_id="P0"))
    assert engine.debt.owed("J1", "m0") == 0.0, "green service did not settle the debt"
