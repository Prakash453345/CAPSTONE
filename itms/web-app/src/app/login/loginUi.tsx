import { cn } from "@/utils/cn";

import type { Lamp } from "@/app/login/loginConsts";

/** A signal head that mirrors the form: amber while you type (steady) or
 *  while we check (pulsing), green once you're cleared, red when you're turned
 *  away. Decorative, so hidden from assistive tech; the text status below it
 *  is what screen readers get. */
export function Signal({ state }: { state: Lamp }) {
  const lamps = [
    { id: "r", on: state === "error", color: "bg-status-critical shadow-[0_0_14px_3px_hsl(var(--status-critical))]" },
    { id: "a", on: state === "typing" || state === "busy", color: "bg-status-warn shadow-[0_0_14px_3px_hsl(var(--status-warn))]" },
    { id: "g", on: state === "granted", color: "bg-status-ok shadow-[0_0_14px_3px_hsl(var(--status-ok))]" },
  ];
  return (
    <span aria-hidden className="flex items-center gap-2 rounded-full bg-muted px-3 py-2">
      {lamps.map((l) => (
        <i
          key={l.id}
          className={cn(
            "block size-3.5 rounded-full transition-[background-color,box-shadow,transform] duration-300",
            l.on ? cn(l.color, "scale-110", l.id === "a" && state === "busy" && "animate-pulse") : "bg-foreground/15",
          )}
        />
      ))}
    </span>
  );
}
