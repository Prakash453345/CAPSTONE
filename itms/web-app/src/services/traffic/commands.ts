/**
 * Operator -> backend command channel. A thin POST to the api-service, which
 * wraps the body in the standard EventEnvelope and publishes it on
 * `commands.operator`; sim-service (SIM_MODE=live) drains that topic each tick.
 *
 * Kept separate from the data provider on purpose: reading traffic state and
 * issuing commands are different concerns. Mutations target the real backend
 * only in connected Live mode; the browser Demo must never issue commands.
 */

import { useSystemStore } from "@/store/systemStore";

/** Matches api-service `CommandRequest`. `payload` must match the schema named
 *  by `event_type` in `contracts/events/`. */
export interface OperatorCommand {
  event_type: string;
  payload: Record<string, unknown>;
  operator?: string;
}

export interface CommandResult {
  published: boolean;
  topic: string;
  message_id: string;
}

/** Base path for the api-service. In dev, Vite proxies `/api` -> `:8000`. */
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class CommandError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "CommandError";
  }
}

export async function postCommand(cmd: OperatorCommand): Promise<CommandResult> {
  const system = useSystemStore.getState();
  if (system.dataMode !== "live") throw new CommandError(409, "Demo is read-only. Switch to Live to issue simulation commands.");
  if (system.connectionStatus !== "online") throw new CommandError(409, "Live stream is not connected. Reconnect before issuing commands.");
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/v1/commands`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(cmd),
      signal: AbortSignal.timeout(10_000),
    });
  } catch (err) {
    throw new CommandError(0, `could not reach the command API: ${String(err)}`);
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new CommandError(res.status, detail);
  }
  return (await res.json()) as CommandResult;
}
