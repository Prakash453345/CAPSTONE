import { ArrowUp, ArrowUpLeft, ArrowUpRight, CornerUpLeft, CornerUpRight, Flag, Navigation, TriangleAlert, Undo2 } from "lucide-react";
import { formatDistance, type Maneuver } from "@/drive/plan";
import { cn } from "@/utils/cn";

export function ManeuverIcon({ m, className }: { m: Maneuver; className?: string }) {
  const cls = cn("size-full", className);
  switch (m.kind) {
    case "depart":
      return <Navigation className={cls} />;
    case "arrive":
      return <Flag className={cls} />;
    case "uturn":
      return <Undo2 className={cls} />;
    case "bear":
      return m.side === "left" ? <ArrowUpLeft className={cls} /> : <ArrowUpRight className={cls} />;
    case "turn":
      return m.side === "left" ? <CornerUpLeft className={cls} /> : <CornerUpRight className={cls} />;
    default:
      return <ArrowUp className={cls} />;
  }
}

/** Within this distance the banner fills with colour: the turn is imminent. */
const IMMINENT_M = 150;

/**
 * The one thing a crew needs most: what to do next and how far away it is.
 * Large type and a high-contrast tile, readable at a glance in a moving cab.
 */
export function ManeuverBanner({
  next,
  distM,
  then,
  offRouteM,
  className,
}: {
  next: Maneuver;
  distM: number;
  then: Maneuver | null;
  offRouteM: number;
  className?: string;
}) {
  if (offRouteM > 60) {
    return (
      <div role="alert" className={cn("pointer-events-auto flex items-center gap-4 rounded-2xl bg-status-critical-muted p-4 text-status-critical shadow-elevation-3", className)}>
        <span className="grid size-14 shrink-0 place-items-center rounded-2xl bg-status-critical/15 p-3.5">
          <TriangleAlert className="size-full" />
        </span>
        <div className="min-w-0">
          <p className="text-lg font-semibold leading-tight">You are off the planned route</p>
          <p className="mt-0.5 text-sm">About {formatDistance(offRouteM)} away. Rejoin it, or ask dispatch for a new route.</p>
        </div>
      </div>
    );
  }

  const imminent = distM <= IMMINENT_M && next.kind !== "depart";
  return (
    <section aria-label="Next instruction" className={cn("pointer-events-auto overflow-hidden rounded-2xl bg-surface-raised shadow-elevation-3", className)}>
      <div className="flex items-center gap-4 p-4">
        <span
          aria-hidden
          className={cn(
            "grid size-16 shrink-0 place-items-center rounded-2xl p-3.5 transition-colors duration-300",
            imminent ? "bg-primary text-primary-foreground" : "bg-primary-muted text-primary",
          )}
        >
          <ManeuverIcon m={next} />
        </span>
        <div className="min-w-0">
          <p className="tabular text-4xl font-semibold leading-none tracking-[-0.02em]">{formatDistance(distM)}</p>
          <p className="mt-1.5 text-[17px] font-medium leading-snug">{next.text}</p>
        </div>
      </div>
      {then && then.kind !== "arrive" && (
        <p className="flex items-center gap-2 border-t border-border bg-muted/60 px-4 py-2 text-[13px] text-muted-foreground">
          <span className="size-4 shrink-0 text-foreground/70">
            <ManeuverIcon m={then} />
          </span>
          <span className="min-w-0 truncate">
            Then {then.text.charAt(0).toLowerCase() + then.text.slice(1)}
          </span>
        </p>
      )}
    </section>
  );
}
