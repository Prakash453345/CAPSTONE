import { useState } from "react";
import { AlertTriangle, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SimModeNotice } from "@/components/map/SimModeNotice";
import { cn } from "@/utils/cn";
import { CommandError, postCommand } from "@/services/traffic/commands";
import type { AnomalyKind, AnomalySeverity } from "@/types";

/** What the map click resolved to. */
export interface AnomalyTarget {
  edgeId: string;
  edgeName: string | null;
  /** [lng, lat] snapped onto the edge. */
  at: [number, number];
}

const TYPES: { id: AnomalyKind; label: string; event: string }[] = [
  { id: "accident", label: "Accident", event: "ACCIDENT" },
  { id: "vehicle_breakdown", label: "Breakdown", event: "VEHICLE_BREAKDOWN" },
  { id: "lane_blockage", label: "Lane blockage", event: "LANE_BLOCKAGE" },
  { id: "road_obstruction", label: "Obstruction", event: "ROAD_OBSTRUCTION" },
  { id: "heavy_congestion", label: "Heavy congestion", event: "HEAVY_CONGESTION" },
];

const SEVERITIES: { id: AnomalySeverity; label: string; event: string; hint: string }[] = [
  { id: "low", label: "Low", event: "LOW", hint: "minor slow-down" },
  { id: "medium", label: "Medium", event: "MEDIUM", hint: "significant delay" },
  { id: "high", label: "High", event: "HIGH", hint: "severe restriction" },
  { id: "blocked", label: "Blocked", event: "BLOCKED", hint: "road impassable" },
];

export function CreateAnomalyPanel({
  target,
  onClose,
  onCreated,
}: {
  target: AnomalyTarget;
  onClose: () => void;
  onCreated: (anomalyId: string) => void;
}) {
  const [type, setType] = useState<AnomalyKind>("lane_blockage");
  const [severity, setSeverity] = useState<AnomalySeverity>("high");
  const [durationMin, setDurationMin] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const anomalyId = crypto.randomUUID();
    const durationS = durationMin.trim() ? Math.max(1, Number(durationMin) * 60) : null;
    try {
      await postCommand({
        event_type: "AnomalyCreateRequested",
        payload: {
          anomaly_id: anomalyId,
          edge_id: target.edgeId,
          lane_id: null,
          anomaly_type: TYPES.find((t) => t.id === type)!.event,
          severity: SEVERITIES.find((s) => s.id === severity)!.event,
          duration_s: durationS,
          position_m: null,
          requested_at: Date.now(),
        },
      });
      onCreated(anomalyId);
    } catch (err) {
      setError(
        err instanceof CommandError
          ? err.status === 0
            ? "Backend unreachable — is the live simulation running?"
            : err.detail
          : "Could not create the anomaly.",
      );
      setBusy(false);
    }
  };

  return (
    <div className="pointer-events-auto w-[300px] max-w-full origin-top-left animate-sheet-in overflow-hidden rounded-xl bg-surface-raised shadow-elevation-3">
      <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
        <div className="flex items-center gap-2">
          <AlertTriangle className="size-4 text-[color:var(--severity-high,#e5622a)]" />
          <span className="text-sm font-semibold">Create anomaly</span>
        </div>
        <button
          type="button"
          aria-label="Cancel"
          onClick={onClose}
          className="grid size-6 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground [&_svg]:size-3.5"
        >
          <X />
        </button>
      </div>

      <div className="space-y-3 p-3">
        <SimModeNotice />

        <div>
          <FieldLabel>Location</FieldLabel>
          <div className="rounded-md border border-border bg-surface px-2.5 py-1.5 font-mono text-xs text-foreground">
            {target.edgeName ?? "Edge"} <span className="text-muted-foreground">·</span>{" "}
            {target.edgeId}
          </div>
        </div>

        <div>
          <FieldLabel>Type</FieldLabel>
          <div className="grid grid-cols-2 gap-1">
            {TYPES.map((t) => (
              <Chip key={t.id} active={type === t.id} onClick={() => setType(t.id)}>
                {t.label}
              </Chip>
            ))}
          </div>
        </div>

        <div>
          <FieldLabel>Severity</FieldLabel>
          <div className="grid grid-cols-4 gap-1">
            {SEVERITIES.map((s) => (
              <Chip
                key={s.id}
                active={severity === s.id}
                onClick={() => setSeverity(s.id)}
                title={s.hint}
              >
                {s.label}
              </Chip>
            ))}
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {SEVERITIES.find((s) => s.id === severity)!.hint}
          </p>
        </div>

        <div>
          <FieldLabel>Duration (minutes, optional)</FieldLabel>
          <input
            type="number"
            min={1}
            inputMode="numeric"
            placeholder="until cleared"
            value={durationMin}
            onChange={(e) => setDurationMin(e.target.value)}
            className="w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-foreground outline-none focus:border-primary/60"
          />
        </div>

        {error && (
          <p className="rounded-md bg-[color-mix(in_srgb,#e5484d_14%,transparent)] px-2.5 py-1.5 text-[11px] text-[#f0a6a6]">
            {error}
          </p>
        )}

        <Button className="w-full" onClick={submit} disabled={busy}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : null}
          {busy ? "Creating…" : "Create anomaly"}
        </Button>
      </div>
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
      {children}
    </div>
  );
}

function Chip({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean;
  onClick: () => void;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={cn(
        "rounded-md border px-2 py-1.5 text-xs transition-colors",
        active
          ? "border-primary/70 bg-primary/15 text-foreground"
          : "border-border bg-surface text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
