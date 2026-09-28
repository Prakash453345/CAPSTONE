"""Wire the M6 detection pipeline (graph detector -> fusion -> conformal
threshold -> candidate raiser) into a live, per-tick hook that raises real
`itms_domain.incident.Incident` objects and publishes them onto the bus.

`scripts/m6_harness.py`'s `_Scorer` runs this exact pipeline already, but only
for offline scoring: it records `(node_index, sim_tick, graph_score)` tuples
in a Python list and hands them to the gate script, which compares them
against injected ground truth. Nothing about that path ever constructs a
domain `Incident` or touches the bus -- confirmed in
`contracts/events/README.md`'s M6 section ("schema (check), producer code
(check) and unit-tested, actually wired into a live run (cross)"). This
module is the missing piece: same detector -> fusion -> raiser pipeline,
`_Scorer.on_tick`'s exact per-tick math, but a newly-raised candidate becomes
a real `Incident.raise_candidate(...)` and gets published via this package's
own `IncidentPublisher` (`events.py`) as an `IncidentCandidate` event.

Construct one `LiveIncidentDetector` per run and pass its `on_tick` bound
method as `run_controlled_scenario`'s `anomaly_feature_sink` argument (with
`anomaly_graph` also given) -- it matches that parameter's call signature
`(step: int, sim_time: float, matrix: list[list[float]]) -> None` exactly,
the same signature `_Scorer.on_tick` implements, so this is a drop-in
production version of that harness class.

What this module deliberately does NOT do: decide what happens to a raised
candidate next. Per ADR-006's human-in-the-loop gate, only an operator (via
api-service, once it consumes `incident.candidate` -- see that service's own
module docstring for its current status) may CONFIRM or REJECT it, and
`itms_domain.incident.Incident` only allows those transitions from the state
CONFIRMED/REJECTED-issuing side, not the raising side. Auto-expiring a
candidate nobody acted on is a policy call that belongs with whoever owns the
canonical incident registry (api-service, not this in-process detector, which
has no visibility into what an operator does in a different process) -- so
it is intentionally left out here rather than half-built against state this
module cannot actually observe.

Requires a trained detector at `<artifacts_dir>/detector/` and held-out
normal features at `<artifacts_dir>/features/val/*.npy` (both produced by
`scripts/m6_record_features.py` + `scripts/m6_train_detector.py`, and
gitignored as regenerable build artifacts). Neither exists in a fresh
checkout. `LiveIncidentDetector.available` is False, and `on_tick` is then a
documented no-op (it does not even buffer frames), whenever:

  - the optional `[anomaly]` extra (torch/numpy) isn't installed, or
  - no trained detector directory exists, or
  - no held-out val features exist to calibrate the alert threshold tau from.

A live demo can therefore always construct and call this class safely; it
silently adds no incident detection until a real trained model is produced
and dropped in -- exactly the M6 status this project has been honest about
from the start (see README's "Current milestone": built end to end, not yet
accurate, because the model has only seen a tiny proof-of-training run).
`unavailable_reason` carries a human-readable explanation for whichever of
the three cases applies, for the live demo to log once at startup.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from itms_common.bus import RedisStreamsSyncBus
from itms_domain.incident import Incident

from sim_service.control.anomaly.events import IncidentPublisher
from sim_service.control.anomaly.graph_features import AnomalyGraph  # numpy/torch-free

if TYPE_CHECKING:
    from sim_service.control.anomaly.calibration import ConformalCalibrator
    from sim_service.control.anomaly.detector import GraphAnomalyDetector, WindowBuffer
    from sim_service.control.anomaly.fusion import CandidateRaiser, FusionLayer, RaiserConfig

log = logging.getLogger("sim-service.control.anomaly.live")

# feature_names index of "is_green" in graph_features.FEATURE_NAMES -- the
# same fixed index scripts/m6_harness.py's _Scorer.on_tick reads.
_IS_GREEN_FEATURE_IDX = 6

# scripts/m6_train_detector.py and scripts/m6_record_features.py both write
# here; this module reads the same layout by default. Path(__file__) is
# .../itms_komal/services/sim-service/sim_service/control/anomaly/live.py,
# so five ".parent"s up is the repo root -- the same computation
# scripts/m6_harness.py does starting from its own location.
DEFAULT_ARTIFACTS_DIR = Path(__file__).resolve().parents[5] / "scripts" / "results" / "m6_artifacts"


def _conformal_version(cal: ConformalCalibrator) -> str:
    """A short, stable identifier for the calibration snapshot in force, in
    the same spirit as `GraphAnomalyDetector.detector_version` (a hash, so a
    later candidate can be traced to exactly the threshold that raised it).
    Built only from public attributes (`cfg.alpha`, `n_points`, `tau`) rather
    than reaching into the calibrator's private score buffer."""
    tau = cal.tau
    tau_str = f"{tau:.6f}" if math.isfinite(tau) else "inf"
    h = hashlib.sha256(f"{cal.cfg.alpha}:{cal.n_points}:{tau_str}".encode()).hexdigest()[:8]
    return f"conformal@{h}"


