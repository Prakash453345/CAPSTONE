import type { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
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

/** Eases a message in and out instead of snapping, so the fields under it
 *  slide rather than jump. `gap` is for a child of a `gap-4` column (the
 *  negative margin cancels the flex gap while it is collapsed); `below` is for
 *  a block that sits above a form with a 1rem margin of its own. */
export function Collapse({
  show,
  kind = "gap",
  children,
}: {
  show: boolean;
  kind?: "gap" | "below";
  children: ReactNode;
}) {
  const closed =
    kind === "gap" ? { height: 0, opacity: 0, marginTop: -16 } : { height: 0, opacity: 0, marginBottom: 0 };
  const open =
    kind === "gap" ? { height: "auto", opacity: 1, marginTop: 0 } : { height: "auto", opacity: 1, marginBottom: 16 };
  return (
    <AnimatePresence initial={false}>
      {show && (
        <motion.div
          initial={closed}
          animate={open}
          exit={closed}
          transition={{ duration: 0.2, ease: "easeOut" }}
          style={{ overflow: "hidden" }}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
