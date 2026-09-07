"""M6 anomaly-detection stream [build guide M6; plan
`ITMS_Anomaly_Detection_Alert_System_Plan.docx`]. Stream 1 (pattern/graph),
buildable now on CPU against the project's own simulated traffic:

    injector.py        self-generated, exactly-labelled incidents (pillar 4.2)
    graph_features.py  static road graph + per-tick per-link feature tensor
    detector.py        spatiotemporal graph autoencoder + the EWMA baseline
                       it has to beat
    calibration.py     conformal alert threshold + online recalibration
    fusion.py          interpretable graph(+vision) -> probability, graph-only
                       until M8

Stream 2 (vision, M8) is designed in the plan and slots into `fusion.py`
without reworking this package -- not built until a real/recorded camera feed
exists.
"""
