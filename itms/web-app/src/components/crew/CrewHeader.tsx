import { LayoutDashboard, LogOut, Moon, Sun, WifiOff } from "lucide-react";
import { Link } from "react-router-dom";
import { BrandMark } from "@/components/branding/BrandMark";
import { Pill } from "@/components/console/kit";
import type { UnitOption } from "@/crew/useMission";
import { CREW_TYPES, crewTypeFor } from "@/store/emergencyStore";
import type { EmergencyVehicleKind } from "@/types";
import { useAuthStore } from "@/store/authStore";
import { useSystemStore } from "@/store/systemStore";
import { useThemeStore } from "@/store/themeStore";
import { cn } from "@/utils/cn";

const ICON_BTN =
  "grid size-10 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&_svg]:size-[18px]";

/** Who is driving, whether the data is live, and the few page-level controls. */
export function CrewHeader({
  units,
  unitId,
  onUnit,
  locked = false,
  kind = null,
  className,
}: {
  units: UnitOption[];
  unitId: string | null;
  onUnit: (id: string) => void;
  /** A crew account: its vehicle is fixed, so it is shown, not chosen. */
  locked?: boolean;
  /** What this crew drives (a crew account knows; shown beside the vehicle). */
  kind?: EmergencyVehicleKind | null;
  className?: string;
}) {
  const mode = useSystemStore((s) => s.dataMode);
  const connection = useSystemStore((s) => s.connectionStatus);
  const theme = useThemeStore((s) => s.resolved);
  const setTheme = useThemeStore((s) => s.setMode);
  const user = useAuthStore((s) => s.user);
  const signOut = useAuthStore((s) => s.signOut);

  const vehicle = units.find((u) => u.id === unitId)?.name ?? unitId ?? "No vehicle linked";
  const status =
    connection === "online" ? (
      <Pill tone={mode === "live" ? "ok" : "warn"} dot>
        {mode === "live" ? "Live" : "Demo"}
      </Pill>
    ) : (
      <Pill tone="critical">
        <WifiOff className="size-3.5" aria-hidden />
        {connection === "connecting" ? "Connecting" : "Offline"}
      </Pill>
    );

  return (
    <header
      className={cn(
        // Floats over the map on a phone; sits in the panel column like the console's cards on a wide screen.
        "pointer-events-auto rounded-2xl bg-surface-raised px-4 py-3 shadow-elevation-3 lg:bg-surface lg:shadow-elevation-1",
        className,
      )}
    >
      <div className="flex items-center gap-3">
        <BrandMark />
        <div className="min-w-0 flex-1">
          <h1 className="text-[15px] font-semibold leading-tight tracking-[-0.01em]">TRAFFIX Crew</h1>
          <p className="mt-0.5 flex min-w-0 items-center gap-2 text-[12.5px] text-muted-foreground">
            <span className="truncate">
              {locked ? (
                <>
                  <span className="sr-only">Vehicle: </span>
                  <span>{kind ? `${crewTypeFor(kind).label} crew · ${vehicle}` : vehicle}</span>
                </>
              ) : user ? (
                `Signed in as ${user.displayName}`
              ) : (
                "Route guidance for emergency vehicles"
              )}
            </span>
            {status}
          </p>
        </div>
        {user?.role !== "responder" && (
          <Link to="/console" className={ICON_BTN} aria-label="Open the operator console" title="Operator console">
            <LayoutDashboard />
          </Link>
        )}
        <button type="button" className={ICON_BTN} aria-label={theme === "dark" ? "Use the light theme" : "Use the dark theme"} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? <Sun /> : <Moon />}
        </button>
        <button type="button" className={ICON_BTN} aria-label="Sign out" title="Sign out" onClick={() => void signOut().catch(() => undefined)}>
          <LogOut />
        </button>
      </div>

      {/* Only operators choose a vehicle; a crew account is tied to its own. */}
      {!locked && (
        <div className="mt-3">
          <label className="sr-only" htmlFor="crew-unit">
            Vehicle
          </label>
          <select
            id="crew-unit"
            value={unitId ?? ""}
            onChange={(e) => onUnit(e.target.value)}
            className="h-10 w-full rounded-xl border border-input bg-surface px-3 text-[14px] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring"
          >
            {!unitId && <option value="">{units.length ? "Choose a vehicle…" : "No unit has had a call yet"}</option>}
            {CREW_TYPES.map((t) => {
              const group = units.filter((u) => u.kind === t.kind);
              return group.length ? (
                <optgroup key={t.kind} label={t.label}>
                  {group.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name}
                      {u.active ? " · on a mission" : ""}
                    </option>
                  ))}
                </optgroup>
              ) : null;
            })}
            {units
              .filter((u) => !u.kind)
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                  {u.active ? " · on a mission" : ""}
                </option>
              ))}
          </select>
        </div>
      )}
    </header>
  );
}
