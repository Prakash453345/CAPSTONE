"""Webster-referenced max-green ceilings for the live and test-lab runners.

The adopted CC-A-CAMP configuration (scripts/m8_harness.ccacamp_inputs): each
phase's `max_green_s` is `CEILING_FACTOR` x its Webster green, never below
`CEILING_FLOOR_S` and never above the shipped 90 s, with `max_wait_s`
re-derived from the new ceilings. Mirrors m5_cycle_ceiling_probe /
m8_harness, which are scenario scripts and so cannot be imported from a
service. Apply *before* shown overlaps are added, as the harness does.
"""
from __future__ import annotations

from dataclasses import replace

from itms_domain import Tier0Config

from sim_service.control.strategies import webster

CEILING_FACTOR = 1.25
CEILING_FLOOR_S = 20.0
ABSOLUTE_CEILING_S = 90.0
MAX_WAIT_MARGIN_S = 60.0


def _ceilings(cfg: Tier0Config, flows: dict, factor: float, floor_s: float) -> dict[str, float]:
    greens = getattr(webster.compute_timing(cfg, flows), "green_s", None) or {}
    out: dict[str, float] = {}
    for phase_id in cfg.ring_order:
        target = greens.get(phase_id)
        if target is None:
            out[phase_id] = cfg.max_green_s.get(phase_id, ABSOLUTE_CEILING_S)
            continue
        lo = cfg.min_green_s.get(phase_id, 0.0)
        webster_ceiling = min(ABSOLUTE_CEILING_S, max(lo, factor * target))
        out[phase_id] = max(webster_ceiling, floor_s)
    return out


def with_webster_ceilings(
    configs: dict[str, Tier0Config],
    flows: dict[str, dict],
    factor: float = CEILING_FACTOR,
    floor_s: float = CEILING_FLOOR_S,
) -> dict[str, Tier0Config]:
    out: dict[str, Tier0Config] = {}
    for tls, cfg in configs.items():
        ceilings = _ceilings(cfg, flows.get(tls, {}), factor, floor_s)
        lost = cfg.yellow_s + cfg.all_red_s
        max_wait = (
            sum(ceilings.get(p, 0.0) for p in cfg.ring_order)
            + len(cfg.ring_order) * lost
            + MAX_WAIT_MARGIN_S
        )
        out[tls] = replace(cfg, max_green_s=ceilings, max_wait_s=max_wait)
    return out
