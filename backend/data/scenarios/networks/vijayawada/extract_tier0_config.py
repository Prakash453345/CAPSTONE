"""Extract real Tier0Config data (phases, conflict matrix, ring order) for
every signal-controlled junction in the Vijayawada corridor network, from
the network's own `.net.xml` -- the bridge between M2's safety kernel
(built and property-tested against synthetic junctions) and the real
7-junction network M1 built.

Two things come straight from netconvert's own output, not guesswork:

- **Phases and ring order**: each junction's `<tlLogic>` already has a
  conflict-aware default program (netconvert never puts two conflicting
  movements in the same phase). We keep the green phases as-is and drop the
  yellow-only phases SUMO baked in -- our own kernel inserts yellow/all-red
  between phases itself (`PlanStep.yellow_s`/`all_red_s`), so keeping
  SUMO's own yellow phases as separate ring entries would double up on
  that.

- **Conflict matrix**: each `<junction>`'s `<request index="i" foes="...">`
  bitstring is the *real* traffic-engineering conflict data (protected
  turns get narrower conflict sets than raw opposing-through movements) --
  this is authoritative, not a hand-derived approximation. SUMO's foes
  string is written most-significant-link-first (reverse of link-index
  order); `_conflicts_from_foes` undoes that so `conflicts[i]` lists link
  indices in ascending order, self excluded.

What's a deliberate addition rather than something read off the network:
`all_red_s`. SUMO's default program has no all-red phase at all (green
straight to yellow straight to the next green) -- our kernel requires one
per I2, so we add a fixed 2.0s clearance the network itself doesn't model.
That's a real safety improvement over the bare simulation default, not an
extraction artifact.

`min_green_s`/`max_green_s` are also deliberate additions, not read off
netconvert -- and an earlier version of this module got that wrong in a way
worth recording rather than quietly erasing. netconvert's `<tlLogic>` gives
each green phase a `duration` attribute, but that number is netconvert's
own guess at a *workable fixed-time plan* for demand it has no visibility
into (it commonly comes out to 30-40s for a plain two-phase junction, just
a default that "runs"). The first extraction used that guess directly as
`min_green_s` -- conflating a safety *floor* (the shortest green any
strategy may ever cut a phase to, I3) with a *nominal plan duration* (what
a specific untuned strategy happens to propose). The two are different
things measured in the same unit, and treating one as the other quietly
capped every strategy in this project -- Webster (M3), and eventually
CA-MP (M4) -- to netconvert's arbitrary ~39s regardless of what real
measured demand said the right split was. `min_green_s`/`max_green_s`
below are fixed, documented safety-engineering bounds instead:
`_MIN_GREEN_S` (10.0s -- a standard floor: long enough for a committed
pedestrian/vehicle to clear, short enough not to constrain any real tuning
strategy) and `_MAX_GREEN_S` (90.0s -- a conventional urban-signal
ceiling). netconvert's `duration` is still used for exactly one thing:
locating which phase is the yellow phase, so its real duration can seed
`yellow_s`.

`max_wait_s` is set explicitly for the same reason, discovered the same
way -- by building a strategy (semi-actuated) that actually reads it and
watching a real junction violate it. `Tier0Config`'s own default,
120.0s, is a number picked with no knowledge of any specific ring; on a
4-phase junction where each phase's `max_green_s` ceiling is 90.0s, one
minor phase legitimately holding its full max-green while a second minor
also has demand can push that second movement's wait comfortably past
120s -- not a strategy bug (semi-actuated's own longest-wait scheduling
was working as designed) but a config whose starvation promise its own
timing structure couldn't back up. `max_wait_s` below is instead sized
off this ring's own worst-case full rotation (every phase maxing out
once, plus clearance overhead) with a flat safety margin -- exactly the
relationship a real deployment tunes these two parameters by, rather than
an arbitrary global default disconnected from how many phases a specific
ring actually has to cycle through.

**Clearance intervals (`yellow_s`), computed rather than inherited --
changed 2026-09-18.** This extraction used to take `yellow_s` from the
duration of whatever yellow-only phase netconvert had guessed for the
junction, which on this corridor is 5-6 s. With `all_red_s` at 2 s that
made every phase change cost 7-8 s of dark time, and at light demand the
4-phase junction spent 32 s of a 72 s cycle clearing. Measured
consequence, 10 held-out seeds, paired: replacing that guess with the
kinematic value below is worth -18.9% / -21.0% person-delay at light /
medium demand for A-CA-MP and -14.3% / -20.6% for the Webster baseline --
larger than any control-algorithm change this project has landed, and it
is a modelling correction rather than a control improvement. The value
now comes from the ITE/IRC change-interval rule,
`y = t_r + v / (2a + 2gG)`, evaluated per junction at the fastest
signal-controlled approach speed the network declares, with `t_r = 1.0 s`,
`a = 3.0 m/s^2`, `G = 0`, clamped to [3 s, 5 s] and rounded to the half
second. `all_red_s` stays the flat 2.0 s: sizing it properly needs each
junction's real clearance distance, which this extract does not carry.

`min_green_s` moved 10 s -> 7 s at the same time and for a related reason.
With the M5 ceiling at 1.25x Webster's green, most phases at light and
medium demand had a 12.5 s ceiling against a 10 s floor -- a 2.5 s band
for the controller to act in, and 62-64% of all its decision ticks were
spent inside the floor. 7 s is still above the usual 4-7 s practice floor
for a through movement; any phase carrying a pedestrian call should get
its own longer floor from `ped_walk_s`/`ped_clearance_s` rather than from
this blanket constant, which is the obvious next refinement here.

`sat_flow_pcu_s` is populated too, for M4. As of `measure_saturation_flow.py`
(see its own module docstring and PROGRESS.md's CA-MP section), most
movements now get a *real* measured value -- loaded from
`sat_flow_calibration.json` if present next to this network file -- rather
than the uniform placeholder every movement used before. A movement missing
from that file (either the calibration script was never run, or that
specific movement couldn't collect enough clean discharges in its
measurement window -- see the calibration script's own skip criteria)
falls back to `_SAT_FLOW_PCU_S`, the original conventional placeholder;
see that constant's own comment for why it exists at all.

What's NOT modeled: pedestrian phases. This network has no crossing
infrastructure (a plain netconvert import with no explicit pedestrian
data), so every extracted `Phase.is_pedestrian` is False and
`ped_walk_s`/`ped_clearance_s` stay empty. I4 is real and property-tested
(M2), but nothing in a live run of *this* network exercises it yet --
that needs a network with pedestrian crossings modeled, not a kernel
change.

One subtlety this extraction has to get right, not just approximate: SUMO
states use uppercase 'G' for a *protected* movement and lowercase 'g' for
a *permissive* one (a free/permitted turn that SUMO yield-checks against
foes dynamically at runtime, independent of phase design -- e.g. an
always-permitted left). Some of this network's real junctions group a 'g'
movement into the same phase as movements its own `foes` data says it
conflicts with. That is not a netconvert bug or a modeling error: it's
exactly the point of a permissive movement, and flagging it as an I1
violation would be a false positive from not knowing SUMO's own
convention. `Phase.protected_movements` (only the 'G' positions) is what
I1 actually checks; `green_movements` (both 'G' and 'g') is everything
that gets a go-indication, still used everywhere else a phase's full
movement set matters (I5's "is this being served", the cabinet's state
string).

Usage: python extract_tier0_config.py [path/to/vijayawada_corridor.net.xml]
Importable: `load_configs(net_path) -> dict[str, Tier0Config]`, keyed by
SUMO traffic-light id (== `Tier0Config.intersection_id`).
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from itms_domain import Phase, Tier0Config
from itms_domain.signal_program import green_phase_states, is_green_phase
from itms_domain.signal_program import sub_stage_indices as _sub_stage_indices  # noqa: F401

_HERE = Path(__file__).resolve().parent
_DEFAULT_NET = _HERE / "vijayawada_corridor.net.xml"
_SAT_FLOW_CALIBRATION_FILENAME = "sat_flow_calibration.json"

# Not read off the network -- see module docstring for why each exists.
_ALL_RED_S = 2.0
_MIN_GREEN_S = 7.0  # safety floor, not netconvert's guessed plan duration -- see module docstring
_MAX_GREEN_S = 90.0  # conventional urban-signal ceiling
_MAX_WAIT_MARGIN_S = 60.0  # headroom above a ring's own worst-case full rotation

# Change-interval (yellow) sizing, added 2026-09-18 -- see the module
# docstring's "Clearance intervals" section for the measurement that forced
# it. `y = t_r + v / (2a + 2gG)` is the ITE/IRC kinematic change-interval
# rule; `G = 0` (this corridor is flat, and no grade data is available in
# the OSM extract), so the denominator is `2a`.
_DRIVER_REACTION_S = 1.0        # ITE's conventional perception-reaction allowance
_COMFORTABLE_DECEL_MPS2 = 3.0   # ITE's conventional comfortable deceleration
_MIN_YELLOW_S = 3.0             # practice floor: never less than 3 s
_MAX_YELLOW_S = 5.0             # practice ceiling: above this, drivers treat it as red-running time

# `s_lm` [build guide §3.9] -- 1800 PCU/h == 0.5 PCU/s per lane, the same
# order of magnitude as HCM's "ideal" per-lane saturation flow and within
# the range IRC guidelines cite for a well-behaved urban lane. The guide
# is explicit that this must eventually be *measured* per approach, per
# condition (§8.5: "do not use a manual value") -- this build has no
# discharge-headway field data yet, so every movement gets the same
# conventional per-lane placeholder rather than a per-approach number
# this project hasn't earned. Flagged here, in PROGRESS.md, and in
# camp.py's own gate criteria as a documented limitation to replace with
# real calibration before any CA-MP result is reported as more than a
# software-correctness demonstration.
_SAT_FLOW_PCU_S = 0.5


def _conflicts_from_foes(foes: str) -> list[int]:
    """SUMO writes `foes` most-significant-link-first; reverse it so index i
    of the result says whether link i is a foe."""
    reversed_bits = foes[::-1]
    return [i for i, bit in enumerate(reversed_bits) if bit == "1"]


def _is_green_phase(state: str) -> bool:
    """A real green phase has at least one green link and no yellow one. SUMO
    states use 'G'/'g' for green, 'y'/'Y' for yellow, 'r'/'R' for red/off.

    A state with both is a change interval in which some movements carry on
    (netconvert writes `yygrrrryygrrrr` before a protected-turn phase, and
    `yyyrrrGyy` where one movement runs through two phases). The first
    version counted those as green phases. Their green sets are subsets of
    the phases around them, often identical to another one, so the cabinet
    could not tell them apart on readback: on a generated radial network
    (`scenarios/generated/spider_lh`) every junction with one went to the
    readback-divergence failsafe hundreds of times a run, and delay at heavy
    demand was 2.8x Webster's. The controller builds its own change interval
    (`TraCICabinet.yellow_state_for`), so these are skipped. The corridor's
    programs have none, so its configs are unchanged.

    'u' (red+amber before green, used in German signal plans such as SUMO's
    Ingolstadt example) is a change interval too. The rule lives in
    `itms_domain.signal_program`, shared with the camera service."""
    return is_green_phase(state)   # itms_domain.signal_program: one rule for all


def _program_agrees(
    junction: ET.Element, tl_logic: ET.Element, tl_to_junction: dict[int, int]
) -> bool:
    """Whether the junction's `<request>` rows, read through `tl_to_junction`,
    describe this program's links.

    The conflict matrix is read from the junction, keyed by request index,
    and the light's link `i` is request `tl_to_junction[i]`
    (`_tl_to_junction_index`). The test: every link of the program maps to a
    request, and no green phase of the program shows two protected links the
    junction calls foes (no real program does). Read through a wrong
    numbering, the program's own greens looked like conflicts (SUMO's
    Ingolstadt example: a junction with 35 requests under an 18-link
    program), and every tick of every run went to the interlock failsafe."""
    states = [ph.get("state", "") for ph in tl_logic.findall("phase")]
    if not states:
        return True
    if set(tl_to_junction) != set(range(len(states[0]))):
        return False
    foes = {int(r.get("index", "-1")): set(_conflicts_from_foes(r.get("foes", "")))
            for r in junction.findall("request")}
    if any(j not in foes for j in tl_to_junction.values()):
        return False
    for st in states:
        if not _is_green_phase(st):
            continue
        on = [i for i, c in enumerate(st) if c == "G"] or [i for i, c in enumerate(st) if c == "g"]
        if any(tl_to_junction[j] in foes[tl_to_junction[i]] for i in on for j in on if i < j):
            return False
    return True


def kinematic_yellow_s(approach_speed_mps: float) -> float:
    """ITE/IRC change interval `y = t_r + v / (2a + 2gG)` with `G = 0`,
    clamped to practice bounds and rounded to the half second.

    Pure and exported so a test can pin the rule rather than the number:
    50 km/h (13.9 m/s) -> 3.5 s, 60 km/h -> 4.0 s, a 25 km/h service road
    -> the 3.0 s floor."""
    raw = _DRIVER_REACTION_S + approach_speed_mps / (2.0 * _COMFORTABLE_DECEL_MPS2)
    clamped = max(_MIN_YELLOW_S, min(_MAX_YELLOW_S, raw))
    return round(clamped * 2.0) / 2.0


def _approach_speed_mps(junction: ET.Element, lane_speeds: dict[str, float]) -> float:
    """The fastest speed limit among this junction's incoming lanes -- the
    approach a yellow has to be long enough for. Falls back to 13.9 m/s
    (50 km/h) when the network declares nothing, which is this corridor's
    own arterial limit."""
    speeds = [
        lane_speeds[lane]
        for lane in (junction.get("incLanes") or "").split()
        if lane in lane_speeds
    ]
    return max(speeds) if speeds else 13.9


def _joined_view(tls_id: str, tl_logic: ET.Element, root: ET.Element) -> ET.Element:
    """A stand-in `<junction>` for a traffic light that controls several
    junctions (netconvert's `--tls.join`, common in OpenStreetMap imports,
    names it `joinedS_...`). Its link indices span every junction it
    controls, so no single junction's `<request>` rows describe it. The
    conflicts are taken from its own program instead: two links conflict when
    no green phase shows both green. That treats the program's groupings as
    the safe ones -- which is what they are, the network's own signal plan --
    and incoming lanes come from its connections, for the yellow."""
    greens = [
        {i for i, c in enumerate(p.get("state", "")) if c in "Gg"}
        for p in tl_logic.findall("phase")
        if _is_green_phase(p.get("state", ""))
    ]
    n = max((len(p.get("state", "")) for p in tl_logic.findall("phase")), default=0)
    view = ET.Element("junction", {"id": tls_id})
    for i in range(n):
        together = set().union(*(g for g in greens if i in g)) if any(i in g for g in greens) \
            else set()
        foes = "".join("1" if (j != i and j not in together) else "0" for j in range(n))
        ET.SubElement(view, "request", {"index": str(i), "foes": foes[::-1]})
    inc = {c.get("from") + "_" + c.get("fromLane") for c in root.findall("connection")
           if c.get("tl") == tls_id and c.get("from") and c.get("fromLane") is not None}
    view.set("incLanes", " ".join(sorted(inc)))
    return view


def _extract_one(
    tls_id: str,
    tl_logic: ET.Element,
    junction: ET.Element,
    measured_sat_flow: dict[str, float] | None = None,
    lane_speeds: dict[str, float] | None = None,
    tl_to_junction: dict[int, int] | None = None,
) -> Tier0Config:
    # Conflict matrix from this junction's own <request> elements, keyed by
    # link-index labels ("L0", "L1", ...) matching the tlLogic state string
    # character positions. A <request index> counts the *junction's* links,
    # which is not always the signal's numbering: inside some joined
    # clusters netconvert numbers the signal's links in a different order
    # (see `_tl_to_junction_index`). `tl_to_junction` translates; without it
    # the two are taken to be the same (true of every corridor junction).
    foes_by_junction_index: dict[int, list[int]] = {}
    for req in junction.findall("request"):
        idx_attr = req.get("index")
        if idx_attr is None:
            raise ValueError(f"junction {junction.get('id')!r} has a <request> with no index")
        foes_by_junction_index[int(idx_attr)] = _conflicts_from_foes(req.get("foes", ""))
    if tl_to_junction is None:
        tl_to_junction = {i: i for i in foes_by_junction_index}
    junction_to_tl = {j: i for i, j in tl_to_junction.items()}
    conflict_matrix: dict[str, frozenset[str]] = {}
    for tl_idx, j_idx in tl_to_junction.items():
        if j_idx not in foes_by_junction_index:
            raise ValueError(
                f"{tls_id!r}: signal link {tl_idx} maps to junction link {j_idx}, which has no <request>"
            )
        conflict_matrix[f"L{tl_idx}"] = frozenset(
            f"L{junction_to_tl[j]}" for j in foes_by_junction_index[j_idx] if j in junction_to_tl
        )

    phases: dict[str, Phase] = {}
    ring_order: list[str] = []
    min_green_s: dict[str, float] = {}
    max_green_s: dict[str, float] = {}
    # Computed from the approach speed, not inherited from netconvert's
    # guessed yellow phase -- see the module docstring's clearance-interval
    # section for the measurement that forced the change.
    yellow_s = kinematic_yellow_s(_approach_speed_mps(junction, lane_speeds or {}))

    # The program's green stages, in program order: change intervals
    # (including the yellow-only clearances SUMO's default program inserts,
    # whose 5-6 s netconvert guess once seeded `yellow_s` and cost more delay
    # than any controller change recovered -- the kinematic rule above is the
    # source now), the heads and tails of a stage (a pedestrian clearance)
    # and repeats are skipped. See `itms_domain.signal_program`.
    green_phase_count = 0
    states = [ph.get("state", "") for ph in tl_logic.findall("phase")]
    for _, state in green_phase_states(states):
        green_links = frozenset(f"L{i}" for i, c in enumerate(state) if c in "Gg")
        protected_links = frozenset(f"L{i}" for i, c in enumerate(state) if c == "G")
        phase_id = f"P{green_phase_count}"
        phases[phase_id] = Phase(phase_id, green_links, protected_movements=protected_links)
        ring_order.append(phase_id)
        min_green_s[phase_id] = _MIN_GREEN_S
        max_green_s[phase_id] = _MAX_GREEN_S
        green_phase_count += 1

    # Every movement that is ever green in some phase gets a real measured
    # saturation flow if `measure_saturation_flow.py` produced one for it;
    # otherwise the original conventional placeholder -- see
    # _SAT_FLOW_PCU_S and this module's own docstring.
    all_green_links: set[str] = set()
    for phase in phases.values():
        all_green_links.update(phase.green_movements)
    measured_sat_flow = measured_sat_flow or {}
    sat_flow_pcu_s = {
        link: measured_sat_flow.get(link, _SAT_FLOW_PCU_S) for link in all_green_links
    }

    # max_wait_s sized off this ring's own worst-case full rotation (every
    # phase maxing out once, plus clearance overhead), not left at
    # Tier0Config's blanket 120.0s default -- see module docstring for why
    # that default and a ring this wide are structurally incompatible.
    max_wait_s = (
        sum(max_green_s.values()) + len(ring_order) * (yellow_s + _ALL_RED_S) + _MAX_WAIT_MARGIN_S
    )

    return Tier0Config(
        intersection_id=tls_id,
        phases=phases,
        ring_order=tuple(ring_order),
        conflict_matrix=conflict_matrix,
        min_green_s=min_green_s,
        max_green_s=max_green_s,
        yellow_s=yellow_s,
        all_red_s=_ALL_RED_S,
        max_wait_s=max_wait_s,
        sat_flow_pcu_s=sat_flow_pcu_s,
    )


def _load_sat_flow_calibration(net_path: Path) -> dict[str, dict[str, float]]:
    """`{tls_id: {"L{i}": pcu_per_s}}`, from `measure_saturation_flow.py`'s
    output if it's been run for this network; `{}` (every movement falls
    back to the placeholder) if not -- calibration is optional, additive
    data, never required for this loader to work."""
    calibration_path = net_path.parent / _SAT_FLOW_CALIBRATION_FILENAME
    if not calibration_path.exists():
        return {}
    return json.loads(calibration_path.read_text())


def _tl_to_junction_index(
    root: ET.Element, junction: ET.Element, tls_id: str
) -> dict[int, int]:
    """{signal linkIndex: junction link index} for one signalised junction.

    SUMO numbers a junction's links (the `index` of its <request>s, and the
    bit positions of `foes`) by walking `incLanes` in order and, per lane,
    its outgoing connections in file order -- the rule `sumolib`'s
    `Node.getLinkIndex` implements. The signal's `linkIndex` on each
    <connection> is a separate numbering that usually, but not always,
    matches it."""
    by_lane: dict[str, list[ET.Element]] = {}
    for c in root.iter("connection"):
        frm = c.get("from", "")
        if frm.startswith(":") or c.get("to", "").startswith(":"):
            continue  # internal (via) connections are not junction links
        by_lane.setdefault(f"{frm}_{c.get('fromLane')}", []).append(c)
    mapping: dict[int, int] = {}
    j_idx = 0
    for lane in (junction.get("incLanes") or "").split():
        if lane.startswith(":"):
            continue
        for c in by_lane.get(lane, ()):
            if c.get("tl") == tls_id and c.get("linkIndex") is not None:
                tl_idx = int(c.get("linkIndex"))
                if tl_idx in mapping:
                    raise ValueError(f"{tls_id!r}: signal link {tl_idx} appears twice")
                mapping[tl_idx] = j_idx
            j_idx += 1
    return mapping


def load_configs(net_path: str | Path) -> dict[str, Tier0Config]:
    net_path = Path(net_path)
    tree = ET.parse(net_path)
    root = tree.getroot()
    calibration = _load_sat_flow_calibration(net_path)

    junctions_by_id = {j.get("id"): j for j in root.findall("junction")}
    lane_speeds: dict[str, float] = {}
    for edge in root.findall("edge"):
        for lane in edge.findall("lane"):
            lane_id = lane.get("id")
            speed = lane.get("speed")
            if lane_id is not None and speed is not None:
                lane_speeds[lane_id] = float(speed)
    configs: dict[str, Tier0Config] = {}
    for tl_logic in root.findall("tlLogic"):
        tls_id = tl_logic.get("id")
        if tls_id is None:
            raise ValueError("a <tlLogic> element has no id")
        junction = junctions_by_id.get(tls_id)
        tl_to_junction: dict[int, int] | None = None
        if junction is not None:
            try:
                tl_to_junction = _tl_to_junction_index(root, junction, tls_id)
            except ValueError:
                tl_to_junction = None  # inconsistent numbering: use the program's view
        if (
            junction is None
            or tl_to_junction is None
            or not _program_agrees(junction, tl_logic, tl_to_junction)
        ):
            # one light over several junctions (netconvert --tls.join), or
            # links the junction's own rows cannot account for: conflicts from
            # the program, whose view is already in the light's numbering
            junction = _joined_view(tls_id, tl_logic, root)
            tl_to_junction = None
        configs[tls_id] = _extract_one(
            tls_id,
            tl_logic,
            junction,
            calibration.get(tls_id),
            lane_speeds,
            tl_to_junction=tl_to_junction,
        )
    return configs


def main() -> None:
    net_path = sys.argv[1] if len(sys.argv) > 1 else str(_DEFAULT_NET)
    configs = load_configs(net_path)
    print(f"extracted {len(configs)} junction configs from {net_path}")
    any_problems = False
    for tls_id, cfg in configs.items():
        problems = cfg.validate()
        status = "OK" if not problems else f"PROBLEMS: {problems}"
        print(
            f"  {tls_id}: {len(cfg.ring_order)} phases, "
            f"yellow_s={cfg.yellow_s}, min_green_s={cfg.min_green_s} -- {status}"
        )
        any_problems = any_problems or bool(problems)
    if any_problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
