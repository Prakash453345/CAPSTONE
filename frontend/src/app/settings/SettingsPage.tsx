import { useState, type FormEvent, type ReactNode } from "react";
import { Check, FlaskConical, Monitor, Moon, Radio, Sun } from "lucide-react";
import { PageHeader, Panel, Segmented, Switch } from "@/components/console/kit";
import { useSystemStore } from "@/store/systemStore";
import { useThemeStore, type ThemeMode } from "@/store/themeStore";
import { useMapStore, type MapLayerId } from "@/store/mapStore";
import { AuthError, changePassword } from "@/services/auth/authApi";
import { cn } from "@/utils/cn";
import type { DataMode } from "@/types";

const LAYERS: { id: MapLayerId; label: string; hint: string }[] = [
  { id: "congestion", label: "Congestion", hint: "Colours each road from free flow to jam" },
  { id: "vehicles", label: "Vehicles", hint: "Every vehicle, as a dot until you zoom in" },
  { id: "signals", label: "Signals", hint: "Junction controllers and green-corridor holds" },
  { id: "incidents", label: "Incidents", hint: "Candidates from the detection model" },
  { id: "anomalies", label: "Anomalies", hint: "Disruptions on the road right now" },
  { id: "emergency", label: "Emergency routes & units", hint: "Units on the road and their routes" },
  { id: "weather", label: "Weather", hint: "Current conditions and rain over the map" },
];

/**
 * Preferences that live in the browser: appearance, data source and which
 * layers the maps draw. Detection and signal-timing thresholds are server-side
 * safety configuration and are deliberately not editable here.
 */
export function SettingsPage() {
  const dataMode = useSystemStore((s) => s.dataMode);
  const setDataMode = useSystemStore((s) => s.setDataMode);
  const theme = useThemeStore((s) => s.mode);
  const setTheme = useThemeStore((s) => s.setMode);
  const activeLayers = useMapStore((s) => s.activeLayers);
  const toggleLayer = useMapStore((s) => s.toggleLayer);

  return (
    <div className="mx-auto max-w-[760px] space-y-6 px-4 pb-10 sm:px-6">
      <PageHeader title="Settings" description="These apply to this browser straight away." />

      <Section title="Appearance" description="Match your system, or pick one.">
        <Segmented<ThemeMode>
          value={theme}
          onChange={setTheme}
          ariaLabel="Appearance"
          options={[
            { value: "system", label: "System", icon: Monitor },
            { value: "light", label: "Light", icon: Sun },
            { value: "dark", label: "Dark", icon: Moon },
          ]}
        />
      </Section>

      <Section title="Data source" description="Where the console reads traffic from.">
        <div className="grid gap-2 sm:grid-cols-2">
          {(
            [
              ["live", "Live", Radio, "The running city simulation, streamed from the api-gateway. Commands work."],
              ["simulation", "Demo", FlaskConical, "A self-contained simulation in this browser. Nothing to set up; reports and dispatches work but stay in the browser."],
            ] as [DataMode, string, typeof Radio, string][]
          ).map(([value, label, Icon, hint]) => {
            const on = dataMode === value;
            return (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={on}
                onClick={() => setDataMode(value)}
                className={cn(
                  "relative rounded-2xl p-4 text-left transition-[box-shadow,background-color] duration-200",
                  on ? "bg-primary-muted ring-2 ring-primary" : "bg-muted/60 hover:bg-muted",
                )}
              >
                <span className="flex items-center gap-2 text-[14px] font-semibold text-foreground">
                  <Icon className="size-4" /> {label}
                </span>
                <span className="mt-1 block text-[12.5px] leading-relaxed text-muted-foreground">{hint}</span>
                {on && (
                  <span className="absolute right-3 top-3 grid size-5 place-items-center rounded-full bg-primary text-primary-foreground">
                    <Check className="size-3" strokeWidth={3} />
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </Section>

      <Section title="Map layers" description="What every map in the console draws.">
        <ul className="-mx-1 divide-y divide-border">
          {LAYERS.map((l) => (
            <li key={l.id} className="flex items-center justify-between gap-4 px-1 py-3">
              <span>
                <span className="block text-[14px] font-medium text-foreground">{l.label}</span>
                <span className="block text-[12.5px] text-muted-foreground">{l.hint}</span>
              </span>
              <Switch checked={activeLayers.has(l.id)} onChange={() => toggleLayer(l.id)} label={l.label} />
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Account" description="Change your sign-in password. Other devices are signed out.">
        <PasswordForm />
      </Section>

      <Section title="What's behind the numbers">
        <dl className="space-y-4 text-[13px] leading-relaxed">
          <div>
            <dt className="font-medium text-foreground">Live simulation with safety checks</dt>
            <dd className="mt-0.5 text-muted-foreground">
              SUMO traffic, controller activity, disruptions, emergency routes and green corridors. Every signal change passes the backend
              safety interlocks first.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-foreground">Detection needs a trained model</dt>
            <dd className="mt-0.5 text-muted-foreground">
              Graph and conformal detection is integrated, but accuracy depends on the model you run. Every candidate waits for a person.
              Camera ingestion is not implemented yet.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-foreground">Session analytics only</dt>
            <dd className="mt-0.5 text-muted-foreground">
              Charts hold up to 30 minutes of received observations. Detection thresholds, routing weights and signal timing are server-side
              safety configuration and cannot be changed here.
            </dd>
          </div>
        </dl>
      </Section>
    </div>
  );
}

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Panel className="p-5">
      <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
      {description && <p className="mt-0.5 text-[13px] text-muted-foreground">{description}</p>}
      <div className="mt-4">{children}</div>
    </Panel>
  );
}

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setStatus(null);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setStatus({ ok: true, text: "Password changed." });
    } catch (err) {
      const text =
        (err instanceof AuthError && err.detail) || "Couldn't change the password. Try again.";
      setStatus({ ok: false, text });
    } finally {
      setBusy(false);
    }
  }

  const input = "h-9 w-full max-w-xs rounded-md border border-border bg-background px-3 text-[13px] text-foreground";
  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block text-[13px] text-foreground">
        Current password
        <input type="password" autoComplete="current-password" required value={current}
          onChange={(e) => setCurrent(e.target.value)} className={cn(input, "mt-1 block")} />
      </label>
      <label className="block text-[13px] text-foreground">
        New password (at least 10 characters)
        <input type="password" autoComplete="new-password" required minLength={10} value={next}
          onChange={(e) => setNext(e.target.value)} className={cn(input, "mt-1 block")} />
      </label>
      <button type="submit" disabled={busy || !current || next.length < 10}
        className="h-9 rounded-md bg-primary px-4 text-[13px] font-medium text-primary-foreground disabled:opacity-50">
        {busy ? "Saving…" : "Change password"}
      </button>
      {status && (
        <p role="status" className={cn("text-[13px]", status.ok ? "text-foreground" : "text-destructive")}>{status.text}</p>
      )}
    </form>
  );
}
