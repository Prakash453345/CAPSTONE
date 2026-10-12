"""Everything needed to run the live Vijayawada corridor under the
arbitration ladder, loaded once: Tier-0 configs, link/lane maps, PCU weights,
and a tuned Webster strategy per junction.

The scenario helpers (`extract_tier0_config`, `link_lanes`, `measure_flows`)
live in `scenarios/networks/vijayawada/` and are not an installed package --
the gate/smoke scripts add that directory to `sys.path` and so does this
module, in one place with this comment, rather than every caller repeating it.
This mirrors what `scripts/m5_harness.py` does for the offline gates.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from itms_domain import Tier0Config

from sim_service.control.runner import StrategySource
from sim_service.control.strategies import webster
from sim_service.signal_controller.queue_state import load_vtype_pcu

_ROOT = Path(__file__).resolve().parents[4]
_SCEN = _ROOT / "scenarios" / "networks" / "vijayawada"
if str(_SCEN) not in sys.path:
    sys.path.insert(0, str(_SCEN))

from extract_tier0_config import load_configs  # noqa: E402
from itms_domain.scenario import Scenario, vijayawada  # noqa: E402
from itms_domain.scenario import current as _current_scenario  # noqa: E402
from link_lanes import link_to_lane_map, link_to_receiving_lane_map  # noqa: E402
from measure_flows import compute_link_flows  # noqa: E402

# which network: ITMS_SCENARIO (any network built by scenarios/build_scenario.py),
# else the Vijayawada network SIM_NETWORK names ("corridor", the default, or
# "district") -- itms_domain.scenario. A live run can also name a Vijayawada
# network directly (`network=`), which is how the tests pick one.
NET_PATH = _current_scenario().net


def scenario_for(network: str | None = None) -> Scenario:
    """The configured scenario, or the named Vijayawada network."""
    return _current_scenario() if network is None else vijayawada(network=network)


def network_path(network: str | None = None) -> Path:
    return scenario_for(network).net


@dataclass(frozen=True)
class CorridorSetup:
    """Immutable bundle handed to `run_controlled_scenario` for a live run."""

    sumocfg_path: str
    route_path: str
    configs: dict[str, Tier0Config]
    strategy: StrategySource
    link_lanes: dict[str, dict[str, str]]
    receiving_lanes: dict[str, dict[str, str]]
    vtype_pcu: dict[str, float]


def demand_paths(demand: str, network: str | None = None) -> tuple[Path, Path]:
    return scenario_for(network).level(demand)


def load_corridor(demand: str = "medium", network: str | None = None) -> CorridorSetup:
    """Load `network` (the configured scenario by default) at the given demand level with a Webster-tuned
    strategy per junction -- the same deterministic baseline
    `scripts/m6_record_features.py` runs. A demand-aware optimiser (A-CA-MP)
    can be swapped in later without touching the live loop."""
    scenario = scenario_for(network)
    sumocfg, route = scenario.level(demand)
    net = scenario.net
    configs = load_configs(net)
    flows = compute_link_flows(net, route)
    strategy = {
        tls_id: partial(
            webster.propose,
            timing=webster.compute_timing(cfg, flows.get(tls_id, {})),
        )
        for tls_id, cfg in configs.items()
    }
    return CorridorSetup(
        sumocfg_path=str(sumocfg),
        route_path=str(route),
        configs=configs,
        strategy=strategy,
        link_lanes=link_to_lane_map(net),
        receiving_lanes=link_to_receiving_lane_map(net),
        vtype_pcu=load_vtype_pcu(route),
    )
