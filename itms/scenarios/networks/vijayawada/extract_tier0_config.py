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

`sat_flow_pcu_s` is populated too, for M4 -- every movement gets the same
conventional per-lane placeholder value (`_SAT_FLOW_PCU_S` below), not a
measured one; see that constant's own comment for why.

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

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from itms_domain import Phase, Tier0Config

_HERE = Path(__file__).resolve().parent
_DEFAULT_NET = _HERE / "vijayawada_corridor.net.xml"

# Not read off the network -- see module docstring for why each exists.
_ALL_RED_S = 2.0
_MIN_GREEN_S = 10.0  # safety floor, not netconvert's guessed plan duration -- see module docstring
_MAX_GREEN_S = 90.0  # conventional urban-signal ceiling
_MAX_WAIT_MARGIN_S = 60.0  # headroom above a ring's own worst-case full rotation

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
    """A real (non-yellow-only) phase has at least one green link. SUMO
    states use 'G'/'g' for green, 'y'/'Y' for yellow, 'r'/'R' for red/off."""
    return any(c in "Gg" for c in state)


def _extract_one(tls_id: str, tl_logic: ET.Element, junction: ET.Element) -> Tier0Config:
    # Conflict matrix from this junction's own <request> elements, keyed by
    # link-index labels ("L0", "L1", ...) matching the tlLogic state string
    # character positions.
    conflict_matrix: dict[str, frozenset[str]] = {}
    for req in junction.findall("request"):
        idx_attr = req.get("index")
        if idx_attr is None:
            raise ValueError(f"junction {junction.get('id')!r} has a <request> with no index")
        idx = int(idx_attr)
        foes = req.get("foes", "")
        conflict_matrix[f"L{idx}"] = frozenset(f"L{j}" for j in _conflicts_from_foes(foes))

    phases: dict[str, Phase] = {}
    ring_order: list[str] = []
    min_green_s: dict[str, float] = {}
    max_green_s: dict[str, float] = {}
    yellow_s = 3.0  # overwritten below from the first yellow phase found, if any

    green_phase_count = 0
    all_phase_elements = tl_logic.findall("phase")
    for phase_el in all_phase_elements:
        state = phase_el.get("state", "")
        duration = float(phase_el.get("duration", "0"))
        if not _is_green_phase(state):
            # A yellow-only clearance phase SUMO's default program inserted.
            # Its duration is real per-junction data worth keeping (unlike
            # all_red_s, which SUMO doesn't model at all here).
            if all(c in "yY" for c in state if c not in "rR"):
                yellow_s = duration
            continue
        phase_id = f"P{green_phase_count}"
        green_links = frozenset(f"L{i}" for i, c in enumerate(state) if c in "Gg")
        protected_links = frozenset(f"L{i}" for i, c in enumerate(state) if c == "G")
        phases[phase_id] = Phase(phase_id, green_links, protected_movements=protected_links)
        ring_order.append(phase_id)
        min_green_s[phase_id] = _MIN_GREEN_S
        max_green_s[phase_id] = _MAX_GREEN_S
        green_phase_count += 1

    # Every movement that is ever green in some phase gets the same
    # conventional placeholder saturation flow -- see _SAT_FLOW_PCU_S.
    all_green_links: set[str] = set()
    for phase in phases.values():
        all_green_links.update(phase.green_movements)
    sat_flow_pcu_s = dict.fromkeys(all_green_links, _SAT_FLOW_PCU_S)

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


def load_configs(net_path: str | Path) -> dict[str, Tier0Config]:
    tree = ET.parse(net_path)
    root = tree.getroot()

    junctions_by_id = {j.get("id"): j for j in root.findall("junction")}
    configs: dict[str, Tier0Config] = {}
    for tl_logic in root.findall("tlLogic"):
        tls_id = tl_logic.get("id")
        if tls_id is None:
            raise ValueError("a <tlLogic> element has no id")
        junction = junctions_by_id.get(tls_id)
        if junction is None:
            raise ValueError(f"tlLogic {tls_id!r} has no matching <junction> element")
        configs[tls_id] = _extract_one(tls_id, tl_logic, junction)
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
