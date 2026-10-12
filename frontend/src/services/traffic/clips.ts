/**
 * Uploaded road videos: the console side of clip-based incident detection.
 *
 * An operator uploads a video for a road; the vision service analyses it and
 * whatever it finds waits for a person to confirm or reject (api-service
 * `/v1/clips`). Confirming creates the same anomaly the Create Anomaly panel
 * does, so the live response chain takes over from there.
 */
import { CommandError } from "@/services/traffic/commands";
import { useSystemStore } from "@/store/systemStore";
import type { AnomalyKind } from "@/types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export type ClipStatus = "QUEUED" | "ANALYSING" | "DONE" | "FAILED";
export type ClipReview = "PENDING" | "CONFIRMED" | "REJECTED" | null;
export type ClipSeverity = "low" | "medium" | "high" | "blocked";

export interface ClipFinding {
  anomalyType: AnomalyKind;
  detector: string;
  severity: ClipSeverity;
  confidence: number;
  startS: number;
  endS: number;
  reasons: string[];
}

export interface Clip {
  id: string;
  filename: string;
  edgeId: string;
  roadName: string;
  submittedMs: number;
  status: ClipStatus;
  progress: number;
  videoUrl: string;
  snapshotUrl: string | null;
  anomalyType: AnomalyKind | null;
  severity: ClipSeverity | null;
  confidence: number | null;
  flaggedAtS: number | null;
  reasons: string[];
  findings: ClipFinding[];
  timeline: Record<string, (number | null)[]>;
  detectors: string[];
  durationS: number | null;
  error: string;
  review: ClipReview;
  reviewedBy: string;
  reviewNote: string;
  anomalyId: string | null;
  confirmedType: AnomalyKind | null;
  confirmedSeverity: ClipSeverity | null;
}

/** The types a reviewer may confirm a finding as (api-service OPERATOR_TYPE). */
export const CONFIRMABLE_TYPES: AnomalyKind[] = [
  "accident",
  "fire",
  "vehicle_breakdown",
  "lane_blockage",
  "road_obstruction",
  "heavy_congestion",
];
export const SEVERITIES: ClipSeverity[] = ["low", "medium", "high", "blocked"];

const url = (path: string) => `${API_BASE}${path}`;
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string => (typeof v === "string" ? v : "");

export function mapClip(p: Record<string, unknown>): Clip | null {
  if (typeof p.clip_id !== "string") return null;
  const findings = Array.isArray(p.findings) ? (p.findings as Record<string, unknown>[]) : [];
  return {
    id: p.clip_id,
    filename: str(p.filename),
    edgeId: str(p.edge_id),
    roadName: str(p.road_name),
    submittedMs: num(p.submitted_ms) ?? 0,
    status: (str(p.status) || "QUEUED") as ClipStatus,
    progress: num(p.progress) ?? 0,
    videoUrl: url(str(p.video_url)),
    snapshotUrl: typeof p.snapshot_url === "string" ? url(p.snapshot_url) : null,
    anomalyType: (p.anomaly_type as AnomalyKind) ?? null,
    severity: (p.severity as ClipSeverity) ?? null,
    confidence: num(p.confidence),
    flaggedAtS: num(p.flagged_at_s),
    reasons: Array.isArray(p.reasons) ? p.reasons.map(String) : [],
    findings: findings.map((f) => ({
      anomalyType: f.anomaly_type as AnomalyKind,
      detector: str(f.detector),
      severity: f.severity as ClipSeverity,
      confidence: num(f.confidence) ?? 0,
      startS: num(f.start_s) ?? 0,
      endS: num(f.end_s) ?? 0,
      reasons: Array.isArray(f.reasons) ? f.reasons.map(String) : [],
    })),
    timeline:
      p.timeline && typeof p.timeline === "object"
        ? (p.timeline as Record<string, (number | null)[]>)
        : {},
    detectors: Array.isArray(p.detectors) ? p.detectors.map(String) : [],
    durationS: num(p.duration_s),
    error: str(p.error),
    review: (p.review as ClipReview) ?? null,
    reviewedBy: str(p.reviewed_by),
    reviewNote: str(p.review_note),
    anomalyId: typeof p.anomaly_id === "string" ? p.anomaly_id : null,
    confirmedType: (p.confirmed_type as AnomalyKind) ?? null,
    confirmedSeverity: (p.confirmed_severity as ClipSeverity) ?? null,
  };
}

