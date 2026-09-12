"""M6 incident-service: event-driven anomaly detection consumer.

Consumes ApproachState and SignalChanged events from the Redis Streams bus,
runs the graph anomaly detector on a sliding window of per-edge features,
and publishes IncidentCandidate events when the conformal-calibrated
threshold is exceeded.

Designed for graceful degradation: runs graph-only until M8 adds the vision
stream -- the fusion layer simply ignores the absent vision_score.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from itms_common.bus import RedisStreamsBus
from itms_common.events import decode_envelope

from incident_service.config import IncidentServiceConfig
from incident_service.fusion import FusionLayer
from incident_service.gate import IncidentGate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s incident-service %(message)s",
)
log = logging.getLogger("incident-service")


def _try_load_detector(config: IncidentServiceConfig):
    """Attempt to load the trained anomaly detector.

    Returns (detector, calibrator) if model files exist, otherwise
    (None, None) -- the service still accepts confirm/reject via the API
    but won't score new observations until a model is trained.
    """
    model_path = Path(config.model_path)
    graph_path = Path(config.graph_path)
    scaler_path = Path(config.scaler_path)
    conformal_path = Path(config.conformal_path)

    if not all(p.exists() for p in [model_path, graph_path, scaler_path]):
        log.warning(
            "model files not found -- running without anomaly detector "
            "(train first via `make m6-train`)"
        )
        return None, None

    try:
        import torch
        from itms_anomaly.graph import build_graph_from_json
        from itms_anomaly.model import SpatioTemporalGAE
        from itms_anomaly.detector import AnomalyDetector
        from itms_anomaly.dataset import FeatureScaler
        from itms_anomaly.conformal import ConformalCalibrator

        edge_index, node_index = build_graph_from_json(str(graph_path))
        model = SpatioTemporalGAE(in_features=6)
        model.load_state_dict(
            torch.load(str(model_path), map_location="cpu", weights_only=True)
        )
        model.eval()

        scaler = FeatureScaler.load(str(scaler_path))

        if conformal_path.exists():
            calibrator = ConformalCalibrator.load(str(conformal_path))
        else:
            calibrator = ConformalCalibrator(alpha=config.conformal_alpha)
            log.warning("conformal calibrator not found -- using default")

        detector = AnomalyDetector(
            model=model,
            edge_index=edge_index,
            node_index=node_index,
            scaler=scaler,
            window_size=config.window_size,
            z_window=config.z_window,
        )

        log.info(
            "loaded anomaly detector: %d nodes, threshold=%.4f",
            len(node_index), calibrator.threshold,
        )
        return detector, calibrator

    except Exception:
        log.exception("failed to load anomaly detector")
        return None, None


async def _consume_and_detect(config: IncidentServiceConfig) -> None:
    """Main consumer loop: subscribe → buffer → detect → gate."""
    bus = RedisStreamsBus(config.redis_url)
    detector, calibrator = _try_load_detector(config)
    fusion = FusionLayer()
    gate = IncidentGate(calibrator, config.database_url, bus)

    current_features: dict[str, dict[str, float]] = {}
    junction_phases: dict[str, str] = {}
    tick_count = 0

    topics = [config.approach_state_topic, config.signal_changed_topic]
    log.info("subscribing to %s", topics)

    async for msg in bus.subscribe(
        topics, group=config.consumer_group, consumer=config.consumer_name
    ):
        try:
            envelope = decode_envelope(msg.raw)
            event_type = envelope["event_type"]
            payload = envelope["payload"]

            if event_type == "ApproachState":
                edge_id = payload.get("movement_id", "")
                if edge_id and not edge_id.startswith(":"):
                    current_features[edge_id] = {
                        "queue_pcu": float(payload.get("q_pcu", 0)),
                        "receiving_occupancy": 0.0,
                        "mean_speed_mps": 0.0,
                        "occupancy": float(payload.get("occupancy", 0)),
                        "wait_time_s": 0.0,
                        "vehicle_count": float(payload.get("q_pcu", 0)),
                    }

            elif event_type == "SignalChanged":
                junction_id = payload.get("intersection_id", "")
                phase = payload.get("phase_id", "")
                if junction_id:
                    junction_phases[junction_id] = phase

            tick_count += 1

            if detector is not None and tick_count >= config.window_size:
                detector.update(current_features)
                scores = detector.score()

                for link_id, z_score in scores.items():
                    if z_score > config.pre_screen_threshold:
                        intersection_id = None
                        phase_is_green = False
                        signal_phase = None
                        for jid, phase in junction_phases.items():
                            if phase and "G" in phase.upper():
                                intersection_id = jid
                                phase_is_green = True
                                signal_phase = phase
                                break

                        fused_score = fusion.fuse(
                            graph_score=z_score,
                            phase_is_green=phase_is_green,
                        )

                        await gate.check_and_raise(
                            link_id=link_id,
                            graph_score=z_score,
                            fused_score=fused_score,
                            features=current_features.get(link_id, {}),
                            signal_phase=signal_phase,
                            intersection_id=intersection_id,
                        )

                tick_count = 0

        except Exception:
            log.exception(
                "failed to handle message %s on %s",
                msg.message_id, msg.topic,
            )
        else:
            await bus.ack(msg.topic, config.consumer_group, msg.message_id)


async def main() -> None:
    config = IncidentServiceConfig()
    log.info("starting incident-service (alpha=%.2f)", config.conformal_alpha)

    shutdown = asyncio.Event()

    def _signal_handler() -> None:
        log.info("shutdown requested")
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows

    consumer = asyncio.create_task(_consume_and_detect(config))
    await shutdown.wait()
    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass
    log.info("incident-service stopped")


if __name__ == "__main__":
    asyncio.run(main())
