"""Unit tests for the Tier-0 clearance-interval rule
(`extract_tier0_config.kinematic_yellow_s`), added with the 2026-09-18
change that stopped inheriting netconvert's guessed yellow.

Imported by path because `scenarios/networks/vijayawada/` is a scenario
script directory, not an installed package -- the same way
`scripts/m5_harness.py` reaches it."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_EXTRACT = (
    Path(__file__).resolve().parents[5]
    / "scenarios" / "networks" / "vijayawada" / "extract_tier0_config.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("extract_tier0_config_under_test", _EXTRACT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    "speed_mps, expected_s",
    [
        (6.9, 3.0),    # 25 km/h service road -- the 3 s practice floor, not 2.2 s
        (13.9, 3.5),   # 50 km/h urban arterial -> 1.0 + 13.9/6 = 3.3 -> 3.5
        (16.7, 4.0),   # 60 km/h -> 3.8 -> 4.0
        (27.8, 5.0),   # 100 km/h -> 5.6, clamped at the 5 s ceiling
    ],
)
def test_kinematic_yellow_follows_the_ite_change_interval_rule(speed_mps, expected_s):
    assert _module().kinematic_yellow_s(speed_mps) == expected_s


def test_yellow_is_monotone_in_approach_speed():
    m = _module()
    speeds = [5.0, 10.0, 15.0, 20.0, 25.0]
    values = [m.kinematic_yellow_s(v) for v in speeds]
    assert values == sorted(values)


def test_extracted_configs_use_the_rule_and_the_new_min_green():
    m = _module()
    configs = m.load_configs(_EXTRACT.parent / "vijayawada_corridor.net.xml")
    assert configs, "the corridor network should yield at least one junction"
    for cfg in configs.values():
        assert m._MIN_YELLOW_S <= cfg.yellow_s <= m._MAX_YELLOW_S
        assert cfg.yellow_s * 2 == int(cfg.yellow_s * 2)  # half-second grid
        assert set(cfg.min_green_s.values()) == {7.0}
        # max_wait must still clear one worst-case rotation of this ring.
        rotation = sum(cfg.max_green_s.values()) + len(cfg.ring_order) * (
            cfg.yellow_s + cfg.all_red_s
        )
        assert cfg.max_wait_s >= rotation


def test_ite_all_red_is_width_plus_vehicle_over_speed():
    """ITE red clearance r = (W + 6 m) / v, rounded up to 0.5 s, in [1, 4] s;
    the slowest-to-clear crossing decides."""
    m = _module()
    assert m.ite_all_red_s([(12.0, 13.9)]) == 1.5        # 18 / 13.9 = 1.29 -> 1.5
    assert m.ite_all_red_s([(30.0, 13.9)]) == 3.0        # 36 / 13.9 = 2.59 -> 3.0
    assert m.ite_all_red_s([(12.0, 13.9), (30.0, 13.9)]) == 3.0
    assert m.ite_all_red_s([(1.0, 20.0)]) == 1.0         # floor
    assert m.ite_all_red_s([(80.0, 8.0)]) == 4.0         # ceiling
    assert m.ite_all_red_s([]) == 2.0                    # no data: the old flat value
