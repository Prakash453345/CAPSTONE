import { useEffect, useRef, useState } from "react";
import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudMoon,
  CloudRain,
  CloudRainWind,
  Moon,
  Sun,
  type LucideIcon,
} from "lucide-react";
import { useMapChromeStore } from "@/store/mapChromeStore";
import { useEffectiveWeather, useWeatherStore, type DemoWeather } from "@/store/weatherStore";
import { trafficAdvice, type WeatherCondition, type WeatherNow } from "@/services/weather/weather";
import { cn } from "@/utils/cn";

const LABEL: Record<WeatherCondition, string> = {
  clear: "Clear",
  cloudy: "Cloudy",
  fog: "Fog",
  drizzle: "Drizzle",
  rain: "Rain",
  "heavy-rain": "Heavy rain",
  thunderstorm: "Thunderstorm",
};

function iconFor(w: Pick<WeatherNow, "condition" | "isDay">): LucideIcon {
  switch (w.condition) {
    case "clear":
      return w.isDay ? Sun : Moon;
    case "cloudy":
      return w.isDay ? Cloud : CloudMoon;
    case "fog":
      return CloudFog;
    case "drizzle":
      return CloudDrizzle;
    case "rain":
      return CloudRain;
    case "heavy-rain":
      return CloudRainWind;
    case "thunderstorm":
      return CloudLightning;
  }
}

const DEMOS: Array<{ value: DemoWeather | null; label: string }> = [
  { value: null, label: "Live" },
  { value: "clear", label: "Clear" },
  { value: "rain", label: "Rain" },
  { value: "heavy-rain", label: "Heavy" },
  { value: "thunderstorm", label: "Storm" },
  { value: "fog", label: "Fog" },
];

/**
 * Apple Maps-style weather badge in the map's top-right corner: icon and
 * temperature at a glance, details and a presenter's demo switch on tap.
 */
export function WeatherChip() {
  const weather = useEffectiveWeather();
  const status = useWeatherStore((s) => s.status);
  const demo = useWeatherStore((s) => s.demo);
  const setDemo = useWeatherStore((s) => s.setDemo);
  const open = useMapChromeStore((s) => s.sheet === "weather");
  const toggle = useMapChromeStore((s) => s.toggle);
  const close = useMapChromeStore((s) => s.close);
  const rootRef = useRef<HTMLDivElement | null>(null);
  // The panel opens to the chip's left; on narrow maps (phones) cap it to the space there so it isn't clipped by the map edge.
  const [maxWidth, setMaxWidth] = useState<number | undefined>(undefined);
  useEffect(() => {
    if (!open) return;
    const root = rootRef.current;
    const mapEl = root?.closest<HTMLElement>("[data-map-root]");
    if (!root || !mapEl) return;
    const chip = root.getBoundingClientRect();
    // Room left of the chip, inside whatever glass covers the map's left edge.
    const left = mapEl.getBoundingClientRect().left + (parseFloat(getComputedStyle(mapEl).getPropertyValue("--inset-l")) || 0);
    // Panel's right edge sits 8 px left of the chip; keep 8 px from that edge.
    setMaxWidth(Math.max(140, chip.left - left - 16));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) close("weather");
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close("weather");
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  if (!weather) return null;
  const Icon = iconFor(weather);
  const temp = `${Math.round(weather.temperatureC)}°`;
  const label = LABEL[weather.condition];
  const advice = trafficAdvice(weather);

  return (
    <div ref={rootRef} className="pointer-events-auto relative z-[25]">
      <button
        type="button"
        onClick={() => toggle("weather")}
        aria-expanded={open}
        aria-label={`Weather: ${label}, ${temp}${demo ? " (demo)" : ""}. Show details`}
        title={`${label} · ${temp}`}
        className={cn(
          "glass flex h-12 w-10 flex-col items-center justify-center gap-0.5 glass-hover rounded-[12px] transition-colors",
          demo && "ring-2 ring-primary/60",
        )}
      >
        <Icon className="size-[18px] text-muted-foreground" aria-hidden />
        <span className="text-[11px] font-medium tabular-nums leading-none text-foreground">{temp}</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Weather details"
          style={{ maxWidth }}
          className="glass-strong absolute right-12 top-0 max-h-[70vh] w-72 origin-top-right animate-sheet-in overflow-y-auto rounded-[14px]"
        >
          <div className="flex items-center gap-3 px-4 pb-3 pt-4">
            <Icon className="size-8 text-muted-foreground" aria-hidden />
            <div className="min-w-0">
              <div className="text-2xl font-medium tabular-nums leading-7 text-foreground">{temp}</div>
              <div className="text-sm text-muted-foreground">
                {label}
                {demo ? " · demo" : status === "error" ? " · may be out of date" : ""}
              </div>
            </div>
          </div>

          <dl className="grid grid-cols-3 gap-2 border-t border-border px-4 py-3 text-xs">
            <Fact label="Rain" value={weather.rainMmPerH > 0 ? `${weather.rainMmPerH.toFixed(1)} mm/h` : "None"} />
            <Fact label="Wind" value={`${Math.round(weather.windKmh)} km/h`} />
            <Fact
              label="Visibility"
              value={weather.visibilityM >= 10000 ? "10+ km" : `${(weather.visibilityM / 1000).toFixed(1)} km`}
            />
          </dl>

          {advice && (
            <p className="border-t border-border px-4 py-3 text-sm text-status-warn">{advice}</p>
          )}

          {!demo && weather.outlook.length > 0 && (
            <ul className="flex gap-2 border-t border-border px-4 py-3 text-xs text-muted-foreground" aria-label="Next hours">
              {weather.outlook.map((h) => {
                const HourIcon = iconFor({ condition: h.condition, isDay: weather.isDay });
                return (
                  <li key={h.time} className="flex flex-1 flex-col items-center gap-1">
                    <span className="tabular-nums">{h.time.slice(11, 16)}</span>
                    <HourIcon className="size-4" aria-hidden />
                    <span className="tabular-nums">{h.rainChance}%</span>
                  </li>
                );
              })}
            </ul>
          )}

          <div className="border-t border-border px-4 py-3">
            <div className="mb-2 text-xs font-medium text-muted-foreground">Presentation weather</div>
            <div role="radiogroup" aria-label="Presentation weather" className="flex flex-wrap gap-1.5">
              {DEMOS.map((d) => {
                const on = demo === d.value;
                return (
                  <button
                    key={d.label}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    onClick={() => setDemo(d.value)}
                    className={cn(
                      "h-7 rounded-full border px-2.5 text-xs font-medium transition-colors",
                      on
                        ? "border-transparent bg-primary text-primary-foreground"
                        : "border-input text-foreground hover:bg-muted",
                    )}
                  >
                    {d.label}
                  </button>
                );
              })}
            </div>
          </div>

          <p className="px-4 pb-3 text-[11px] text-muted-foreground">
            Weather data by{" "}
            <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer" className="underline">
              Open-Meteo.com
            </a>{" "}
            (CC BY 4.0)
          </p>
        </div>
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular-nums text-foreground">{value}</dd>
    </div>
  );
}
