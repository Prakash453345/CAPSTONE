"""Which road network the system runs on -- one definition for every service
and script.

The project was built on the Vijayawada corridor, and until this module every
entry point named its files directly. Now they ask here. With no
`ITMS_SCENARIO` set, the answer is one of the two Vijayawada networks named by
`SIM_NETWORK`: "corridor" (the default, exactly as before -- the single MG
Road arterial every offline gate is measured on) or "district" (the
surrounding arterial grid, `scenarios/networks/vijayawada/build_district.sh`,
where emergency routes genuinely compete). With `ITMS_SCENARIO=<dir>`, it is
the scenario in that directory: one
built by `scenarios/build_scenario.py` from any SUMO network (generated, or an
OpenStreetMap export), described by its `scenario.json`:

    {"name": ..., "net": "x.net.xml",
     "levels": {"light": {"sumocfg": ..., "route": ...}, "medium": ..., "heavy": ...},
     "cameras_file": "cameras.json"}

Optional files next to it are picked up when present: `facilities.json` and
`responder_depots.json` (hospitals and police for the live incident layer)
and `sat_flow_calibration.json` (measured saturation flows). A network
without them still runs; the incident layer then has nowhere to send units.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from itms_domain.paths import VIJAYAWADA_DEMAND_DIR, VIJAYAWADA_NET_DIR

ENV = "ITMS_SCENARIO"
NETWORK_ENV = "SIM_NETWORK"
VIJAYAWADA_NETWORKS = ("corridor", "district")


@dataclass(frozen=True)
class Scenario:
    name: str
    directory: Path          # where the optional files live (facilities, calibration)
    net: Path
    levels: dict[str, tuple[Path, Path]]   # level -> (sumocfg, route)
    cameras: Path

    def level(self, name: str) -> tuple[Path, Path]:
        if name not in self.levels:
            raise ValueError(f"scenario {self.name!r} has no demand level {name!r} "
                             f"(it has {sorted(self.levels)})")
        return self.levels[name]


def vijayawada(network: str = "corridor") -> Scenario:
    if network not in VIJAYAWADA_NETWORKS:
        raise ValueError(f"network must be one of {list(VIJAYAWADA_NETWORKS)}, got {network!r}")
    net_dir = VIJAYAWADA_NET_DIR
    demand = VIJAYAWADA_DEMAND_DIR
    suffix = {"light": "_light", "medium": "", "heavy": "_heavy"}
    return Scenario(
        name="vijayawada" if network == "corridor" else f"vijayawada-{network}",
        directory=net_dir,
        net=net_dir / f"vijayawada_{network}.net.xml",
        levels={lv: (demand / f"vijayawada_{network}{s}.sumocfg",
                     demand / f"vijayawada_{network}{s}.rou.xml") for lv, s in suffix.items()},
        # planned against the corridor's junctions; not re-planned for the district
        cameras=net_dir / "cameras.json",
    )


def from_directory(directory: str | Path) -> Scenario:
    d = Path(directory).resolve()
    manifest = json.loads((d / "scenario.json").read_text())
    return Scenario(
        name=manifest["name"],
        directory=d,
        net=d / manifest["net"],
        levels={lv: (d / v["sumocfg"], d / v["route"]) for lv, v in manifest["levels"].items()},
        cameras=d / manifest.get("cameras_file", "cameras.json"),
    )


def current() -> Scenario:
    """`ITMS_SCENARIO`'s scenario, else the Vijayawada network `SIM_NETWORK`
    names (the corridor when unset). Setting both is an error: they would name
    two different networks."""
    d = os.environ.get(ENV)
    network = os.environ.get(NETWORK_ENV)
    if d and network:
        raise ValueError(f"set {ENV} or {NETWORK_ENV}, not both "
                         f"({ENV}={d!r}, {NETWORK_ENV}={network!r})")
    return from_directory(d) if d else vijayawada(network=network or "corridor")
