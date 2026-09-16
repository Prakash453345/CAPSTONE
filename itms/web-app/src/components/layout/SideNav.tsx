import { NavLink } from "react-router-dom";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NAV_ITEMS } from "@/app/nav";
import { Tooltip } from "@/components/ui/tooltip";
import { useSystemStore } from "@/store/systemStore";
import { cn } from "@/utils/cn";

interface SideNavProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  /** Called after a nav item is chosen — lets the mobile drawer close itself. */
  onNavigate?: () => void;
}

export function SideNav({ collapsed, onToggleCollapsed, onNavigate }: SideNavProps) {
  const viewMode = useSystemStore((s) => s.viewMode);
  const setViewMode = useSystemStore((s) => s.setViewMode);

  // Split view (Phase 8) replaces the routed page entirely, so a nav click
  // while split is active exits it -- otherwise the sidebar would highlight
  // the clicked page while the split (Anomaly | Traffic) content stays put,
  // silently ignoring the click.
  const goTo = () => {
    if (viewMode === "split") setViewMode("single");
    onNavigate?.();
  };

  return (
    <nav
      aria-label="Primary"
      className={cn(
        "product-nav flex h-full flex-col border-r border-border bg-surface/60 backdrop-blur-sm transition-[width] duration-200",
        collapsed ? "w-16" : "w-60",
      )}
    >
      <div
        className={cn(
          "flex h-14 items-center border-b border-border px-3",
          collapsed ? "justify-center" : "gap-2.5",
        )}
      >
        <BrandMark />
        {!collapsed && (
          <div className="min-w-0 leading-tight">
            <div className="truncate text-sm font-bold tracking-tight">TRAFFIX</div>
            <div className="truncate font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              Command Center
            </div>
          </div>
        )}
      </div>

      {!collapsed && <div className="nav-caption">OPERATIONS WORKSPACE</div>}
      <ul className="flex flex-1 flex-col gap-1 overflow-y-auto p-2">
        {NAV_ITEMS.map((item) => {
          const link = (
            <NavLink
              to={item.path}
              end={item.path === "/"}
              onClick={goTo}
              className={({ isActive }) =>
                cn(
                  "group flex items-center gap-3 rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
                  "text-muted-foreground hover:bg-muted hover:text-foreground",
                  collapsed && "justify-center px-0",
                  isActive &&
                    "bg-primary-muted/50 text-primary hover:bg-primary-muted/60 hover:text-primary",
                )
              }
            >
              <item.icon className="size-[18px] shrink-0" />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </NavLink>
          );
          return (
            <li key={item.id}>
              {collapsed ? <Tooltip label={item.label}>{link}</Tooltip> : link}
            </li>
          );
        })}
      </ul>

      {!collapsed && <div className="nav-city"><span className="eyebrow">CONNECTED CORRIDOR</span><strong>Vijayawada, IN</strong><small>MG Road · Urban mobility network</small></div>}
      <div className="border-t border-border p-2">
        <button
          type="button"
          onClick={onToggleCollapsed}
          className={cn(
            "flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
            collapsed && "justify-center px-0",
          )}
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
        >
          {collapsed ? (
            <PanelLeftOpen className="size-[18px]" />
          ) : (
            <>
              <PanelLeftClose className="size-[18px]" />
              <span>Collapse</span>
            </>
          )}
        </button>
      </div>
    </nav>
  );
}

function BrandMark() {
  return (
    <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-primary/30 bg-primary-muted/40">
      <svg width="16" height="16" viewBox="0 0 32 32" fill="none" aria-hidden>
        <path
          d="M16 4v24M4 16h24"
          stroke="hsl(var(--primary))"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
        <circle
          cx="16"
          cy="16"
          r="3.4"
          fill="hsl(var(--background))"
          stroke="hsl(var(--primary))"
          strokeWidth="2.5"
        />
      </svg>
    </span>
  );
}
