import { cn } from "@/utils/cn";

/**
 * Minimal CSS-only tooltip: wrap a trigger, pass `label`. Shown on hover and
 * keyboard focus of anything inside. Used by the collapsed nav rail.
 * (A full Radix tooltip can replace this later without touching call sites.)
 */
export function Tooltip({
  label,
  side = "right",
  className,
  children,
}: {
  label: string;
  side?: "right" | "top" | "bottom";
  className?: string;
  children: React.ReactNode;
}) {
  const pos =
    side === "right"
      ? "left-full top-1/2 -translate-y-1/2 ml-2"
      : side === "top"
        ? "bottom-full left-1/2 -translate-x-1/2 mb-2"
        : "top-full left-1/2 -translate-x-1/2 mt-2";

  return (
    <span className={cn("group/tt relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute z-50 whitespace-nowrap rounded-md border border-border bg-surface-raised px-2 py-1 text-xs text-foreground opacity-0 shadow-panel transition-opacity duration-150",
          "group-hover/tt:opacity-100 group-focus-within/tt:opacity-100",
          pos,
        )}
      >
        {label}
      </span>
    </span>
  );
}
