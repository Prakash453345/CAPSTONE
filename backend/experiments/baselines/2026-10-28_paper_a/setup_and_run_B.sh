#!/usr/bin/env bash
# One-time setup on Preethi's Mac, then starts run_mac_B.sh. Run from the unzipped itms_paper_a folder:
#   cd ~/Downloads/itms_paper_a && caffeinate -i bash baselines/2026-10-28_paper_a/setup_and_run_B.sh
set -e
cd "$(dirname "$0")/../.."
PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
$PY -c 'import sys; assert sys.version_info >= (3, 11), "needs Python 3.11+ (python.org installer)"'
[ -x .venv/bin/python ] || $PY -m venv .venv
.venv/bin/pip install -q --upgrade pip
# one command: the packages depend on each other and are not on PyPI
.venv/bin/pip install -q -e packages/domain -e packages/common -e packages/geo -e services/sim-service -e services/vision-service sumo-data==1.27.1  # must match eclipse-sumo 1.27.1 (its libraries)
.venv/bin/python -c 'import sumo, sim_service, vision_service; print("setup ok, SUMO", sumo.__version__ if hasattr(sumo,"__version__") else "")'
md5 -r $(head -9 baselines/2026-10-28_paper_a/FROZEN.txt | awk '{print $2}') | awk '{print $1"  "$2}' > /tmp/frozen_now.txt
head -9 baselines/2026-10-28_paper_a/FROZEN.txt | diff - /tmp/frozen_now.txt && echo "frozen code verified"
bash baselines/2026-10-28_paper_a/run_mac_B.sh
