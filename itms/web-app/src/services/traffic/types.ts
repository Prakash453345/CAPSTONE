import type {
  Anomaly,
  DataMode,
  EmergencyRequest,
  Incident,
  Intersection,
  NotificationEvent,
  SystemSummary,
  Vehicle,
} from "@/types";
import type { CommandResult, OperatorCommand } from "@/services/traffic/commands";

/**
 * The normalised shape every data provider emits. Screens and stores only ever
 * see this — never a backend wire format. A mock provider produces it now
 * (Phase 2); a WebSocket provider will produce the same thing in Phase 9.
 */
export interface TrafficSnapshot {
  /** ISO timestamp this snapshot represents. */
  timestamp: string;
  vehicles: Vehicle[];
  intersections: Intersection[];
  incidents: Incident[];
  /** Operator-created + auto-detected anomalies currently on the network. */
  anomalies: Anomaly[];
  /** Live emergency dispatches with their routes (SIM_MODE=live). */
  emergencyRequests: EmergencyRequest[];
  /** edgeId -> congestion index 0..1. */
  roadCongestion: Record<string, number>;
  summary: SystemSummary;
  /** Noteworthy things that happened since the last snapshot — freshly
   *  produced each call, not an accumulated log (that lives in
   *  `notificationStore`). Legitimately empty most snapshots. */
  events: NotificationEvent[];
}

export interface TrafficDataProvider {
  readonly mode: DataMode;
  /** Begin producing snapshots. Idempotent. */
  start(): void;
  /** Stop and release timers/sockets. Idempotent. */
  stop(): void;
  /** Register a snapshot listener; returns an unsubscribe fn. */
  subscribe(listener: (snapshot: TrafficSnapshot) => void): () => void;
  /** Register a connection-state listener; returns an unsubscribe fn. */
  onStatus(listener: (status: ProviderStatus) => void): () => void;
  /**
   * Send an operator command to the backend. Present only on providers backed
   * by a real api-service (the WebSocket provider); the mock provider omits it,
   * so callers must feature-detect (`provider.sendCommand?.(cmd)`).
   */
  sendCommand?(command: OperatorCommand): Promise<CommandResult>;
}

export type ProviderStatus =
  | "connecting"
  | "online"
  | "reconnecting"
  | "offline";
