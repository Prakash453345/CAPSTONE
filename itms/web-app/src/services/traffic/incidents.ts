import { junctionById } from "@/data/network";
import type { Incident } from "@/types";
import { CommandError } from "@/services/traffic/commands";
import { useSystemStore } from "@/store/systemStore";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";
const classificationType: Record<string, Incident["type"]> = {
  STALL: "breakdown",
  QUEUE_SPILLBACK: "congestion",
};

/** Normalize both REST registry rows and stream events without inventing locations. */
export function mapIncident(
  p: Record<string, unknown>,
  previous?: Incident,
): Incident | null {
  if (typeof p.incident_id !== "string") return null;
  const junction = junctionById.get(
    String(p.intersection_id ?? previous?.affectedIntersection),
  );
  if (!junction && !previous) return null;
  const state = String(p.state ?? p.new_state ?? "CANDIDATE").toUpperCase();
  if (
    !["CANDIDATE", "CONFIRMED", "REJECTED", "EXPIRED", "CLEARED"].includes(
      state,
    )
  )
    return null;
  const rawTime =
    p.first_seen_ms ??
    p.detected_at ??
    p.candidate_detected_at ??
    previous?.detectedAt;
  const at =
    typeof rawTime === "number" ? rawTime : Date.parse(String(rawTime));
  const confidence =
    p.fused_probability == null
      ? previous?.confidence
      : Number(p.fused_probability);
  if (
    !Number.isFinite(at) ||
    confidence == null ||
    !Number.isFinite(confidence)
  )
    return null;
  return {
    id: p.incident_id,
    latitude: junction?.lat ?? previous!.latitude,
    longitude: junction?.lng ?? previous!.longitude,
    affectedIntersection: junction?.id ?? previous?.affectedIntersection,
    type:
      p.classification == null
        ? (previous?.type ?? "unknown")
        : (classificationType[String(p.classification)] ?? "unknown"),
    // The detector contract carries probability, not severity. Keep that distinction visible.
    severity: "low",
    severityKnown: false,
    confidence: Math.max(0, Math.min(1, confidence)),
    detectedAt: new Date(at).toISOString(),
    status:
      state === "CANDIDATE"
        ? "candidate"
        : state === "CONFIRMED"
          ? "confirmed"
          : "resolved",
    resolution: ["REJECTED", "EXPIRED", "CLEARED"].includes(state)
      ? state.toLowerCase()
      : undefined,
  };
}
export async function fetchIncidents(
  signal?: AbortSignal,
): Promise<Incident[]> {
  const res = await fetch(`${API_BASE}/v1/incidents`, { signal });
  if (!res.ok)
    throw new CommandError(res.status, "Could not load the incident registry.");
  const rows: unknown = await res.json();
  if (!Array.isArray(rows))
    throw new CommandError(502, "Unexpected incident registry response.");
  return rows
    .filter(
      (r): r is Record<string, unknown> => r !== null && typeof r === "object",
    )
    .map((r) => mapIncident(r))
    .filter((r): r is Incident => r !== null);
}
export async function reviewIncident(
  id: string,
  action: "confirm" | "reject",
  key: string,
  actor: string,
  classification: string,
  detail: string,
): Promise<Incident | null> {
  if (useSystemStore.getState().dataMode !== "live")
    throw new CommandError(
      409,
      "Demo incidents cannot be reviewed against the live backend.",
    );
  const res = await fetch(
    `${API_BASE}/v1/incidents/${encodeURIComponent(id)}/${action}`,
    {
      method: "POST",
      headers: { "content-type": "application/json", ...(key ? { "X-API-Key": key } : {}) },
      body: JSON.stringify({ actor, classification, detail }),
      signal: AbortSignal.timeout(10_000),
    },
  );
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new CommandError(
      res.status,
      body?.detail ?? `Review failed (${res.status}).`,
    );
  }
  return mapIncident((await res.json()) as Record<string, unknown>);
}