def _calibrate_from_val_features(
    art_dir: Path, graph: AnomalyGraph, detector: GraphAnomalyDetector, alpha: float
) -> ConformalCalibrator | None:
    """Fit the conformal alert threshold on the held-out VAL normal-traffic
    feature runs `scripts/m6_record_features.py` records. Same logic as
    `scripts/m6_harness.py`'s `calibrate_from_val_features`, reimplemented
    here (rather than imported) because `scripts/` is a directory of
    standalone experiment scripts that push themselves onto `sys.path` --
    not an importable package a production module should depend on. Returns
    None if no val features exist yet."""
    import numpy as np

    from sim_service.control.anomaly.calibration import ConformalCalibrator, ConformalConfig
    from sim_service.control.anomaly.detector import WindowBuffer
    from sim_service.control.anomaly.graph_features import N_FEATURES

    val_dir = art_dir / "features" / "val"
    if not val_dir.exists():
        return None

    window = getattr(detector, "warmup_windows", 1)
    scores: list[float] = []
    for p in sorted(val_dir.glob("*.npy")):
        run = np.load(p).astype(np.float32)
        if run.shape[1:] != (graph.num_nodes, N_FEATURES):
            continue
        buf = WindowBuffer(window, graph.num_nodes)
        for frame in run:
            buf.push(frame)
            if buf.ready:
                scores.extend(detector.score(buf.array()))

    if not scores:
        return None
    cal = ConformalCalibrator(
        ConformalConfig(alpha=alpha, min_points=200, window=max(20_000, len(scores)))
    )
    cal.fit(scores)
    return cal


