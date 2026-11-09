import { useState } from "react";
import { Loader2, Siren } from "lucide-react";
import { Button, Panel } from "@/components/console/kit";
import { RoadField, type PickedRoad } from "@/components/map/RoadField";
import { CommandError, postCommand } from "@/services/traffic/commands";

/** Police crews ask an operator for a green corridor to a road. The
 *  route is planned and held until an operator approves it; nothing is
 *  preempted before that. */
export function CorridorAskCard({ className }: { className?: string }) {
  const [open, setOpen] = useState(false);
  const [road, setRoad] = useState<PickedRoad | null>(null);
  const [reason, setReason] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    if (!road) return;
    setState("busy");
    setError(null);
    try {
      await postCommand({
        event_type: "CrewCorridorRequest",
        payload: { unit_id: "", destination_edge: road.edgeId, reason: reason.trim(), requested_at: Date.now() },
      });
      setState("sent");
    } catch (err) {
      setError(err instanceof CommandError ? err.detail : "The request failed.");
      setState("idle");
    }
  };

  if (state === "sent") {
    return (
      <Panel className={className} aria-label="Green corridor request">
        <p role="status" className="px-5 py-4 text-[14px]">
          Asked for a green corridor. Your route appears here once an operator answers.
        </p>
      </Panel>
    );
  }

  return (
    <Panel className={className} aria-label="Green corridor request">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex w-full items-center gap-3 px-5 py-4 text-left text-[14px] font-medium transition-colors hover:bg-muted/60"
        >
          <Siren className="size-4 text-primary" aria-hidden />
          Request a green corridor
        </button>
      ) : (
        <div className="space-y-3 px-5 py-4">
          <p className="text-[13px] text-muted-foreground">An operator approves it before any signal is held green.</p>
          <RoadField value={road} picking={false} onPickOnMap={() => undefined} onChange={setRoad} placeholder="Where to?" hideMap />
          <input
            aria-label="Reason"
            value={reason}
            maxLength={120}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason (optional)"
            className="h-11 w-full rounded-[12px] bg-surface-fill px-3 text-[15px] outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring/60"
          />
          {error && (
            <p role="alert" className="text-[13px] text-status-critical">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <Button variant="primary" onClick={send} disabled={!road || state === "busy"}>
              {state === "busy" && <Loader2 className="animate-spin" />}
              Send request
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </Panel>
  );
}
