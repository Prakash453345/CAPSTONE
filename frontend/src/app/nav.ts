import {
  LayoutDashboard,
  ScanEye,
  Waypoints,
  Ambulance,
  BarChart3,
  Settings2,
  Map as MapIcon,
  type LucideIcon,
} from "lucide-react";
import type { WorkspaceId } from "@/types";

export type NavGroup = "monitor" | "operate" | "review";

export interface NavItem {
  id: WorkspaceId | "map";
  label: string;
  /** Short label for the collapsed rail / tooltips. */
  short: string;
  path: string;
  icon: LucideIcon;
  group: NavGroup | "footer";
  /** One line describing the workspace, used by the command palette. */
  blurb: string;
}

export const NAV_GROUPS: { id: NavGroup; label: string }[] = [
  { id: "monitor", label: "Monitor" },
  { id: "operate", label: "Operate" },
  { id: "review", label: "Review" },
];

export const NAV_ITEMS: NavItem[] = [
  {
    id: "overview",
    label: "Overview",
    short: "Overview",
    path: "/console",
    icon: LayoutDashboard,
    group: "monitor",
    blurb: "How the network is doing right now, and what needs you.",
  },
  {
    id: "map",
    label: "Live map",
    short: "Map",
    path: "/console/map",
    icon: MapIcon,
    group: "monitor",
    blurb: "The whole corridor on one full-screen map.",
  },
  {
    id: "traffic",
    label: "Traffic",
    short: "Traffic",
    path: "/console/traffic",
    icon: Waypoints,
    group: "operate",
    blurb: "Every road and signal, busiest first.",
  },
  {
    id: "anomalies",
    label: "Incidents",
    short: "Incidents",
    path: "/console/anomalies",
    icon: ScanEye,
    group: "operate",
    blurb: "Review detected incidents and manage disruptions on the road.",
  },
  {
    id: "emergency",
    label: "Emergency",
    short: "Emergency",
    path: "/console/emergency",
    icon: Ambulance,
    group: "operate",
    blurb: "Dispatch units and follow their green corridors.",
  },
  {
    id: "analytics",
    label: "Analytics",
    short: "Analytics",
    path: "/console/analytics",
    icon: BarChart3,
    group: "review",
    blurb: "Trends across this session: congestion, speed and load.",
  },
  {
    id: "settings",
    label: "Settings",
    short: "Settings",
    path: "/console/settings",
    icon: Settings2,
    group: "footer",
    blurb: "Data source, appearance and map layers.",
  },
];

export const NAV_BY_PATH = new Map(NAV_ITEMS.map((item) => [item.path, item]));

/** The nav item whose section contains `pathname`, or null for an address
 *  the console doesn't have (its 404 page), so nothing claims to be current. */
export function navItemFor(pathname: string): NavItem | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/console") return NAV_ITEMS[0]!;
  return NAV_ITEMS.find((i) => i.path !== "/console" && (path === i.path || path.startsWith(`${i.path}/`))) ?? null;
}