function requireLive() {
  if (useSystemStore.getState().dataMode !== "live")
    throw new CommandError(409, "Video analysis runs on the live backend. Switch to Live first.");
}

async function errorDetail(res: Response): Promise<string> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
  return typeof body?.detail === "string" ? body.detail : `${res.status} ${res.statusText}`;
}

export async function fetchClips(signal?: AbortSignal): Promise<Clip[]> {
  const res = await fetch(url("/v1/clips"), { signal });
  if (!res.ok) throw new CommandError(res.status, "Could not load uploaded videos.");
  const rows: unknown = await res.json();
  if (!Array.isArray(rows)) throw new CommandError(502, "Unexpected response for uploaded videos.");
  return rows
    .filter((r): r is Record<string, unknown> => r !== null && typeof r === "object")
    .map(mapClip)
    .filter((c): c is Clip => c !== null);
}

export interface UploadTarget {
  edgeId: string;
  roadName: string;
  at: [number, number];
}

/** XMLHttpRequest rather than fetch: fetch cannot report upload progress, and
 *  a road video can take a while to send. */
export function uploadClip(
  file: File,
  target: UploadTarget,
  onProgress: (fraction: number) => void,
): { done: Promise<Clip>; cancel: () => void } {
  requireLive();
  const form = new FormData();
  form.append("file", file);
  form.append("edge_id", target.edgeId);
  form.append("road_name", target.roadName);
  form.append("longitude", String(target.at[0]));
  form.append("latitude", String(target.at[1]));
  const xhr = new XMLHttpRequest();
  const done = new Promise<Clip>((resolve, reject) => {
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: Record<string, unknown> | null = null;
      try {
        body = JSON.parse(xhr.responseText) as Record<string, unknown>;
      } catch {
        /* non-JSON body: handled below */
      }
      if (xhr.status >= 200 && xhr.status < 300 && body) {
        const clip = mapClip(body);
        if (clip) return resolve(clip);
      }
      const detail = typeof body?.detail === "string" ? body.detail : `Upload failed (${xhr.status}).`;
      reject(new CommandError(xhr.status, detail));
    };
    xhr.onerror = () => reject(new CommandError(0, "Could not reach the backend to upload the video."));
    xhr.onabort = () => reject(new CommandError(499, "Upload cancelled."));
  });
  xhr.open("POST", url("/v1/clips"));
  xhr.send(form);
  return { done, cancel: () => xhr.abort() };
}

export async function reviewClip(
  id: string,
  action: "confirm" | "reject",
  key: string,
  body: { actor: string; note?: string; anomalyType?: AnomalyKind; severity?: ClipSeverity },
): Promise<Clip> {
  requireLive();
  const res = await fetch(url(`/v1/clips/${encodeURIComponent(id)}/${action}`), {
    method: "POST",
    headers: { "content-type": "application/json", "X-API-Key": key },
    body: JSON.stringify({
      actor: body.actor,
      note: body.note ?? "",
      ...(action === "confirm" ? { anomaly_type: body.anomalyType, severity: body.severity } : {}),
    }),
    signal: AbortSignal.timeout(10_000),
  });
  if (!res.ok) throw new CommandError(res.status, await errorDetail(res));
  const clip = mapClip((await res.json()) as Record<string, unknown>);
  if (!clip) throw new CommandError(502, "Unexpected review response.");
  return clip;
}
