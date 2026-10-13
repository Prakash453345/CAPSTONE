"""Which states of a SUMO signal program are the phases a controller chooses
between.

A program lists every state the light shows: the greens, and between them
change intervals, clearances and start-up signals. The controller builds its
own change intervals (`TraCICabinet.yellow_state_for`), so what it needs from
the program is the set of green stages. `green_phase_states` picks them, and
both the controller's configuration (`extract_tier0_config.py`, which numbers
them `P0, P1, ...`) and the camera service's view of the signal
(`itms_geo.RoadNetwork.green_phases`) use it, so the two number phases alike.

Three things in real programs are not phases of their own:

- **Change intervals**: a state with any amber ('y'/'Y') or red+amber ('u',
  the German start-up signal) in it, even while other links stay green.
  netconvert writes `yyyrrrGyy` where one movement runs through two phases;
  counted as a phase it duplicated a neighbour's green set and the cabinet
  could not tell them apart on readback (a generated radial network went to
  the readback failsafe hundreds of times a run).
- **Parts of a stage**: consecutive greens with no amber between them are
  one stage. A green whose links are a strict subset of another's in the
  same stage, protecting nothing the other does not, is that stage's head or
  tail: the pedestrian clearance of an OpenStreetMap import with crossings
  (`GGGGrr...GrGGGGG`, then the same with the crossings red, then amber),
  or an early start. Counted as phases they doubled a Berlin junction's
  ring to ten.
- **Repeats**: the same green shown twice in one cycle is one phase.
"""

from __future__ import annotations

_CHANGE = frozenset("yYu")


def is_green_phase(state: str) -> bool:
    """At least one green link and no amber or red+amber."""
    return any(c in "Gg" for c in state) and not any(c in _CHANGE for c in state)


def _separates_stages(state: str) -> bool:
    """An amber (a clearance) or all red. A red+amber start-up signal does not
    end a stage: it announces the next part of it."""
    return any(c in "yY" for c in state) or not any(c in "Ggu" for c in state)


def sub_stage_indices(states: list[str]) -> set[int]:
    """Program positions of greens that are only the head or tail of a
    neighbouring green's stage (see the module docstring)."""
    n = len(states)
    if n == 0:
        return set()
    seps = [_separates_stages(st) for st in states]
    if any(seps):
        start = seps.index(True)
        order = [(start + j) % n for j in range(1, n + 1)]   # begin after a separator
    else:
        order = list(range(n))
    runs: list[list[int]] = [[]]
    for i in order:
        if seps[i]:
            runs.append([])
        elif is_green_phase(states[i]):
            runs[-1].append(i)
    drop: set[int] = set()
    for run in runs:
        sets = {i: (frozenset(k for k, c in enumerate(states[i]) if c in "Gg"),
                    frozenset(k for k, c in enumerate(states[i]) if c == "G")) for i in run}
        for i, (g, p) in sets.items():
            if any(g < g2 and p <= p2 for j, (g2, p2) in sets.items() if j != i):
                drop.add(i)
    return drop


def green_phase_states(states: list[str]) -> list[tuple[int, str]]:
    """`(program position, state)` of each phase, in program order."""
    part = sub_stage_indices(states)
    out: list[tuple[int, str]] = []
    seen: set[tuple[frozenset[int], frozenset[int]]] = set()
    for i, st in enumerate(states):
        if not is_green_phase(st) or i in part:
            continue
        key = (frozenset(k for k, c in enumerate(st) if c in "Gg"),
               frozenset(k for k, c in enumerate(st) if c == "G"))
        if key in seen:
            continue
        seen.add(key)
        out.append((i, st))
    return out
