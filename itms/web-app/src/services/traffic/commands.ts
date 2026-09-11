/**
 * Operator -> backend command channel. A thin POST to the api-service, which
 * wraps the body in the standard EventEnvelope and publishes it on
 * `commands.operator`; sim-service (SIM_MODE=live) drains that topic each tick.
 *
 * Kept separate from the data provider on purpose: reading traffic state and
 * issuing commands are different concerns, and commands always go to the real
 * backend regardless of which data mode the map is showing.
 */

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
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/v1/commands`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(cmd),
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
