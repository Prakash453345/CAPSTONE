"""Watch the Green Corridor Engine work, on one run, with commentary.

`m7_corridor_benchmark.py` answers "does it help, and what does it cost"
over thirty seeds. This answers a different question — "what is it
actually doing right now" — and it is the one you want in front of you
when demonstrating the system or when something looks wrong.

Two modes:

    python scripts/m7_demo.py --gui        watch it in sumo-gui
    python scripts/m7_demo.py              headless, commentary only

The commentary is the point. In the GUI you can see greens open ahead of
the ambulance, but not *why* — whether a junction was claimed on lead
time or held short of one, whether a hold ended because the vehicle
passed or because a bound fired, whether the crew would be seeing a solid
confirmation or a flashing one. Every line below is a decision the engine
made, with the reason it made it.

    [   304s] EV0  CLAIM    1880441740_4393296  eta 17.3s  movement L12, max hold 39s
    [   309s] EV0  HOLD     1880441740_4393296  min_green   [FLASHING]
    [   314s] EV0  CLEARING 1880441740_4393296  yellow + all-red, then P0   [FLASHING]
    [   319s] EV0  GREEN    1880441740_4393296  phase P0   [SOLID]
    [   323s] EV0  RELEASE  1880441740_4393296  passed         junction total 11s preempted

`--arm reactive` runs the field-standard baseline instead, so the two can
be watched side by side; `--arm none` turns preemption off entirely and
shows the ambulance taking its chances with ordinary adaptive control.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import traci

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "experiments"))
sys.path.insert(0, str(_ROOT / "data" / "scenarios" / "networks" / "vijayawada"))

from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
from m5_harness import MAX_STEPS_SAFETY_CAP, NET_PATH, build_acamp, scenario_inputs  # noqa: E402
from m7_corridor_benchmark import (  # noqa: E402
    EV_DEPARTURES_S,
    EV_INCIDENT,
    _Injector,
    build_arm,
    ev_vehicle_ids,
)
from sim_service.control.corridor import Confirmation, PreemptState  # noqa: E402
from sim_service.control.dispatch import should_redispatch  # noqa: E402
from sim_service.control.runner import (  # noqa: E402
    _ensure_sumo_home,
    run_controlled_scenario,
)
from sim_service.signal_controller.ev_detection import (  # noqa: E402
    EmergencyVehicleReporter,
    build_movement_index,
)
from sim_service.signal_controller.ev_routing import traci_route_fn  # noqa: E402


def _short(junction_id: str) -> str:
    """Junction ids on this corridor run to 50 characters of cluster
    naming. The distinguishing part is the first number."""
    return junction_id.replace("cluster_", "")[:18]


class Commentary:
    """Diffs the engine's state each tick and narrates what changed.

    Written as an observer rather than as callbacks inside the engine on
    purpose: a demo is not a reason to put print statements into a safety
    path, and everything it reports is already readable from the engine's
    public state. If a future dashboard needs the same event stream, this
    is the shape it should take -- poll and diff, no hooks in `propose`."""

    def __init__(self, engine, configs, quiet: bool = False) -> None:
        self._engine = engine
        self._configs = configs
        self._quiet = quiet
        self._state: dict[str, tuple] = {}
        self._releases: dict[str, dict] = {}
        """Previous release counters per junction, so a release can be
        attributed to the counter that *moved*. The first version took
        the largest counter instead, which is right only while one reason
        dominates -- it would have reported `passed` for a stale-report
        release the moment `passed` pulled ahead, and the release-reason
        distribution is the whole diagnostic."""
        self.events: list[str] = []

    def _emit(self, now_s: float, vehicle: str, verb: str, junction: str, detail: str) -> None:
        line = f"[{now_s:6.0f}s] {vehicle:4s} {verb:8s} {_short(junction):20s} {detail}"
        self.events.append(line)
        if not self._quiet:
            print(line, flush=True)

    def __call__(self, now_s: float) -> None:
        for junction_id, jp in self._engine._junctions.items():  # noqa: SLF001
            cfg = self._configs.get(junction_id)
            reservation = jp.reservation
            key = (
                reservation.vehicle_id if reservation else None,
                jp.state,
                jp.last_defer,
            )
            previous = self._state.get(junction_id)
            self._state[junction_id] = key
            if previous == key:
                continue

            prev_vehicle = previous[0] if previous else None
            if reservation is None:
                if prev_vehicle is not None:
                    before = self._releases.get(junction_id, {})
                    moved = [
                        r for r, n in jp.releases.items() if n > before.get(r, 0)
                    ]
                    reason = moved[0].value if moved else "unknown"
                    self._emit(
                        now_s, prev_vehicle, "RELEASE", junction_id,
                        f"{reason:<14s} junction total {jp.preempted_s:.0f}s preempted",
                    )
                self._releases[junction_id] = dict(jp.releases)
                continue
            self._releases[junction_id] = dict(jp.releases)

            confirm = ""
            if cfg is not None:
                mark = jp.confirmation(cfg, _fake_ctx(jp))
                confirm = f"   [{mark.name}]" if mark is not Confirmation.NONE else ""

            if prev_vehicle != reservation.vehicle_id:
                # The vehicle's own ETA at the moment of the claim, read
                # back from the track rather than plumbed out of
                # `_should_claim`. It is the number worth seeing: the
                # claim fires when ETA falls under the computed lead
                # time, so watching them converge is watching the
                # trigger work.
                track = self._engine._tracks.get(  # noqa: SLF001
                    reservation.vehicle_id
                )
                eta = track.eta_s(junction_id, self._engine.cfg) if track else float("inf")
                eta_txt = f"eta {eta:4.1f}s  " if eta != float("inf") else ""
                self._emit(
                    now_s, reservation.vehicle_id, "CLAIM", junction_id,
                    f"{eta_txt}movement {reservation.movement}, "
                    f"max hold {reservation.expires_at_s - now_s:.0f}s",
                )
            elif jp.state is PreemptState.DWELL:
                self._emit(
                    now_s, reservation.vehicle_id, "GREEN", junction_id,
                    f"phase {jp.target_phase}{confirm}",
                )
            elif jp.state is PreemptState.ENTRY_CLEAR:
                self._emit(
                    now_s, reservation.vehicle_id, "CLEARING", junction_id,
                    f"yellow + all-red, then {jp.target_phase}{confirm}",
                )
            elif jp.last_defer.value != "none":
                self._emit(
                    now_s, reservation.vehicle_id, "HOLD", junction_id,
                    f"{jp.last_defer.value}{confirm}",
                )


class DispatchWatch:
    """Narrates the dispatch layer: the call, the choice, the arrival.

    The half of the response the benchmark deliberately cannot show.
    `m7_corridor_benchmark.py` freezes dispatch at t = 0 so every arm
    drives the identical route -- without that the arms would diverge
    onto different hospitals and the travel-time comparison would be
    between two different trips. Here there is only one arm, so the
    destination can be re-evaluated as the corridor congests, which is
    what it would do in service.

    Reports, and does not act on, a better destination. Re-routing
    mid-run is a `traci.vehicle.setRoute` away and is not the
    interesting part; what is worth seeing is how often the answer
    changes at all, because that is the number that says whether live
    re-dispatch earns its complexity on a corridor this size."""

    INTERVAL_S = 60.0

    def __init__(self, injector, ev_ids, quiet: bool = False) -> None:
        self._injector = injector
        self._ev_ids = ev_ids
        self._quiet = quiet
        self._next_check = 0.0
        self._announced = False
        self._arrived: set[str] = set()
        self._live: set[str] = set()
        self.reconsiderations = 0

    def _say(self, line: str) -> None:
        if not self._quiet:
            print(line, flush=True)

    def _announce(self) -> None:
        decision, incident = self._injector.decision, self._injector.incident
        self._say(
            f"\nDISPATCH  {incident.incident_id}: {incident.required_capability} "
            f"call on edge {incident.origin_edge}"
        )
        self._say(
            f"          -> {decision.facility.name} ({decision.facility.kind}), "
            f"{decision.travel_time_s:.0f}s free-flow over "
            f"{len(decision.route_edges)} edges"
        )
        self._say(
            f"          chosen from {decision.considered} capable facilities"
            + (f", {decision.unreachable} unreachable" if decision.unreachable else "")
        )
        for name, seconds in decision.runners_up:
            self._say(f"             next: {name} {seconds:.0f}s")
        if decision.considered == 1:
            self._say(
                "          the only one on this corridor -- which is why a "
                "scarce\n          capability is where a green corridor earns "
                "its keep"
            )
        self._say("")

    def __call__(self, now_s: float) -> None:
        if self._injector.decision is None:
            return
        if not self._announced:
            self._announced = True
            self._announce()

        # Arrival: the vehicle leaves the network at the end of its route,
        # which is the facility's edge, so a vehicle that was live and is
        # no longer has completed its response.
        live = set(traci.vehicle.getIDList()) & self._ev_ids
        for vid in sorted(self._live - live):
            if vid in self._arrived:
                continue
            self._arrived.add(vid)
            self._say(
                f"[{now_s:6.0f}s] {vid:4s} ARRIVED  "
                f"{self._injector.decision.facility.name} -- response complete"
            )
        self._live = live

        if now_s < self._next_check or not live:
            return
        self._next_check = now_s + self.INTERVAL_S
        better = should_redispatch(
            self._injector.decision,
            self._injector.incident,
            self._injector.facilities,
            traci_route_fn(),
        )
        if better is not None:
            self.reconsiderations += 1
            self._say(
                f"[{now_s:6.0f}s] {'--':4s} REROUTE  would now prefer "
                f"{better.facility.name} at {better.travel_time_s:.0f}s "
                f"(current {self._injector.decision.facility.name})"
            )


class _FakeCtx:
    """`JunctionPreemption.confirmation` needs only `current_phase_id`."""

    def __init__(self, phase_id: str | None) -> None:
        self.current_phase_id = phase_id


def _fake_ctx(jp):
    return _FakeCtx(jp.target_phase if jp.state is PreemptState.DWELL else None)


def _run(*posargs, gui: bool = False, **kwargs):
    """`run_controlled_scenario`, with a usable message when SUMO never
    comes up.

    The GUI path fails differently from everything else in this project:
    the process starts, exits before it opens its socket, and TraCI then
    reports a port. Catching that and saying what to try next is worth
    more than the traceback, which points at TraCI and not at the
    problem."""
    try:
        return run_controlled_scenario(*posargs, **kwargs)
    except Exception as exc:  # noqa: BLE001 - re-raised below for the non-GUI case
        if not gui:
            raise
        binary = os.environ.get("SUMO_BINARY", "sumo-gui")
        print(
            f"\nsumo-gui did not start ({type(exc).__name__}: {exc}).\n\n"
            "Run it by hand to see its own error, which TraCI hides:\n"
            f"    {binary} -c "
            f"{kwargs.get('_cfg', 'scenarios/demand/vijayawada/vijayawada_corridor.sumocfg')}\n\n"
            "On macOS a pip-installed sumo-gui commonly needs the Homebrew\n"
            "build instead (`brew install --cask sumo-gui`, or `brew install sumo`),\n"
            "then re-run with:\n"
            "    SUMO_BINARY=$(which sumo-gui) .venv/bin/python scripts/m7_demo.py --gui\n\n"
            "The headless run needs none of this and works today:\n"
            "    .venv/bin/python scripts/m7_demo.py\n"
            "Same commentary, no window.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def _prepare_gui() -> bool:
    """Point `SUMO_BINARY` at a working `sumo-gui`, or explain why not.

    Worth doing before TraCI rather than after, because of how TraCI
    fails when the binary does not start: it launches the process,
    watches nothing, and then retries a socket that will never open --
    printing `Could not connect to TraCI server ... Connection refused`
    once a second, forever, with sumo-gui's actual complaint discarded.
    The message names a port, which is the one thing that is not wrong.

    So the binary is probed directly first and its own stderr is shown.
    `--version` is enough: it exercises library loading and the data-file
    lookup that `SUMO_HOME` controls, which is where a pip-installed
    sumo-gui usually falls over, without opening a window."""
    candidates = [
        os.environ.get("SUMO_BINARY"),
        str(Path(sys.executable).parent / "sumo-gui"),
        shutil.which("sumo-gui"),
    ]
    _ensure_sumo_home()
    for candidate in candidates:
        if not candidate or not Path(candidate).exists():
            continue
        probe = subprocess.run(
            [candidate, "--version"], capture_output=True, text=True, timeout=60
        )
        if probe.returncode == 0:
            os.environ["SUMO_BINARY"] = candidate
            first = (probe.stdout or "").strip().splitlines()
            print(f"sumo-gui: {candidate}")
            if first:
                print(f"          {first[0]}")
            return True
        print(f"sumo-gui at {candidate} exits {probe.returncode}:", file=sys.stderr)
        for line in (probe.stderr or probe.stdout or "").strip().splitlines()[:12]:
            print(f"    {line}", file=sys.stderr)

    print(
        "\nNo working sumo-gui found. SUMO_HOME="
        f"{os.environ.get('SUMO_HOME', '(unset)')}\n"
        "The headless run needs none of this and works today:\n"
        "    .venv/bin/python scripts/m7_demo.py\n"
        "It prints the same commentary; only the moving picture is missing.",
        file=sys.stderr,
    )
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", action="store_true", help="run in sumo-gui")
    parser.add_argument("--arm", default="corridor",
                        choices=["corridor", "corridor_noAD", "reactive", "none"])
    parser.add_argument("--demand", default="medium", choices=["light", "medium", "heavy"])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--delay", type=int, default=60,
                        help="sumo-gui millisecond delay per step (higher = slower)")
    parser.add_argument("--quiet", action="store_true", help="summary only")
    parser.add_argument(
        "--capability", default=EV_INCIDENT.required_capability,
        help="what the incident needs: trauma (default), general, cardiac, "
             "obstetric, paediatric, neuro, oncology, orthopaedic, ophthalmic, "
             "ent, dental. Worth trying `general` at least once -- 48 of this "
             "corridor's facilities offer it, the nearest is a block away, and "
             "the response never reaches a second junction. That contrast is "
             "the argument for why the gate uses a trauma call.",
    )
    parser.add_argument(
        "--origin", default=EV_INCIDENT.origin_edge,
        help="the edge the call comes from (default: the arterial's western end)",
    )
    args = parser.parse_args()

    if args.gui and not _prepare_gui():
        return

    configs, flows, vtype_pcu, paths = scenario_inputs(args.demand)
    arm = build_arm(args.arm)
    strategy = build_acamp(configs, flows, acamp_cfg=arm.acamp_cfg)
    if arm.corridor is not None:
        for controller in strategy.values():
            controller.corridor = arm.corridor

    reporter = None
    commentary = None
    if arm.corridor is not None:
        index = build_movement_index(
            link_to_lane_map(NET_PATH), link_to_receiving_lane_map(NET_PATH), configs
        )
        reporter = EmergencyVehicleReporter(arm.corridor, index, ev_vehicle_ids())
        commentary = Commentary(arm.corridor, configs, quiet=args.quiet)
    injector = _Injector(
        reporter,
        incident=replace(
            EV_INCIDENT,
            incident_id=f"INC-{args.capability.upper()}",
            origin_edge=args.origin,
            required_capability=args.capability,
        ),
    )
    dispatch_watch = DispatchWatch(injector, ev_vehicle_ids(), quiet=args.quiet)

    def tick(now_s: float) -> None:
        injector(now_s)
        dispatch_watch(now_s)
        if commentary is not None:
            commentary(now_s)

    print(f"arm={args.arm}  demand={args.demand}  seed={args.seed}")
    print(f"{len(EV_DEPARTURES_S)} emergency vehicles at t = "
          f"{', '.join(f'{d:.0f}s' for d in EV_DEPARTURES_S)}, "
          f"answering a {args.capability} call from edge {args.origin}.")
    print("The route is not written down anywhere: it is whatever dispatch\n"
          "returns for that call against the facility register.")

    extra = ["--start", "--quit-on-end", "--delay", str(args.delay)] if args.gui else None
    result = _run(
        str(paths["sumocfg"]),
        configs,
        strategy=strategy,
        seed=args.seed,
        link_lanes=link_to_lane_map(NET_PATH),
        receiving_lanes=link_to_receiving_lane_map(NET_PATH),
        vtype_pcu=vtype_pcu,
        max_steps=MAX_STEPS_SAFETY_CAP,
        corridor=arm.corridor,
        ev_reporter=tick,
        extra_sumo_args=extra,
        # Three retries, not sixty. If sumo-gui is going to start it does
        # so at once; if it is not, the useful thing is the error, not
        # another fifty-seven seconds of the same line.
        traci_retries=3 if args.gui else None,
        gui=args.gui,
    )

    print(f"\n{'-' * 68}")
    print(f"steps {result['steps']}   interlock violations {result['interlock_violations']}")
    if injector.decision is not None:
        print(f"destination            {injector.decision.facility.name} "
              f"(from {injector.decision.considered} capable facilities)")
        print(f"re-dispatch would fire {dispatch_watch.reconsiderations} times "
              f"(checked every {DispatchWatch.INTERVAL_S:.0f}s, "
              "30s improvement threshold)")
    if arm.corridor is not None:
        stats = arm.corridor.stats()
        print(f"reservations granted   {stats.get('reservations_granted', 0):.0f}")
        print(f"seconds preempted      {stats.get('preempted_s', 0):.0f}")
        print(f"denied by interlock    {stats.get('denied_by_interlock', 0):.0f}"
              "   <- must be 0; anything else is an engine bug")
        print("release reasons:")
        for key, value in sorted(stats.items()):
            if key.startswith("release_") and value:
                print(f"   {key[8:]:20s} {value:.0f}")
        print("deferrals (why a preemption could not be served yet):")
        for key, value in sorted(stats.items()):
            if key.startswith("defer_") and value:
                print(f"   {key[6:]:20s} {value:.0f} ticks")
        if reporter is not None:
            served = sum(reporter.passages.values())
            expected = len(ev_vehicle_ids()) * len(configs)
            print(f"junction passages      {served}/{expected} "
                  "(every vehicle past every junction on its route)")


if __name__ == "__main__":
    main()
