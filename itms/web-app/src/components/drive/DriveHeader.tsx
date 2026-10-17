import { LayoutDashboard, LogOut, Moon, Sun, WifiOff } from "lucide-react";
import { Link } from "react-router-dom";
import { BrandMark } from "@/components/branding/BrandMark";
import { Pill } from "@/components/console/kit";
import type { UnitOption } from "@/drive/useMission";
import { useAuthStore } from "@/store/authStore";
import { useSystemStore } from "@/store/systemStore";
import { useThemeStore } from "@/store/themeStore";
import { cn } from "@/utils/cn";

const ICON_BTN =
  "grid size-10 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&_svg]:size-[18px]";

/** Who is driving, whether the data is live, and the few page-level controls. */
export function DriveHeader({
  units,
  unitId,
  onUnit,
  className,
}: {
  units: UnitOption[];
  unitId: string | null;
  onUnit: (id: string) => void;
  className?: string;
}) {
  const mode = useSystemStore((s) => s.dataMode);
  const connection = useSystemStore((s) => s.connectionStatus);
  const theme = useThemeStore((s) => s.resolved);
  const setTheme = useThemeStore((s) => s.setMode);
  const user = useAuthStore((s) => s.user);
  const signOut = useAuthStore((s) => s.signOut);

  return (
    <header className={cn("pointer-events-auto rounded-2xl bg-surface-raised p-3 shadow-elevation-3", className)}>
      <div className="flex items-center gap-3">
        <BrandMark />
        <div className="min-w-0 flex-1">
          <h1 className="text-[15px] font-semibold leading-tight tracking-[-0.01em]">TRAFFIX Drive</h1>
          <p className="truncate text-[12px] text-muted-foreground">{user ? `Signed in as ${user.displayName}` : "Emergency vehicle guidance"}</p>
        </div>
        <Link to="/console" className={ICON_BTN} aria-label="Open the operator console" title="Operator console">
          <LayoutDashboard />
        </Link>
        <button type="button" className={ICON_BTN} aria-label={theme === "dark" ? "Use the light theme" : "Use the dark theme"} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? <Sun /> : <Moon />}
        </button>
        <button type="button" className={ICON_BTN} aria-label="Sign out" title="Sign out" onClick={() => void signOut().catch(() => undefined)}>
          <LogOut />
        </button>
      </div>

      <div className="mt-3 flex items-center gap-2">
        <label className="sr-only" htmlFor="drive-unit">
          Vehicle
        </label>
        <select
          id="drive-unit"
          value={unitId ?? ""}
          onChange={(e) => onUnit(e.target.value)}
          className="h-10 min-w-0 flex-1 rounded-xl border border-input bg-surface px-3 text-[14px] font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {!unitId && <option value="">Choose your vehicle…</option>}
          {units.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
              {u.active ? " · on a mission" : ""}
            </option>
          ))}
        </select>
        {connection === "online" ? (
          <Pill tone={mode === "live" ? "ok" : "warn"} dot>
            {mode === "live" ? "Live" : "Demo"}
          </Pill>
        ) : (
          <Pill tone="critical">
            <WifiOff className="size-3.5" aria-hidden />
            {connection === "connecting" ? "Connecting" : "Offline"}
          </Pill>
        )}
      </div>
    </header>
  );
}
