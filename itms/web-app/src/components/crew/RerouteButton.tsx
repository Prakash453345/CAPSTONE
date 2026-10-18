import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { CommandError, postCommand } from "@/services/traffic/commands";
import { useSystemStore } from "@/store/systemStore";
import { cn } from "@/utils/cn";

/** Asks the system to recalculate the route (the same command dispatchers use). */
export function RerouteButton({ requestId, unitName, className }: { requestId: string; unitName: string; className?: string }) {
  const live = useSystemStore((s) => s.dataMode === "live");
  const [state, setState] = useState<"idle" | "busy" | "sent" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setState("busy");
    setError(null);
    try {
      await postCommand({
        event_type: "EmergencyCommand",
        payload: { request_id: requestId, action: "RECALCULATE", reason: `Crew request (${unitName})`, requested_at: Date.now() },
      });
      setState("sent");
      window.setTimeout(() => setState("idle"), 4000);
    } catch (err) {
      setError(err instanceof CommandError ? err.detail : "The request failed.");
      setState("error");
    }
  };

  return (
    <div className={cn("relative", className)}>
      <button
        type="button"
        disabled={!live || state === "busy"}
        onClick={send}
        title={live ? "Ask for a new route" : "New routes can only be requested in Live mode"}
        className="inline-flex h-11 items-center gap-2 rounded-xl bg-surface-raised px-3.5 text-[14px] font-medium shadow-elevation-1 transition-colors hover:bg-muted active:scale-95 disabled:pointer-events-none disabled:opacity-50"
      >
        <RefreshCw className={cn("size-[18px]", state === "busy" && "animate-spin")} aria-hidden />
        {state === "sent" ? "Requested" : state === "busy" ? "Requesting…" : "New route"}
      </button>
      {state === "error" && error && (
        <p role="alert" className="absolute bottom-full right-0 mb-2 w-60 rounded-lg bg-status-critical-muted px-3 py-2 text-[12px] text-status-critical shadow-elevation-2">
          {error}
        </p>
      )}
    </div>
  );
}
