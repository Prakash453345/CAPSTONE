import { cn } from "@/utils/cn";

/**
 * Compact telemetry module (spec §6: "not oversized colorful cards").
 * A label, a big tabular value, an optional unit and an optional delta/hint.
 */
export function StatTile({
  label,
  value,
  unit,
  hint,
  tone = "default",
  className,
}: {
  label: string;
  value: string | number;
  unit?: string;
  hint?: string;
  tone?: "default" | "ok" | "warn" | "critical" | "info";
  className?: string;
}) {
  const toneText =
    tone === "ok"
      ? "text-status-ok"
      : tone === "warn"
        ? "text-status-warn"
        : tone === "critical"
          ? "text-status-critical"
          : tone === "info"
            ? "text-status-info"
            : "text-foreground";

  return (
    <div
      className={cn(
        "flex min-w-0 flex-col justify-between rounded-lg border border-border bg-surface px-3 py-2.5",
        className,
      )}
    >
      <span className="truncate font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </span>
      <div className="mt-1 flex items-baseline gap-1">
        <span className={cn("tabular text-xl font-semibold leading-none", toneText)}>
          {value}
        </span>
        {unit && (
          <span className="text-xs text-muted-foreground">{unit}</span>
        )}
      </div>
      {hint && (
        <span className="mt-1 truncate text-[11px] text-muted-foreground">
          {hint}
        </span>
      )}
    </div>
  );
}
