import { useNavigate } from "react-router-dom";
import { AlertTriangle, Ambulance, ScanEye, Siren } from "lucide-react";
import { useMapStore } from "@/store/mapStore";
import { PRESET_UNITS, selectActiveRequests, useEmergencyStore } from "@/store/emergencyStore";
import { useIncidentStore } from "@/store/incidentStore";
import { cn } from "@/utils/cn";

/**
 * Command Center action bar (Phase 9): the operator actions that used to be
 * discoverable only as small overlay buttons on the map (Create Anomaly,
 * Emergency Response) or by navigating blind (View Active Incidents, Active
 * Emergency). Create Anomaly / Emergency Response drive the exact same
 * `mapStore`/`emergencyStore` state the map's own overlay buttons already
 * do — this is a second, more visible front door onto that flow, not a
 * parallel implementation of it.
 */
export function CommandActionBar() {
  const navigate = useNavigate();
  const interactionMode = useMapStore((s) => s.interactionMode);
  const setInteractionMode = useMapStore((s) => s.setInteractionMode);
  const draft = useEmergencyStore((s) => s.draft);
  const startDraft = useEmergencyStore((s) => s.startDraft);
  const clearDraft = useEmergencyStore((s) => s.clearDraft);
  const selectRequest = useEmergencyStore((s) => s.selectRequest);
  const activeRequests = useEmergencyStore(selectActiveRequests);
  const activeAnomalies = useIncidentStore(
    (s) => s.anomalies.filter((a) => a.status === "active").length,
  );

  const creatingAnomaly = interactionMode === "create-anomaly";

  const toggleCreateAnomaly = () =>
    setInteractionMode(creatingAnomaly ? "idle" : "create-anomaly");

  const toggleEmergencyDraft = () => (draft ? clearDraft() : startDraft(PRESET_UNITS[0]));

  const openActiveEmergency = () => {
    if (activeRequests.length === 1) selectRequest(activeRequests[0].id);
    navigate("/emergency");
  };

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface/40 px-4 py-2.5">
      <span className="mr-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        Actions
      </span>
      <ActionButton
        icon={AlertTriangle}
        label={creatingAnomaly ? "Cancel" : "Create anomaly"}
        active={creatingAnomaly}
        onClick={toggleCreateAnomaly}
      />
      <ActionButton
        icon={Ambulance}
        label={draft ? "Cancel dispatch" : "Emergency response"}
        active={draft != null}
        onClick={toggleEmergencyDraft}
      />
      <ActionButton
        icon={ScanEye}
        label="View active incidents"
        count={activeAnomalies}
        onClick={() => navigate("/anomalies")}
      />
      <ActionButton
        icon={Siren}
        label="Active emergency"
        count={activeRequests.length}
        countTone={activeRequests.length > 0 ? "critical" : undefined}
        onClick={openActiveEmergency}
      />
    </div>
  );
}

function ActionButton({
  icon: Icon,
  label,
  onClick,
  active,
  count,
  countTone,
}: {
  icon: typeof AlertTriangle;
  label: string;
  onClick: () => void;
  active?: boolean;
  count?: number;
  countTone?: "critical";
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
        active
          ? "border-primary/70 bg-primary/15 text-foreground"
          : "border-border bg-surface text-muted-foreground hover:border-primary/40 hover:text-foreground",
      )}
    >
      <Icon className="size-3.5" />
      {label}
      {count != null && count > 0 && (
        <span
          className={cn(
            "grid h-4 min-w-4 place-items-center rounded-full px-1 font-mono text-[10px] font-semibold leading-none",
            countTone === "critical"
              ? "bg-status-critical text-white"
              : "bg-primary-muted text-primary",
          )}
        >
          {count}
        </span>
      )}
    </button>
  );
}
