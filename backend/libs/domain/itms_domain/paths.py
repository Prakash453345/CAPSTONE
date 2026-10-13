"""Where everything lives in the backend, defined once.

It lives in itms_domain, the bottom layer with no dependencies, so every
package can import it. Every service, library, test and experiment script asks
here instead of
counting `parents[n]` from its own file, so moving a folder means changing one
line, not forty. The layout:

    backend/
    |-- services/          deployable services (api-gateway, simulation-service, vision-service)
    |-- libs/              shared packages (common, domain, geo)
    |-- contracts/events/  Avro event schemas
    |-- data/
    |   |-- scenarios/     SUMO networks and demand (committed)
    |   `-- models/        trained model weights (not committed)
    |-- ml/notebooks/      training notebooks
    |-- experiments/       benchmark / gate scripts, results/, baselines/
    `-- var/               runtime state: uploaded clips, evidence (not committed)

`ITMS_BACKEND_ROOT` overrides the root, for an install that is not an
editable checkout (a container image copies the data next to the code).
"""

from __future__ import annotations

import os
from pathlib import Path


def _find_backend_root() -> Path:
    env = os.environ.get("ITMS_BACKEND_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "libs").is_dir() \
                and (parent / "services").is_dir():
            return parent
    raise RuntimeError(
        f"cannot find the backend root above {here}; set ITMS_BACKEND_ROOT to the "
        "directory that holds services/, libs/ and data/")


BACKEND_ROOT = _find_backend_root()

SERVICES_DIR = BACKEND_ROOT / "services"
CONTRACTS_DIR = BACKEND_ROOT / "contracts" / "events"

DATA_DIR = BACKEND_ROOT / "data"
SCENARIOS_DIR = DATA_DIR / "scenarios"
NETWORKS_DIR = SCENARIOS_DIR / "networks"
DEMAND_DIR = SCENARIOS_DIR / "demand"
VIJAYAWADA_NET_DIR = NETWORKS_DIR / "vijayawada"
VIJAYAWADA_DEMAND_DIR = DEMAND_DIR / "vijayawada"
MODELS_DIR = DATA_DIR / "models"

EXPERIMENTS_DIR = BACKEND_ROOT / "experiments"
RESULTS_DIR = EXPERIMENTS_DIR / "results"
BASELINES_DIR = EXPERIMENTS_DIR / "baselines"

VAR_DIR = BACKEND_ROOT / "var"
