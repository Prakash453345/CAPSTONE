import type { DataMode } from "@/types";
import type { TrafficDataProvider } from "@/services/traffic/types";
import { createMockProvider } from "@/services/traffic/mockProvider";
import { createWebSocketProvider } from "@/services/traffic/wsProvider";

/**
 * Returns the data provider for the requested mode.
 *
 *   live        -> WebSocket provider against the ITMS api-service (real SUMO
 *                  state via sim-service). Also exposes `sendCommand` for
 *                  operator actions.
 *   simulation  -> in-browser mock provider (no backend required) — the
 *                  offline demo / design mode.
 *
 * This factory is the single place that choice is made.
 */
export function createTrafficProvider(mode: DataMode): TrafficDataProvider {
  switch (mode) {
    case "live":
      return createWebSocketProvider();
    case "simulation":
    default:
      return createMockProvider();
  }
}

export type { TrafficDataProvider, TrafficSnapshot } from "@/services/traffic/types";
export { CommandError, type OperatorCommand, type CommandResult } from "@/services/traffic/commands";
