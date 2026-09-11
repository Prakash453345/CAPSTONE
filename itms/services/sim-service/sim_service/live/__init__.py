"""The live, command-driven simulation service.

`sim_service.main` has two SUMO modes:

    SIM_MODE=sumo   (default, M1)  -> adapters/sumo/traci_loop.run
                    one-way SUMO -> Redis stream, no controller, no commands.
                    The M1-gate path. Untouched.

    SIM_MODE=live                  -> sim_service.live.service.run_live
                    control/runner.run_controlled_scenario promoted to a
                    long-running service: the arbitration ladder governs every
                    junction, the same M1 VehiclePositionUpdated / ApproachState
                    stream is published (so the api-service fan-out doesn't know
                    the difference), AND a `commands.*` topic is drained every
                    tick so an operator can create anomalies, dispatch an
                    emergency vehicle and request a green corridor against the
                    running simulation.

Both share `control/runner.py`; `live/` is only the wiring (corridor setup +
the command loop), not a second simulation engine.
"""
