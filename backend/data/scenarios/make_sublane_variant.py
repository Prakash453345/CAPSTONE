"""Make a lane-less ("sublane") copy of a generated scenario, for the paper-A
Indian-traffic check (2026-10-28).

The Indian-mix scenarios already carry two-wheelers (~37 % of vehicles),
autos (~19 %), cars and buses, but SUMO ran them in lane-based mode: every
vehicle occupies a whole lane. This copy switches on SUMO's sublane model
(`--lateral-resolution 0.8`) and gives each class the lateral behaviour of
lane-less traffic: two-wheelers and autos filter between and beside cars and
pick any lateral position (`latAlignment="arbitrary"`), with small lateral
gaps (`minGapLat`) and the SL2015 lane-change model. Network, demand and
seeds are unchanged.

    python scenarios/make_sublane_variant.py arterial_lh vijayawada_district
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

GEN = Path(__file__).resolve().parent / "generated"

# vClass -> attributes added to its vType (literature values for mixed Indian traffic,
# e.g. Mathew et al.; SUMO docs, "Sublane model")
LATERAL = {
    "motorcycle": dict(latAlignment="arbitrary", minGapLat="0.3", maxSpeedLat="1.5",
                       lcSublane="5", lcPushy="0.6", width="0.8"),
    "taxi": dict(latAlignment="arbitrary", minGapLat="0.4", maxSpeedLat="1.0",
                 lcSublane="3", lcPushy="0.4", width="1.4"),
    "passenger": dict(latAlignment="center", minGapLat="0.5", maxSpeedLat="1.0",
                      lcSublane="1"),
    "bus": dict(latAlignment="center", minGapLat="0.6", maxSpeedLat="0.6"),
}


def _patch_vtype(m: re.Match) -> str:
    tag = m.group(0)
    vc = re.search(r'vClass="([^"]+)"', tag)
    extra = LATERAL.get(vc.group(1), {}) if vc else {}
    if 'laneChangeModel=' not in tag:
        extra = {"laneChangeModel": "SL2015", **extra}
    for k, v in extra.items():
        if f'{k}="' in tag:
            tag = re.sub(rf'{k}="[^"]*"', f'{k}="{v}"', tag)
        else:
            tag = tag.replace("<vType ", f'<vType {k}="{v}" ', 1)
    return tag


def make(name: str) -> Path:
    src, dst = GEN / name, GEN / f"{name}_sublane"
    dst.mkdir(exist_ok=True)
    scen = json.loads((src / "scenario.json").read_text())
    for f in src.iterdir():
        if f.suffix == ".xml" and f.name.endswith(".rou.xml"):
            (dst / f.name).write_text(re.sub(r"<vType [^>]*>", _patch_vtype, f.read_text()))
        elif f.name.endswith(".sumocfg"):
            txt = f.read_text()
            if "lateral-resolution" not in txt:
                txt = txt.replace("</processing>", '    <lateral-resolution value="0.8"/>\n'
                                  "    </processing>")
            (dst / f.name).write_text(txt)
        elif f.name != "scenario.json" and f.is_file():
            shutil.copy2(f, dst / f.name)
    scen["name"] = f"{name}_sublane"
    scen["sublane"] = {"lateral_resolution_m": 0.8, "classes": LATERAL}
    (dst / "scenario.json").write_text(json.dumps(scen, indent=1))
    return dst


if __name__ == "__main__":
    for n in sys.argv[1:]:
        print(make(n))
