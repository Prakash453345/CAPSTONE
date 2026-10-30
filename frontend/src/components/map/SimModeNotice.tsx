import { Radio } from "lucide-react";
import { useSystemStore } from "@/store/systemStore";

/**
 * Shown inside the Create Anomaly / Emergency Response panels while the
 * console shows Demo data. Demo is read-only: `postCommand` refuses every
 * operator command until the data source is Live (services/traffic/
 * commands.ts), because the browser demo has nothing to send it to. Saying
 * so before the operator fills in the form, not only after they submit it,
 * keeps the refusal from looking like a broken button.
 */
export function SimModeNotice() {
  const dataMode = useSystemStore((s) => s.dataMode);
  const setDataMode = useSystemStore((s) => s.setDataMode);
  if (dataMode !== "simulation") return null;

  return (
    <div className="flex items-start gap-2 rounded-md border border-status-warn/30 bg-status-warn-muted px-2.5 py-2 text-[11px]">
      <Radio className="mt-0.5 size-3.5 shrink-0 text-status-warn" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-status-warn">You&rsquo;re viewing the demo</p>
        <p className="mt-0.5 text-muted-foreground">
          Reports and dispatches go to the live city simulation, so they can&rsquo;t
          be sent from the demo. Switch to Live to send this one.
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
