"""Which road network the system runs on -- one definition for every service
and script.

The project was built on the Vijayawada corridor, and until this module every
entry point named its files directly. Now they ask here. With no
`ITMS_SCENARIO` set, the answer is the Vijayawada corridor, exactly as
before. With `ITMS_SCENARIO=<dir>`, it is the scenario in that directory: one
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

ENV = "ITMS_SCENARIO"
_REPO = Path(__file__).resolve().parents[3]


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


def vijayawada(repo: Path = _REPO) -> Scenario:
    net_dir = repo / "scenarios" / "networks" / "vijayawada"
    demand = repo / "scenarios" / "demand" / "vijayawada"
    suffix = {"light": "_light", "medium": "", "heavy": "_heavy"}
    return Scenario(
        name="vijayawada",
        directory=net_dir,
        net=net_dir / "vijayawada_corridor.net.xml",
        levels={lv: (demand / f"vijayawada_corridor{s}.sumocfg",
                     demand / f"vijayawada_corridor{s}.rou.xml") for lv, s in suffix.items()},
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
    """`ITMS_SCENARIO`'s scenario, or the Vijayawada corridor when unset."""
    d = os.environ.get(ENV)
    return from_directory(d) if d else vijayawada()
