import { TrafficMap } from "@/components/map/TrafficMap";
import { NetworkExplorer } from "@/components/console/NetworkExplorer";
import { WorkspaceLayout } from "@/components/console/WorkspaceLayout";

/** Traffic: every street and signal beside the live map. */
export function TrafficPage() {
  return <WorkspaceLayout label="Roads and signals" panel={<NetworkExplorer />} map={<TrafficMap />} />;
}
