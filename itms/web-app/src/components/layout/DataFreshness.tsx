import { useClock } from "@/hooks/useClock";
import { useSystemStore } from "@/store/systemStore";

export function DataFreshness() {
  const now = useClock();
  const mode = useSystemStore((s) => s.dataMode);
  const last = useSystemStore((s) => s.summary.lastUpdate);
  const status = useSystemStore((s) => s.connectionStatus);
  const age = last
    ? Math.max(0, Math.floor((now.getTime() - Date.parse(last)) / 1000))
    : null;
  const fresh = age !== null && age < 6 && status === "online";
  return (
    <span
      className={`data-freshness ${fresh ? "fresh" : "stale"}`}
      role="status"
    >
      <span className="telemetry-pulse" />
      {mode === "simulation" ? "DEMO" : "LIVE"}
      <i />
      {age === null
        ? "Awaiting telemetry"
        : fresh
          ? `Updated ${age}s ago`
          : `Stale · last update ${age}s ago`}
    </span>
  );
}
