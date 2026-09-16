import { useSystemStore } from "@/store/systemStore";
export function SourceBanner() {
  const mode = useSystemStore((s) => s.dataMode);
  const status = useSystemStore((s) => s.connectionStatus);
  const setMode = useSystemStore((s) => s.setDataMode);
  if (mode === "simulation")
    return (
      <div className="source-banner">
        <span>
          DEMO ENVIRONMENT · Illustrative browser simulation. Not live city
          traffic. Commands are disabled.
        </span>
        <button onClick={() => setMode("live")}>
          Connect to live simulation →
        </button>
      </div>
    );
  if (status !== "online")
    return (
      <div className="source-banner live-warning" role="status">
        <span>
          Waiting for the live simulation. Start api-service and SUMO; the
          stream reconnects automatically.
        </span>
        <button onClick={() => setMode("simulation")}>
          Explore the demo instead
        </button>
      </div>
    );
  return null;
}
