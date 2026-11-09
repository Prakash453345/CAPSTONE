import { useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { CommandError, postCommand } from "@/services/traffic/commands";
import { edgeById, roadLabel } from "@/data/network";
import { InlineError, Pill, PrimaryButton, SectionLabel, Sheet } from "@/components/map/sheet";
import type { AnomalyKind, AnomalySeverity } from "@/types";

/** What the map click resolved to. */
export interface AnomalyTarget {
  edgeId: string;
  edgeName: string | null;
  /** [lng, lat] snapped onto the edge. */
  at: [number, number];
}

/** What each type brings out, so the operator knows before pressing create
 *  (sim-service `incident_response._RESPONSE_MAP`). */
const TYPES: { id: AnomalyKind; label: string; event: string; sends: string }[] = [
  { id: "accident", label: "Accident", event: "ACCIDENT", sends: "Police, ambulance and fire" },
  { id: "fire", label: "Fire", event: "FIRE", sends: "Fire and police" },
  { id: "vehicle_breakdown", label: "Breakdown", event: "VEHICLE_BREAKDOWN", sends: "Police" },
  { id: "lane_blockage", label: "Lane blocked", event: "LANE_BLOCKAGE", sends: "Police" },
  { id: "road_obstruction", label: "Obstruction", event: "ROAD_OBSTRUCTION", sends: "Police" },
  { id: "heavy_congestion", label: "Congestion", event: "HEAVY_CONGESTION", sends: "No responders" },
];

const SEVERITIES: { id: AnomalySeverity; label: string; event: string; hint: string }[] = [
  { id: "low", label: "Low", event: "LOW", hint: "Minor slow-down" },
  { id: "medium", label: "Medium", event: "MEDIUM", hint: "Significant delay" },
  { id: "high", label: "High", event: "HIGH", hint: "Severe restriction" },
  { id: "blocked", label: "Blocked", event: "BLOCKED", hint: "Road closed; traffic is routed around it" },
];

const DURATIONS: { label: string; min: number | null }[] = [
  { label: "Until cleared", min: null },
  { label: "15 min", min: 15 },
  { label: "30 min", min: 30 },
  { label: "1 h", min: 60 },
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
  const [type, setType] = useState<AnomalyKind>("accident");
  const [severity, setSeverity] = useState<AnomalySeverity>("high");
  const [durationMin, setDurationMin] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const edge = edgeById.get(target.edgeId);
  const chosenType = TYPES.find((t) => t.id === type)!;

  const submit = async () => {
    setBusy(true);
    setError(null);
    const anomalyId = crypto.randomUUID();
    try {
      await postCommand({
        event_type: "AnomalyCreateRequested",
        payload: {
          anomaly_id: anomalyId,
          edge_id: target.edgeId,
          lane_id: null,
          anomaly_type: chosenType.event,
          severity: SEVERITIES.find((s) => s.id === severity)!.event,
          duration_s: durationMin == null ? null : durationMin * 60,
          position_m: null,
          requested_at: Date.now(),
        },
      });
      onCreated(anomalyId);
    } catch (err) {
      setError(
        err instanceof CommandError
          ? err.status === 0
            ? "Can't reach the server. Is the live simulation running?"
            : err.detail
          : "Could not report it.",
      );
      setBusy(false);
    }
  };

  return (
    <Sheet
      title="Report a disruption"
      subtitle={`${roadLabel(target.edgeId)}${edge ? ` · ${edge.numLanes} lane${edge.numLanes === 1 ? "" : "s"}` : ""}`}
      icon={<AlertTriangle />}
      onClose={onClose}
      closeLabel="Cancel"
      footer={
        <PrimaryButton onClick={submit} disabled={busy}>
          {busy && <Loader2 className="animate-spin" />}
          {busy ? "Reporting…" : `Report ${chosenType.label.toLowerCase()}`}
        </PrimaryButton>
      }
    >
      <div>
        <SectionLabel>What happened</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          {TYPES.map((t) => (
            <Pill key={t.id} active={type === t.id} onClick={() => setType(t.id)}>
              {t.label}
            </Pill>
          ))}
        </div>
        <p className="mt-2 px-1 text-[12px] text-muted-foreground">
          Sends: <span className="font-medium text-foreground">{chosenType.sends}</span>
        </p>
      </div>

      <div>
        <SectionLabel>How bad</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          {SEVERITIES.map((s) => (
            <Pill key={s.id} active={severity === s.id} onClick={() => setSeverity(s.id)} title={s.hint}>
              {s.label}
            </Pill>
          ))}
        </div>
        <p className="mt-2 px-1 text-[12px] text-muted-foreground">{SEVERITIES.find((s) => s.id === severity)!.hint}</p>
      </div>

      <div>
        <SectionLabel>For how long</SectionLabel>
        <div className="flex flex-wrap gap-1.5">
          {DURATIONS.map((d) => (
            <Pill key={d.label} active={durationMin === d.min} onClick={() => setDurationMin(d.min)}>
              {d.label}
            </Pill>
          ))}
        </div>
      </div>

      {error && <InlineError>{error}</InlineError>}
    </Sheet>
  );
}
