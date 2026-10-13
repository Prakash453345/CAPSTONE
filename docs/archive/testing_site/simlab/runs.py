"""Run registry: what was tested, under what settings, and what came out.

A "run" is one simulation started from the site. Each gets a directory under
`var/runs/<id>/` holding its generated scenario (if custom), `status.json`
(live, rewritten by the runner), `tripinfo.xml` and `result.json` (final).
The index itself is kept in `var/state.json` so run history survives a server
restart, which matters because comparing two runs usually means comparing one
you did ten minutes ago with one you just finished.

The comparison is deliberately plain: a paired table of the same KPIs, with
percentage deltas and an explicit note that two single runs on different seeds
are not a statistical result. The repo's own gate scripts do the 30-paired-seed
Wilcoxon work; pretending a one-vs-one here is the same thing would be exactly
the kind of number this project's honesty norm exists to prevent.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from simlab import paths

# KPI key -> (label, unit, lower_is_better)
KPI_FIELDS: dict[str, tuple[str, str, bool]] = {
    "person_delay_s": ("Person delay", "person-s", True),
    "person_throughput_per_hour": ("Person throughput", "persons/h", False),
    "wait_mean_s": ("Mean wait", "s", True),
    "wait_p95_s": ("Wait p95", "s", True),
    "wait_max_s": ("Worst wait", "s", True),
    "stops_per_vehicle": ("Stops per vehicle", "stops", True),
    "n_trips_total": ("Trips completed", "trips", False),
}


class RunStore:
    def __init__(self) -> None:
        paths.ensure_var_dirs()
        self.path = paths.STATE_PATH
        self.runs: dict[str, dict] = {}
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.runs = {r["id"]: r for r in data.get("runs", []) if r.get("id")}
        except (ValueError, OSError, KeyError):
            self.runs = {}

    def _save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"runs": list(self.runs.values())}, indent=2, default=str),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except OSError:
            pass

    # -- lifecycle ---------------------------------------------------------
    def create(self, config: dict, *, label: str = "") -> dict:
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        run_dir = paths.RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "id": run_id,
            "label": label or _auto_label(config),
            "created_at": time.time(),
            "config": config,
            "dir": str(run_dir),
            "status_path": str(run_dir / "status.json"),
            "state": "created",
            "metrics": None,
            "counters": None,
            "od": None,
            "notes": "",
            "checks": {},
        }
        self.runs[run_id] = record
        self._save()
        return record

    def get(self, run_id: str) -> dict | None:
        return self.runs.get(run_id)

    def list(self) -> list[dict]:
        return sorted(self.runs.values(), key=lambda r: r["created_at"], reverse=True)

    def delete(self, run_id: str) -> bool:
        if run_id not in self.runs:
            return False
        self.runs.pop(run_id)
        self._save()
        return True

    def annotate(self, run_id: str, **fields) -> dict | None:
        run = self.runs.get(run_id)
        if run is None:
            return None
        for key in ("label", "notes"):
            if key in fields and fields[key] is not None:
                run[key] = str(fields[key])
        if isinstance(fields.get("checks"), dict):
            run.setdefault("checks", {}).update(fields["checks"])
        self._save()
        return run

    def live_status(self, run_id: str) -> dict | None:
        """Read the runner's own status file. Source of truth while a run is
        in flight; also folded back into the index when the run ends so the
        history table has KPIs without re-reading files."""
        run = self.runs.get(run_id)
        if run is None:
            return None
        p = Path(run["status_path"])
        if not p.exists():
            return {"state": run.get("state", "created"), "run_id": run_id}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {"state": "unreadable", "run_id": run_id}
        if data.get("state") in ("finished", "stopped", "failed"):
            changed = (
                run.get("state") != data.get("state")
                or run.get("metrics") != data.get("metrics")
            )
            run["state"] = data["state"]
            run["metrics"] = data.get("metrics")
            run["counters"] = data.get("counters")
            run["od"] = data.get("od")
            run["summary"] = data.get("summary")
            run["error"] = data.get("error")
            if changed:
                self._save()
        elif run.get("state") != data.get("state"):
            run["state"] = data.get("state", run.get("state"))
            self._save()
        return data

    # -- comparison / export ----------------------------------------------
    def compare(self, ids: list[str]) -> dict:
        chosen = [self.runs[i] for i in ids if i in self.runs]
        for run in chosen:
            self.live_status(run["id"])
        rows = []
        for key, (label, unit, lower_better) in KPI_FIELDS.items():
            values = [
                (run["metrics"] or {}).get(key) if isinstance(run.get("metrics"), dict) else None
                for run in chosen
            ]
            numeric = [v for v in values if isinstance(v, (int, float))]
            best = None
            if len(numeric) > 1:
                best = (min if lower_better else max)(numeric)
            rows.append(
                {
                    "key": key,
                    "label": label,
                    "unit": unit,
                    "lower_is_better": lower_better,
                    "values": values,
                    "best": best,
                    "delta_pct": _delta_pct(values),
                }
            )
        return {
            "runs": [
                {
                    "id": r["id"],
                    "label": r.get("label"),
                    "state": r.get("state"),
                    "config": r.get("config"),
                    "metrics": r.get("metrics"),
                    "od": r.get("od"),
                }
                for r in chosen
            ],
            "rows": rows,
            "caveat": (
                "Two runs are two samples, not a result. Different seeds move these "
                "numbers on their own. For a claim worth defending, use the repo's "
                "gate scripts -- they run paired seeds with confidence intervals."
            ),
        }

    def export_csv(self, ids: list[str] | None = None) -> str:
        chosen = [self.runs[i] for i in (ids or list(self.runs)) if i in self.runs]
        for run in chosen:
            self.live_status(run["id"])
        cfg_cols = ["demand", "controller", "engine", "realtime_factor", "step_length", "seed"]
        header = ["run_id", "label", "created_at", "state", *cfg_cols, *KPI_FIELDS]
        header += ["od_requested", "od_target", "od_arrived", "od_target_met"]
        lines = [",".join(header)]
        for r in chosen:
            cfg = r.get("config") or {}
            m = r.get("metrics") or {}
            od = r.get("od") or {}
            row = [
                r["id"],
                _csv(r.get("label")),
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["created_at"])),
                r.get("state") or "",
                *[_csv(cfg.get(c)) for c in cfg_cols],
                *[_csv(m.get(k)) for k in KPI_FIELDS],
                _csv(od.get("requested")),
                _csv(od.get("target_arrivals")),
                _csv(od.get("arrived")),
                _csv(od.get("target_met")),
            ]
            lines.append(",".join(row))
        return "\n".join(lines) + "\n"

    def export_json(self, ids: list[str] | None = None) -> dict:
        chosen = [self.runs[i] for i in (ids or list(self.runs)) if i in self.runs]
        for run in chosen:
            self.live_status(run["id"])
        return {
            "exported_at": time.time(),
            "source": "ITMS testing_site",
            "repo": str(paths.REPO),
            "runs": chosen,
        }


def _auto_label(config: dict) -> str:
    demand = config.get("demand", "?")
    controller = config.get("controller", "?")
    if demand == "custom":
        od = config.get("od") or {}
        return f"custom {od.get('count', '?')}x {od.get('origin', '?')}->{od.get('destination', '?')} / {controller}"
    return f"{demand} / {controller}"


def _delta_pct(values: list[Any]) -> float | None:
    """Second column against the first, as a signed percentage. Only defined
    for exactly two comparable runs -- the honest shape for an A/B."""
    if len(values) != 2:
        return None
    a, b = values
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or a == 0:
        return None
    return round((b - a) / abs(a) * 100.0, 2)


def _csv(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if any(c in text for c in ',"\n'):
        return '"' + text.replace('"', '""') + '"'
    return text
