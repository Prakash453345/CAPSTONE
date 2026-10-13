import { Radio } from "lucide-react";
import { useSystemStore } from "@/store/systemStore";

/**
 * Shown inside the Create Anomaly / Emergency Response panels while the
 * operator is in Simulation mode. Both actions always post to the real
 * backend regardless of data mode (`services/traffic/commands.ts`'s own
 * doc comment: "commands always go to the real backend regardless of which
 * data mode the map is showing") — but Simulation mode's provider has no
 * live event stream and shows its own local mock data, so a
 * successfully-created anomaly or dispatch has nothing to appear *in*.
 * Without this, the operator gets no error and no result — indistinguishable
 * from the feature being broken. Naming the mismatch here, at the one moment
 * it matters, is cheaper and more honest than trying to fake the result in
 * Simulation mode.
 */
export function SimModeNotice() {
  const dataMode = useSystemStore((s) => s.dataMode);
  const setDataMode = useSystemStore((s) => s.setDataMode);
  if (dataMode !== "simulation") return null;

  return (
    <div className="flex items-start gap-2 rounded-md border border-status-warn/30 bg-status-warn-muted px-2.5 py-2 text-[11px]">
      <Radio className="mt-0.5 size-3.5 shrink-0 text-status-warn" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-status-warn">You're in Simulation mode</p>
        <p className="mt-0.5 text-muted-foreground">
          This will still reach the live backend, but Simulation mode shows its
          own local traffic — you won't see the result here until you switch to
          Live.
        </p>
        <button
          type="button"
          onClick={() => setDataMode("live")}
          className="mt-1.5 rounded-md border border-status-warn/40 px-2 py-1 font-medium text-status-warn transition-colors hover:bg-status-warn/10"
        >
          Switch to Live
        </button>
      </div>
    </div>
  );
}
