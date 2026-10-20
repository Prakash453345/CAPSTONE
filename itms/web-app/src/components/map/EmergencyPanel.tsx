import { Suspense, lazy } from "react";
import { Ambulance } from "lucide-react";
import { cn } from "@/utils/cn";
import { MAP_CHIP, MAP_CHIP_ACTIVE } from "@/components/map/mapChrome";
import { PRESET_UNITS, selectSelectedRequest, useEmergencyStore } from "@/store/emergencyStore";

const EmergencySheets = lazy(() => import("@/components/map/EmergencySheets"));

/**
 * Emergency response on the console map. The operator says what is needed
 * (an ambulance, police, fire) and where; the system offers the call to the
 * nearest crew of that kind that is free, by live travel time, and the crew
 * drives from wherever it is. There is no "from": a unit is never sent from
 * a point the operator picks.
 *
 * Three sheets, one at a time: the request being drafted, the call while a
 * crew is being found, then the live mission once a crew has accepted.
 * `part="chip"` is the entry point in the map's search row.
 */
export function EmergencyPanel({ part }: { part: "chip" | "panel" }) {
  const draft = useEmergencyStore((s) => s.draft);
  const startDraft = useEmergencyStore((s) => s.startDraft);
  const selected = useEmergencyStore(selectSelectedRequest);
  const pendingCall = useEmergencyStore((s) => s.pendingCall);
  const busy = Boolean(draft || selected || pendingCall);

  if (part === "panel") {
    if (!busy) return null;
    return (
      <Suspense fallback={null}>
        <EmergencySheets />
      </Suspense>
    );
  }

  return (
    <button
      type="button"
      onClick={() => startDraft(PRESET_UNITS[0])}
      aria-pressed={busy}
      className={cn(MAP_CHIP, busy && MAP_CHIP_ACTIVE)}
    >
      <Ambulance />
      Emergency response
    </button>
  );
}

