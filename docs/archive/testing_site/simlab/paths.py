"""Where everything lives, resolved once.

Archived: `docs/archive/testing_site/` inside CAPSTONE, reading the backend at
`CAPSTONE/backend/`. Nothing in this package ever writes into the backend -- it is read-only source of truth for the network,
the demand scenarios, the facilities list and the event contracts. Everything
this tool generates (custom scenarios, logs, run artefacts) goes under
`testing_site/var/`, which is disposable.

Every path is resolved relative to this file rather than the working
directory, so `python3 server.py` works from anywhere.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# simlab/paths.py -> simlab -> testing_site -> archive -> docs -> CAPSTONE
SITE_DIR = Path(__file__).resolve().parents[1]
CAPSTONE_DIR = SITE_DIR.parents[2]

# `ITMS_REPO` lets the site drive a checkout somewhere else (e.g. the working
# copy at ~/Documents/capstone/itms) without moving the site itself.
REPO = Path(os.environ.get("ITMS_REPO") or (CAPSTONE_DIR / "backend")).resolve()

# --- read-only, inside the repo -------------------------------------------
NET_DIR = REPO / "data" / "scenarios" / "networks" / "vijayawada"
NET_PATH = NET_DIR / "vijayawada_corridor.net.xml"
GEOJSON_PATH = NET_DIR / "vijayawada_corridor.geojson"
FACILITIES_PATH = NET_DIR / "facilities.json"
DEMAND_DIR = REPO / "data" / "scenarios" / "demand" / "vijayawada"
CONTRACTS_DIR = REPO / "contracts" / "events"
SCRIPTS_DIR = REPO / "experiments"
RESULTS_DIR = SCRIPTS_DIR / "results"
WEB_DIR = CAPSTONE_DIR / "docs" / "archive" / "legacy-web-demo"
LEAFLET_DIR = WEB_DIR / "vendor" / "leaflet"
VENV_DIR = REPO / ".venv"

# --- writable, inside testing_site ----------------------------------------
STATIC_DIR = SITE_DIR / "static"
RUNNER_DIR = SITE_DIR / "runner"
VAR_DIR = SITE_DIR / "var"
RUNS_DIR = VAR_DIR / "runs"
LOG_DIR = VAR_DIR / "logs"
STATE_PATH = VAR_DIR / "state.json"

# The three demand levels the repo ships, keyed the way `sim_service.live.
# corridor._DEMAND_SUFFIX` keys them. Vehicle counts and periods are from
# `scenarios/demand/vijayawada/build_demand_levels.sh`.
DEMAND_LEVELS = {
    "light": {"suffix": "_light", "period_s": 5.0, "approx_vehicles": 354},
    "medium": {"suffix": "", "period_s": 2.5, "approx_vehicles": 708},
    "heavy": {"suffix": "_heavy", "period_s": 1.25, "approx_vehicles": 1416},
}


def ensure_var_dirs() -> None:
    for d in (VAR_DIR, RUNS_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def demand_paths(level: str) -> tuple[Path, Path]:
    """(sumocfg, rou.xml) for one of the three shipped demand levels."""
    if level not in DEMAND_LEVELS:
        raise ValueError(f"demand must be one of {sorted(DEMAND_LEVELS)}, got {level!r}")
    suffix = DEMAND_LEVELS[level]["suffix"]
    return (
        DEMAND_DIR / f"vijayawada_corridor{suffix}.sumocfg",
        DEMAND_DIR / f"vijayawada_corridor{suffix}.rou.xml",
    )


def _version_key(path: Path) -> tuple:
    """Sort `python3.14` above `python3.9` -- lexical order gets this wrong,
    and picking the older interpreter out of a venv is a confusing failure."""
    tail = path.name.removeprefix("python")
    try:
        return tuple(int(p) for p in tail.split("."))
    except ValueError:
        return ()


def venv_python() -> Path | None:
    """The repo's own interpreter, which is the only one with `traci`,
    `itms_common` and the services installed. `make setup` creates it.

    Checks more than `bin/python` on purpose. A venv's `python` is a symlink
    to a versioned name and on to the base install, and which of the three
    names exists depends on how the venv was made -- so all of them are
    tried, newest version first. `.exists()` follows symlinks, so a venv whose
    base Python has been uninstalled or moved is correctly reported as having
    no interpreter rather than handing back a path that cannot execute; see
    `venv_problem` for saying so out loud.
    """
    candidates = [
        VENV_DIR / "bin" / "python",
        VENV_DIR / "bin" / "python3",
        VENV_DIR / "Scripts" / "python.exe",
    ]
    candidates += sorted(VENV_DIR.glob("bin/python3.*"), key=_version_key, reverse=True)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def venv_problem() -> str | None:
    """Why the venv is unusable, when it exists but yields no interpreter.

    Distinct from "not created yet", which the banner already covers. This is
    the nastier case: `.venv/` is full of working console scripts, so it looks
    fine, but every one of them starts with a shebang pointing at an
    interpreter that is gone -- nothing runs and the error is opaque. Worth
    naming precisely rather than falling back to the system Python and
    failing later with a missing-module traceback.
    """
    if venv_python() is not None or not VENV_DIR.is_dir():
        return None
    dangling = [p for p in VENV_DIR.glob("bin/python*") if p.is_symlink() and not p.exists()]
    if dangling:
        try:
            target = os.readlink(dangling[0])
        except OSError:
            target = "?"
        return (
            f"{VENV_DIR} exists, but its interpreter link is dangling "
            f"({dangling[0].name} -> {target}) -- the Python it was built against has "
            f"moved or been uninstalled. Recreate it: rm -rf .venv && make setup"
        )
    return (
        f"{VENV_DIR} exists but holds no Python interpreter. Recreate it: "
        f"rm -rf .venv && make setup"
    )


def runner_python() -> Path:
    """Interpreter used for the simulation subprocess. Falls back to the one
    running this server, which will fail loudly (and legibly, in the run log)
    if the repo has not been set up yet -- better than pretending."""
    return venv_python() or Path(sys.executable)


def venv_bin(name: str) -> Path | None:
    candidate = VENV_DIR / "bin" / name
    if candidate.exists():
        return candidate
    found = shutil.which(name)
    return Path(found) if found else None


def repo_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for any child process that imports the repo's packages.

    The scenario helpers under `scenarios/networks/vijayawada/` are not an
    installed package -- every gate script adds that directory to `sys.path`
    itself. The runner does the same, but putting it on PYTHONPATH too means
    a plain `python -m sim_service.main` child works without the repo being
    pip-installed in editable mode.
    """
    env = dict(os.environ)
    parts = [
        str(REPO / "packages" / "common"),
        str(REPO / "packages" / "domain"),
        str(REPO / "services" / "sim-service"),
        str(REPO / "services" / "api-service"),
        str(NET_DIR),
    ]
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONUNBUFFERED"] = "1"
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


def repo_status() -> dict:
    """What the site can and cannot do with this checkout, answered honestly
    up front rather than as a stack trace on first use."""
    py = venv_python()
    sumo = venv_bin("sumo")
    return {
        "capstone_dir": str(CAPSTONE_DIR),
        "repo": str(REPO),
        "repo_found": REPO.is_dir(),
        "network_found": NET_PATH.exists(),
        "geojson_found": GEOJSON_PATH.exists(),
        "facilities_found": FACILITIES_PATH.exists(),
        "leaflet_found": (LEAFLET_DIR / "leaflet.js").exists(),
        "venv_python": str(py) if py else None,
        "venv_problem": venv_problem(),
        "sumo_binary": str(sumo) if sumo else None,
        "docker": shutil.which("docker"),
        "redis_server": shutil.which("redis-server"),
        "demand_levels": {
            level: {
                **meta,
                "sumocfg": str(demand_paths(level)[0]),
                "present": demand_paths(level)[0].exists() and demand_paths(level)[1].exists(),
            }
            for level, meta in DEMAND_LEVELS.items()
        },
    }
