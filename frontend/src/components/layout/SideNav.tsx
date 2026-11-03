import { NavLink, useLocation } from "react-router-dom";
import { Navigation, PanelLeftClose, PanelLeftOpen, Search, type LucideIcon } from "lucide-react";
import { NAV_GROUPS, NAV_ITEMS, navItemFor, type NavItem } from "@/app/nav";
import { BrandMark } from "@/components/branding/BrandMark";
import { Tooltip } from "@/components/ui/tooltip";
import { useIncidentStore } from "@/store/incidentStore";
import { useActiveRequests } from "@/store/emergencyStore";
import { cn } from "@/utils/cn";
import { CITIES_LABEL, SHOWN_CITIES } from "@/data/city";
import { NAV_WIDTH } from "@/components/layout/mapFirst";

interface SideNavProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  /** Called after a nav item is chosen, so the mobile drawer can close itself. */
  onNavigate?: () => void;
  /** Opens the command palette: the rail's first row, as Search is in Apple Maps. */
  onOpenSearch: () => void;
}

/** Apple Maps' sidebar row: the glyph in a rounded tile, then the label. */
const ROW =
  "group relative z-[1] flex h-11 w-full items-center gap-3 rounded-xl px-2 text-[15px] font-medium tracking-[-0.01em] outline-none transition-colors duration-150";

function Tile({ icon: Icon, active }: { icon: LucideIcon; active?: boolean }) {
  return (
    <span
      className={cn(
        "grid size-[30px] shrink-0 place-items-center rounded-[9px] transition-colors duration-200",
        active
          ? "bg-system-blue text-white"
          : "bg-tile text-foreground shadow-[0_0.5px_1.5px_rgba(0,0,0,0.12)] group-hover:text-foreground",
      )}
    >
      <Icon className="size-[17px]" strokeWidth={2} />
    </span>
  );
}

/** Live counts that deserve a glance from anywhere in the console. */
function useBadges() {
  const incidents = useIncidentStore((s) => s.incidents.filter((i) => i.status === "candidate").length);
  const anomalies = useIncidentStore((s) => s.anomalies.filter((a) => a.status === "active").length);
  const emergencies = useActiveRequests().length;
  return { anomalies: incidents + anomalies, emergency: emergencies } as Partial<Record<NavItem["id"], number>>;
}

export function SideNav({ collapsed, onToggleCollapsed, onNavigate, onOpenSearch }: SideNavProps) {
  const { pathname } = useLocation();
  const current = navItemFor(pathname);
  const badges = useBadges();

  const goTo = () => onNavigate?.();

  const item = (it: NavItem) => {
    const active = it.id === current?.id;
    const count = badges[it.id] ?? 0;
    const link = (
      <NavLink
        to={it.path}
        end={it.path === "/console"}
        onClick={goTo}
        aria-current={active ? "page" : undefined}
        aria-description={count > 0 ? `${count} ${it.id === "emergency" ? "active" : "need attention"}` : undefined}
        className={cn(ROW, "text-foreground", active ? "bg-glass-hover" : "hover:bg-glass-hover", collapsed && "justify-center px-0")}
      >
        <Tile icon={it.icon} active={active} />
        {!collapsed && <span className="truncate">{it.label}</span>}
        {count > 0 &&
          (collapsed ? (
            <span aria-hidden className="absolute right-2.5 top-1.5 size-2.5 rounded-full bg-status-critical ring-2 ring-background" />
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
      className={cn(ROW, "text-foreground hover:bg-glass-hover", collapsed && "justify-center px-0")}
    >
      <Tile icon={Navigation} />
      {!collapsed && <span className="truncate">Crew view</span>}
    </NavLink>
  );

  const mac = typeof navigator !== "undefined" && /Mac|iP(hone|ad)/.test(navigator.platform);
  const searchRow = (
    <button
      type="button"
      onClick={onOpenSearch}
      aria-keyshortcuts={mac ? "Meta+K" : "Control+K"}
      className={cn(ROW, "text-foreground hover:bg-glass-hover", collapsed && "justify-center px-0")}
    >
      <Tile icon={Search} />
      {!collapsed && (
        <>
          <span className="flex-1 truncate text-left">Search</span>
          <span className="pr-1 text-[12px] font-normal tracking-normal text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
            {mac ? "⌘K" : "Ctrl K"}
          </span>
        </>
      )}
    </button>
  );

  return (
    <nav
      aria-label="Primary"
      className="glass-sidebar relative isolate flex h-full flex-col transition-[width] duration-300 ease-[cubic-bezier(.22,1,.36,1)]"
      style={{ width: NAV_WIDTH[collapsed ? "collapsed" : "expanded"] }}
    >
      <div className={cn("flex h-[68px] shrink-0 items-center gap-2.5 pl-5 pr-3", collapsed && "justify-center px-0")}>
        <BrandMark />
        {!collapsed && (
          <>
            <div className="min-w-0 flex-1 leading-tight">
              <div className="text-[19px] font-semibold tracking-[-0.025em]">Traffix</div>
              <div className="truncate text-[11.5px] text-muted-foreground">
                {SHOWN_CITIES.length > 1 ? CITIES_LABEL : `${CITIES_LABEL} operations`}
              </div>
            </div>
            <Tooltip label="Hide sidebar">
              <button
                type="button"
                onClick={onToggleCollapsed}
                aria-label="Collapse navigation"
                className="grid size-9 shrink-0 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-glass-hover hover:text-foreground"
              >
                <PanelLeftClose className="size-[19px]" strokeWidth={1.7} />
              </button>
            </Tooltip>
          </>
        )}
      </div>

      <div className="isolate flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-3 pb-3 pt-1">
        <ul>
          <li>{collapsed ? <Tooltip label="Search">{searchRow}</Tooltip> : searchRow}</li>
        </ul>
        {NAV_GROUPS.map((g) => (
          <div key={g.id}>
            {!collapsed ? (
              <div className="px-2 pb-1 text-[12px] font-semibold text-muted-foreground">{g.label}</div>
            ) : (
              <div className="mx-auto mb-2 h-px w-6 bg-[var(--glass-edge)]" />
            )}
            <ul className="flex flex-col gap-0.5">{NAV_ITEMS.filter((i) => i.group === g.id).map(item)}</ul>
          </div>
        ))}
      </div>

      <div className="isolate shrink-0 px-3 pb-4 pt-2">
        <ul className="flex flex-col gap-0.5">
          <li>{collapsed ? <Tooltip label="Crew view">{crewLink}</Tooltip> : crewLink}</li>
          {NAV_ITEMS.filter((i) => i.group === "footer").map(item)}
          {collapsed && (
            <li>
              <Tooltip label="Show sidebar">
                <button
                  type="button"
                  onClick={onToggleCollapsed}
                  aria-label="Expand navigation"
                  className={cn(ROW, "justify-center px-0 text-muted-foreground hover:bg-glass-hover hover:text-foreground")}
                >
                  <PanelLeftOpen className="size-[19px]" strokeWidth={1.7} />
                </button>
              </Tooltip>
            </li>
          )}
        </ul>
      </div>
    </nav>
  );
}
