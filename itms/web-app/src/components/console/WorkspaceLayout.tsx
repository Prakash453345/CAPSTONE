import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { EASE_OUT } from "@/components/console/motion";

/**
 * The operational pages' shape: one side panel and the live map, both as
 * floating surfaces with the same gutter, so every workspace feels like the
 * same instrument set up for a different job.
 */
export function WorkspaceLayout({
  label,
  panel,
  map,
  panelWidth = 380,
}: {
  label: string;
  panel: ReactNode;
  map: ReactNode;
  panelWidth?: number;
}) {
  return (
    <div
      className="operational-workspace grid h-full grid-cols-1 gap-4 px-4 pb-4 sm:px-6 sm:pb-6 lg:grid-cols-[var(--panel-w)_minmax(0,1fr)]"
      style={{ ["--panel-w" as string]: `${panelWidth}px` }}
    >
      <motion.aside
        aria-label={label}
        initial={{ opacity: 0, x: -12 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.45, ease: EASE_OUT }}
        className="flex min-h-[320px] flex-col overflow-hidden rounded-2xl bg-surface shadow-elevation-1 lg:min-h-0"
      >
        {panel}
      </motion.aside>
      <motion.section
        aria-label="Live map"
        initial={{ opacity: 0, scale: 0.99 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5, ease: EASE_OUT }}
        className="relative min-h-[460px] overflow-hidden rounded-2xl bg-surface shadow-elevation-1 lg:h-full"
      >
        {map}
      </motion.section>
    </div>
  );
}
