import { NavLink, useLocation } from "react-router-dom";
import { useRef } from "react";
import { Navigation, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NAV_GROUPS, NAV_ITEMS, navItemFor, type NavItem } from "@/app/nav";
import { BrandMark } from "@/components/branding/BrandMark";
import { Tooltip } from "@/components/ui/tooltip";
import { useIndicator } from "@/components/console/hooks";
import { useSystemStore } from "@/store/systemStore";
import { useIncidentStore } from "@/store/incidentStore";
import { useActiveRequests } from "@/store/emergencyStore";
import { cn } from "@/utils/cn";
import { CITIES_LABEL, SHOWN_CITIES } from "@/data/city";

interface SideNavProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  /** Called after a nav item is chosen, so the mobile drawer can close itself. */
  onNavigate?: () => void;
}

/** Live counts that deserve a glance from anywhere in the console. */
function useBadges() {
  const incidents = useIncidentStore((s) => s.incidents.filter((i) => i.status === "candidate").length);
  const anomalies = useIncidentStore((s) => s.anomalies.filter((a) => a.status === "active").length);
  const emergencies = useActiveRequests().length;
  return { anomalies: incidents + anomalies, emergency: emergencies } as Partial<Record<NavItem["id"], number>>;
}

export function SideNav({ collapsed, onToggleCollapsed, onNavigate }: SideNavProps) {
  const viewMode = useSystemStore((s) => s.viewMode);
  const setViewMode = useSystemStore((s) => s.setViewMode);
  const { pathname } = useLocation();
  const current = navItemFor(pathname);
  const badges = useBadges();
  // the active pill slides between items with a CSS transition
  const navRef = useRef<HTMLElement>(null);
  const pill = useIndicator(navRef, '[aria-current="page"]', [current?.id, collapsed, viewMode]);

  // Split view replaces the routed page, so choosing a page leaves it.
  const goTo = () => {
    if (viewMode === "split") setViewMode("single");
    onNavigate?.();
  };

  const item = (it: NavItem) => {
    const active = viewMode !== "split" && it.id === current?.id;
    const count = badges[it.id] ?? 0;
    const link = (
      <NavLink
        to={it.path}
        end={it.path === "/console"}
        onClick={goTo}
        aria-current={active ? "page" : undefined}
        aria-description={count > 0 ? `${count} ${it.id === "emergency" ? "active" : "need attention"}` : undefined}
        className={cn(
          "group relative z-[1] flex h-9 items-center gap-3 rounded-xl px-2.5 text-[13.5px] font-medium outline-none transition-colors duration-150",
          active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
          collapsed && "justify-center px-0",
        )}
      >
        {!active && <span className="absolute inset-0 -z-10 rounded-xl opacity-0 transition-opacity group-hover:bg-muted group-hover:opacity-100" />}
        <it.icon className={cn("size-[18px] shrink-0", active && "text-primary")} strokeWidth={1.8} />
        {!collapsed && <span className="truncate">{it.label}</span>}
        {count > 0 &&
          (collapsed ? (
            <span aria-hidden className="absolute right-1.5 top-1.5 size-2 rounded-full bg-status-critical ring-2 ring-background" />
          ) : (
            <span
              aria-hidden
              className={cn(
                "ml-auto grid h-5 min-w-5 place-items-center rounded-full px-1.5 text-[11px] font-semibold tabular",
                it.id === "emergency" ? "bg-status-critical text-white" : "bg-status-warn-muted text-status-warn",
              )}
            >
              {count}
            </span>
          ))}
      </NavLink>
    );
    return <li key={it.id}>{collapsed ? <Tooltip label={it.label}>{link}</Tooltip> : link}</li>;
  };

  // What an emergency crew sees, from the same live data: a separate page, not a workspace.
  const crewLink = (
    <NavLink
      to="/crew"
      onClick={goTo}
      className={cn(
        "group relative z-[1] flex h-9 items-center gap-3 rounded-xl px-2.5 text-[13.5px] font-medium text-muted-foreground outline-none transition-colors duration-150 hover:bg-muted hover:text-foreground",
        collapsed && "justify-center px-0",
      )}
    >
      <Navigation className="size-[18px] shrink-0" strokeWidth={1.8} />
      {!collapsed && <span className="truncate">Crew view</span>}
    </NavLink>
  );

  return (
    <nav
      ref={navRef}
      aria-label="Primary"
      className={cn(
        "relative isolate flex h-full flex-col bg-background transition-[width] duration-300 ease-[cubic-bezier(.22,1,.36,1)]",
        collapsed ? "w-[68px]" : "w-[232px]",
      )}
    >
      <span aria-hidden className="pointer-events-none absolute left-0 top-0 z-0 rounded-xl bg-surface shadow-elevation-1" style={pill} />
      <div className={cn("flex h-16 shrink-0 items-center gap-2.5 px-4", collapsed && "justify-center px-0")}>
        <BrandMark />
        {!collapsed && (
          <div className="min-w-0 leading-tight">
            <div className="text-[15px] font-semibold tracking-[-0.01em]">Traffix</div>
            <div className="text-[11.5px] text-muted-foreground">
              {SHOWN_CITIES.length > 1 ? CITIES_LABEL : `${CITIES_LABEL} operations`}
            </div>
          </div>
        )}
      </div>

      <div className="isolate flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-3 pb-3 pt-2">
        {NAV_GROUPS.map((g) => (
          <div key={g.id}>
            {!collapsed ? (
              <div className="px-2.5 pb-1.5 text-[11.5px] font-medium text-muted-foreground">{g.label}</div>
            ) : (
              <div className="mx-auto mb-2 h-px w-6 bg-border" />
            )}
            <ul className="flex flex-col gap-0.5">{NAV_ITEMS.filter((i) => i.group === g.id).map(item)}</ul>
          </div>
        ))}
      </div>

      <div className="isolate shrink-0 px-3 pb-4">
        <ul className="flex flex-col gap-0.5">
          <li>{collapsed ? <Tooltip label="Crew view">{crewLink}</Tooltip> : crewLink}</li>
          {NAV_ITEMS.filter((i) => i.group === "footer").map(item)}
        </ul>
        <button
          type="button"
          onClick={onToggleCollapsed}
          className={cn(
            "mt-0.5 flex h-9 w-full items-center gap-3 rounded-xl px-2.5 text-[13.5px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
            collapsed && "justify-center px-0",
          )}
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
        >
          {collapsed ? <PanelLeftOpen className="size-[18px]" strokeWidth={1.8} /> : <PanelLeftClose className="size-[18px]" strokeWidth={1.8} />}
          {!collapsed && <span>Collapse</span>}
        </button>
      </div>
    </nav>
  );
}
