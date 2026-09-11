import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";

/**
 * Standard "not built yet" state for a workspace. Deliberately not blank
 * (spec §2 / §15): it names the screen, explains what will live here, and
 * states which build phase delivers it.
 */
export function WorkspacePlaceholder({
  title,
  blurb,
  icon: Icon,
  phase,
}: {
  title: string;
  blurb: string;
  icon: LucideIcon;
  phase: string;
}) {
  return (
    <div className="grid h-full place-items-center p-6">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25, ease: "easeOut" }}
        className="max-w-md text-center"
      >
        <div className="mx-auto mb-4 grid size-12 place-items-center rounded-xl border border-border bg-surface-raised">
          <Icon className="size-6 text-muted-foreground" />
        </div>
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        <p className="mx-auto mt-1.5 text-sm text-muted-foreground">{blurb}</p>
        <div className="mt-4 flex justify-center">
          <Badge tone="primary">{phase}</Badge>
        </div>
      </motion.div>
    </div>
  );
}
