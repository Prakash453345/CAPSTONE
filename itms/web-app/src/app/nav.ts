import {
  LayoutDashboard,
  ScanEye,
  Waypoints,
  Ambulance,
  BarChart3,
  Settings2,
  type LucideIcon,
} from "lucide-react";
import type { WorkspaceId } from "@/types";

export interface NavItem {
  id: WorkspaceId;
  label: string;
  /** Short label for the collapsed rail / tooltips. */
  short: string;
  path: string;
  icon: LucideIcon;
  /** Optional one-line description for the placeholder screens. */
  blurb: string;
}

export const NAV_ITEMS: NavItem[] = [
  {
    id: "overview",
    label: "Command Center",
    short: "Overview",
    path: "/console",
    icon: LayoutDashboard,
    blurb: "Immediate system awareness — health, live traffic and the incident feed.",
  },
  {
    id: "anomalies",
    label: "Anomaly Detection",
    short: "Anomalies",
    path: "/console/anomalies",
    icon: ScanEye,
    blurb: "Investigate candidate anomalies, review evidence, confirm or dismiss.",
  },
  {
    id: "traffic",
    label: "Traffic Management",
    short: "Traffic",
    path: "/console/traffic",
    icon: Waypoints,
    blurb: "Live map, intersections, signal state and congestion.",
  },
  {
    id: "emergency",
    label: "Emergency Response",
    short: "Emergency",
    path: "/console/emergency",
    icon: Ambulance,
    blurb: "Emergency units, routes and green-corridor progress.",
  },
  {
    id: "analytics",
    label: "Analytics",
    short: "Analytics",
    path: "/console/analytics",
    icon: BarChart3,
    blurb: "Trends, KPIs and fixed-timer baseline comparison.",
  },
  {
    id: "settings",
    label: "Settings",
    short: "Settings",
    path: "/console/settings",
    icon: Settings2,
    blurb: "Data source, thresholds, map layers and operator preferences.",
  },
];

export const NAV_BY_PATH = new Map(NAV_ITEMS.map((item) => [item.path, item]));
