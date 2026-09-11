import { cn } from "@/utils/cn";

type Tone = "ok" | "warn" | "critical" | "info" | "neutral";

const toneClass: Record<Tone, string> = {
  ok: "bg-status-ok",
  warn: "bg-status-warn",
  critical: "bg-status-critical",
  info: "bg-status-info",
  neutral: "bg-muted-foreground",
};

/** A small state indicator; optionally emits a slow expanding ring while `pulse`. */
export function StatusDot({
  tone = "neutral",
  pulse = false,
  className,
}: {
  tone?: Tone;
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("relative inline-flex h-2 w-2", className)}>
      {pulse && (
        <span
          className={cn(
            "absolute inset-0 rounded-full opacity-60 animate-ping-ring",
            toneClass[tone],
          )}
        />
      )}
      <span className={cn("relative inline-flex h-2 w-2 rounded-full", toneClass[tone])} />
    </span>
  );
}
