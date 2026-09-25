import { useLocation } from "react-router-dom";
import { Menu, FlaskConical, Radio, Columns2, Square, Sun, Moon, Monitor } from "lucide-react";
import { NAV_ITEMS } from "@/app/nav";
import { useSystemStore } from "@/store/systemStore";
import { useThemeStore, type ThemeMode } from "@/store/themeStore";
import { useClock } from "@/hooks/useClock";
import { formatClock } from "@/utils/format";
import { ConnectionPill } from "@/components/layout/ConnectionPill";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { StatusDot } from "@/components/ui/status-dot";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/cn";
import type { DataMode, ViewMode } from "@/types";

function useActiveWorkspaceLabel(viewMode: ViewMode): string {
  const { pathname } = useLocation();
  if (viewMode === "split") return "Split View · Anomalies + Traffic";
  const match =
    [...NAV_ITEMS]
      .filter((i) => i.path !== "/console")
      .find((i) => pathname.startsWith(i.path)) ??
    NAV_ITEMS.find((i) => i.path === "/console");
  return match?.label ?? "Command Center";
}

export function TopBar({ onOpenNav }: { onOpenNav: () => void }) {
  const now = useClock();

  const operational = useSystemStore((s) => s.summary.operational);
  const dataMode = useSystemStore((s) => s.dataMode);
  const setDataMode = useSystemStore((s) => s.setDataMode);
  const viewMode = useSystemStore((s) => s.viewMode);
  const setViewMode = useSystemStore((s) => s.setViewMode);
  const label = useActiveWorkspaceLabel(viewMode);

  return (
    <header className="product-topbar flex min-h-16 shrink-0 flex-wrap items-center gap-3 border-b border-border bg-surface/70 px-3 py-2 backdrop-blur-sm sm:px-6">
      <Button
        variant="subtle"
        size="icon-sm"
        className="lg:hidden"
        onClick={onOpenNav}
        aria-label="Open navigation"
      >
        <Menu />
      </Button>

      <div className="min-w-0">
        <h1 className="truncate text-sm font-semibold tracking-tight">{label}</h1>
      </div>

      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        <div
          className="hidden items-center gap-2 rounded-full border border-border bg-surface px-2.5 py-1 md:flex"
          title={operational ? "All systems operational" : "System degraded"}
        >
          <StatusDot tone={operational ? "ok" : "critical"} pulse={operational} />
          <span className="font-mono text-[11px] tracking-wide text-muted-foreground">
            {dataMode === "simulation" ? "DEMO SESSION" : operational ? "STREAM ACTIVE" : "AWAITING DATA"}
          </span>
        </div>

        <Segmented<DataMode>
          value={dataMode}
          onChange={setDataMode}
          options={[
            { value: "live", label: "Live", icon: Radio },
            { value: "simulation", label: "Demo", icon: FlaskConical },
          ]}
          ariaLabel="Data mode"
        />

        <time
          className="tabular hidden font-mono text-xs text-muted-foreground lg:block"
          dateTime={now.toISOString()}
        >
          {formatClock(now)}
        </time>

        <ConnectionPill />

        <NotificationBell />

        <Segmented<ViewMode>
          value={viewMode}
          onChange={setViewMode}
          options={[
            { value: "single", label: "Single", icon: Square },
            { value: "split", label: "Split", icon: Columns2 },
          ]}
          ariaLabel="View mode"
        />

        <ThemeButton />
      </div>
    </header>
  );
}

const THEME_NEXT: Record<ThemeMode, ThemeMode> = { system: "light", light: "dark", dark: "system" };
const THEME_META: Record<ThemeMode, { icon: typeof Sun; label: string }> = {
  system: { icon: Monitor, label: "Appearance: match system" },
  light: { icon: Sun, label: "Appearance: light" },
  dark: { icon: Moon, label: "Appearance: dark" },
};

/** Cycles system → light → dark, like the Maps apps' appearance setting. */
function ThemeButton() {
  const mode = useThemeStore((s) => s.mode);
  const setMode = useThemeStore((s) => s.setMode);
  const { icon: Icon, label } = THEME_META[mode];
  return (
    <Button
      variant="subtle"
      size="icon-sm"
      onClick={() => setMode(THEME_NEXT[mode])}
      aria-label={`${label}. Click to change.`}
      title={label}
      className="rounded-full"
    >
      <Icon key={mode} className="animate-fade-in" />
    </Button>
  );
}

interface SegOption<T extends string> {
  value: T;
  label: string;
  icon: typeof Radio;
}

function Segmented<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
}: {
  value: T;
  onChange: (v: T) => void;
  options: SegOption<T>[];
  ariaLabel: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="flex items-center gap-0.5 rounded-full border border-border bg-surface p-0.5"
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={opt.label}
            onClick={() => onChange(opt.value)}
            className={cn(
              "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
              active
                ? "bg-primary-muted/60 text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <opt.icon className="size-3.5" />
            <span className="hidden sm:inline">{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}
