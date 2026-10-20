import { BellRing, BellOff } from "lucide-react";
import { useAlertPermission } from "@/crew/useCallAlerts";

/**
 * Asks once for permission to show call alerts. Browsers only ask after a tap,
 * and only on HTTPS, so this says plainly when they cannot be turned on.
 * Hidden once alerts are on.
 */
export function AlertsPrompt() {
  const { state, ask } = useAlertPermission();
  if (state === "granted" || state === "unsupported") return null;

  if (state === "default") {
    return (
      <section className="pointer-events-auto flex items-center gap-3 rounded-[22px] bg-surface-raised p-4 shadow-elevation-1">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-primary-muted text-primary">
          <BellRing className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-semibold leading-tight">Turn on call alerts</p>
          <p className="text-[13px] text-muted-foreground">Get a notification and a sound when dispatch sends you a call.</p>
        </div>
        <button
          type="button"
          onClick={() => void ask()}
          className="h-10 shrink-0 rounded-full bg-primary px-4 text-[14px] font-semibold text-primary-foreground hover:brightness-105"
        >
          Turn on
        </button>
      </section>
    );
  }

  return (
    <section className="pointer-events-auto flex items-start gap-3 rounded-[22px] bg-surface-raised p-4 shadow-elevation-1">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
        <BellOff className="size-5" />
      </span>
      <p className="text-[13px] leading-snug text-muted-foreground">
        {state === "insecure"
          ? "Call alerts need the secure (https://) address of this site. Calls still appear here."
          : "Call alerts are blocked for this site. Allow notifications in the browser's site settings to get them."}
      </p>
    </section>
  );
}