class LiveIncidentDetector:
    """Per-run: buffer -> `detector.score()` -> `fusion.probability()` ->
    `raiser.update()` -> publish. See the module docstring for exactly what
    this does and does not own.

    `feats[:, 1]` (persistence) and `feats[:, 4]` (vision_score) are left at
    0.0 -- the same simplification `scripts/m6_harness.py`'s `_Scorer.on_tick`
    makes, since neither is computed anywhere pre-M8 yet.
    """

    def __init__(
        self,
        graph: AnomalyGraph,
        bus: RedisStreamsSyncBus,
        *,
        artifacts_dir: str | Path = DEFAULT_ARTIFACTS_DIR,
        raiser_cfg: RaiserConfig | None = None,
        alpha: float = 0.05,
        source: str = "sim-service",
    ) -> None:
        self.graph = graph
        self._alpha = alpha
        self._publisher = IncidentPublisher(bus, source=source)
        self._adj = graph.adjacency_lists()

        self.available = False
        self.unavailable_reason = "not yet initialised"
        self.detector: GraphAnomalyDetector | None = None
        self.fusion: FusionLayer | None = None
        self.conformal: ConformalCalibrator | None = None
        self.raiser: CandidateRaiser | None = None
        self.buf: WindowBuffer | None = None
        self._detector_version = ""

        self.ticks_scored = 0
        self.raw_over_threshold = 0
        self.candidates_raised = 0

        self._load(Path(artifacts_dir), raiser_cfg)

    # ---- startup ------------------------------------------------------

    def _load(self, art: Path, raiser_cfg: RaiserConfig | None) -> None:
        try:
            from sim_service.control.anomaly.detector import GraphAnomalyDetector, WindowBuffer
            from sim_service.control.anomaly.fusion import (
                CandidateRaiser,
                FusionLayer,
                RaiserConfig,
            )
        except ImportError as exc:
            self._disable(
                f"the optional [anomaly] extra (torch/numpy) is not installed ({exc}) -- "
                "run `pip install -e 'services/sim-service[anomaly]'` (or `make test-anomaly`, "
                "which installs it) to enable live incident detection; the live demo runs "
                "fine without it, it just never raises incidents"
            )
            return

        detector_dir = art / "detector"
        if not detector_dir.exists():
            self._disable(
                f"no trained detector at {detector_dir} -- M6's model has only seen a "
                "proof-of-training run so far (see README's 'Current milestone'); train one "
                "with scripts/m6_record_features.py then scripts/m6_train_detector.py"
            )
            return

        try:
            detector = GraphAnomalyDetector.load(detector_dir, self.graph)
        except Exception as exc:  # noqa: BLE001 -- any load failure means "unavailable", not a crash
            self._disable(f"failed to load detector at {detector_dir}: {exc}")
            return

        conformal = _calibrate_from_val_features(art, self.graph, detector, self._alpha)
        if conformal is None:
            self._disable(
                f"no held-out normal features at {art / 'features' / 'val'} to calibrate the "
                "alert threshold from -- run scripts/m6_record_features.py first"
            )
            return

        self.detector = detector
        self.fusion = FusionLayer()
        self.conformal = conformal
        self.raiser = CandidateRaiser(self.graph.num_nodes, cfg=raiser_cfg or RaiserConfig())
        window = getattr(detector, "warmup_windows", 1)
        self.buf = WindowBuffer(window, self.graph.num_nodes)
        self._detector_version = f"{detector.detector_version}/{_conformal_version(conformal)}"
        self.available = True
        self.unavailable_reason = ""
        log.info(
            "LiveIncidentDetector enabled: detector_version=%s tau=%.3f "
            "(calibrated on %d normal-traffic points)",
            self._detector_version,
            conformal.tau,
            conformal.n_points,
        )

    def _disable(self, reason: str) -> None:
        self.available = False
        self.unavailable_reason = reason
        log.warning("LiveIncidentDetector disabled: %s", reason)

    # ---- per-tick hook --------------------------------------------

    def on_tick(self, step: int, sim_time: float, matrix: list[list[float]]) -> None:
        """Matches `run_controlled_scenario`'s `anomaly_feature_sink` call
        signature exactly -- pass this bound method straight through as that
        argument. A documented no-op whenever `self.available` is False."""
        if not self.available:
            return
        assert self.detector is not None
        assert self.fusion is not None
        assert self.conformal is not None
        assert self.raiser is not None
        assert self.buf is not None

        import numpy as np

        from sim_service.control.anomaly.fusion import neighbour_mean_scores

        self.buf.push(matrix)
        if not self.buf.ready:
            return

        win = self.buf.array()
        graph_score = self.detector.score(win)
        tau = self.conformal.tau
        neighbour_mean = neighbour_mean_scores(graph_score, self._adj)
        last_frame = win[-1]

        feats = np.zeros((self.graph.num_nodes, 5))
        feats[:, 0] = graph_score
        feats[:, 2] = neighbour_mean
        feats[:, 3] = last_frame[:, _IS_GREEN_FEATURE_IDX]
        fused = self.fusion.probability(feats, tau)

        self.ticks_scored += 1
        self.raw_over_threshold += int((fused >= 0.5).sum())

        for candidate in self.raiser.update(step, fused.tolist(), list(graph_score)):
            self._raise_incident(candidate, sim_tick=step, tau=tau)

    def _raise_incident(self, candidate, *, sim_tick: int, tau: float) -> None:
        i = candidate.node_index
        at_ms = int(time.time() * 1000)  # wall clock -- incident_candidate.avsc's `detected_at`
        # is explicitly documented as "never used for detection-latency arithmetic";
        # sim_tick (below) is what a latency measurement should use instead.
        inc = Incident.raise_candidate(
            incident_id=str(uuid.uuid4()),
            link_id=self.graph.link_of[i],
            intersection_id=self.graph.tls_of[i],
            at_ms=at_ms,
            graph_score=candidate.graph_score,
            fused_probability=candidate.fused_probability,
            threshold_tau=tau,
            false_alarm_budget=self._alpha,
            detector_version=self._detector_version,
        )
        self.candidates_raised += 1
        self._publisher.candidate(inc, sim_tick=sim_tick)
        log.info(
            "incident candidate raised: %s intersection=%s link=%s graph_score=%.2f tau=%.2f",
            inc.incident_id,
            inc.intersection_id,
            inc.link_id,
            inc.graph_score,
            tau,
        )

    # ---- introspection -----------------------------------------

    def stats(self) -> dict[str, float]:
        return {
            "available": float(self.available),
            "ticks_scored": float(self.ticks_scored),
            "raw_over_threshold": float(self.raw_over_threshold),
            "candidates_raised": float(self.candidates_raised),
            "tau": float(self.conformal.tau) if self.conformal is not None else float("nan"),
        }
