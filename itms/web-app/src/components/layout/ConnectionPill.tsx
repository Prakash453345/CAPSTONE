import { useSyncExternalStore } from "react";
import { WifiOff, Wifi, Loader2, TriangleAlert } from "lucide-react";
import { useSystemStore, selectIsStale } from "@/store/systemStore";
import { StatusDot } from "@/components/ui/status-dot";
import { cn } from "@/utils/cn";
import type { ConnectionStatus } from "@/types";

const META: Record<
  ConnectionStatus,
  { label: string; tone: "ok" | "warn" | "critical" | "info"; Icon: typeof Wifi }
> = {
  online: { label: "Live", tone: "ok", Icon: Wifi },
  connecting: { label: "Connecting", tone: "info", Icon: Loader2 },
  reconnecting: { label: "Reconnecting", tone: "warn", Icon: Loader2 },
  offline: { label: "Offline", tone: "critical", Icon: WifiOff },
};

/** Re-render every second so the stale check stays current. */
function useTick(intervalMs = 1000) {
  return useSyncExternalStore(
    (cb) => {
      const id = window.setInterval(cb, intervalMs);
      return () => window.clearInterval(id);
    },
    () => Math.floor(Date.now() / intervalMs),
  );
}

export function ConnectionPill() {
  useTick();
  const status = useSystemStore((s) => s.connectionStatus);
  const isStale = useSystemStore((s) => selectIsStale(s));

  const stale = isStale && status === "online";
  const meta = stale
    ? { label: "Stale data", tone: "warn" as const, Icon: TriangleAlert }
    : META[status];
  const spinning = status === "connecting" || status === "reconnecting";

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-full border border-border bg-surface px-2.5 py-1 font-mono text-[11px] tracking-wide",
        stale && "border-status-warn/40",
      )}
      title={
        stale
          ? "Connected, but no fresh updates recently"
          : `Data connection: ${meta.label}`
      }
    >
      <StatusDot tone={meta.tone} pulse={meta.tone === "ok" && !stale} />
      <meta.Icon className={cn("size-3.5 opacity-80", spinning && "animate-spin")} />
      <span className="text-muted-foreground">{meta.label}</span>
    </div>
  );
}
