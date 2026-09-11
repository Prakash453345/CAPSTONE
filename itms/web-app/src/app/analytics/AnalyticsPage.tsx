import { BarChart3 } from "lucide-react";
import { WorkspacePlaceholder } from "@/components/layout/WorkspacePlaceholder";

export function AnalyticsPage() {
  return (
    <WorkspacePlaceholder
      title="Analytics"
      blurb="Waiting time, speed, queue length and congestion trends; anomaly detection latency; incident and false-alarm trends; emergency transit time; fixed-timer baseline comparison."
      icon={BarChart3}
      phase="Planned"
    />
  );
}
