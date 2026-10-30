import { useEffect, useRef, useState } from "react";
import { useMapInstance } from "@/components/map/MapContext";
import { DEFAULT_CENTER } from "@/store/mapStore";
import { useThemeStore } from "@/store/themeStore";
import { useEffectiveWeather, useWeatherStore } from "@/store/weatherStore";
import { rainDensity, type WeatherNow } from "@/services/weather/weather";

const POLL_MS = 10 * 60 * 1000;
const ATTRIB_SRC = "weather-attribution";

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Weather drawn over the map from live Open-Meteo data (or a demo preset):
 * rain streaks slanted by the real wind, a fog veil at low visibility, and a
 * rare soft lightning flash in storms. Deliberately faint: congestion
 * colours and incidents must stay readable through it. Reduced motion gets
 * a still frame and no flashes.
 */
export function WeatherLayer({ visible }: { visible: boolean }) {
  const map = useMapInstance();
  const weather = useEffectiveWeather();
  const refresh = useWeatherStore((s) => s.refresh);

  // Poll while shown. The store ignores overlapping refreshes, so split
  // view's two maps don't double the calls.
  useEffect(() => {
    if (!visible) return;
    const run = () => void refresh(DEFAULT_CENTER.latitude, DEFAULT_CENTER.longitude);
    run();
    const id = window.setInterval(run, POLL_MS);
    return () => window.clearInterval(id);
  }, [visible, refresh]);

  // CC BY 4.0 credit, via an empty source so it joins the map attribution.
  useEffect(() => {
    if (!visible || map.getSource(ATTRIB_SRC)) return;
    map.addSource(ATTRIB_SRC, {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
      attribution: 'Weather <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo.com</a> (CC BY 4.0)',
    });
    return () => {
      if (map.getSource(ATTRIB_SRC)) map.removeSource(ATTRIB_SRC);
    };
  }, [map, visible]);

  if (!visible || !weather) return null;
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 z-[1] overflow-hidden">
      <FogVeil weather={weather} />
      <RainCanvas weather={weather} />
      {weather.condition === "thunderstorm" && <Lightning />}
    </div>
  );
}

interface Drop {
  x: number;
  y: number;
  len: number;
  speed: number;
}

function RainCanvas({ weather }: { weather: WeatherNow }) {
  const map = useMapInstance();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const dark = useThemeStore((s) => s.resolved === "dark");
  const density = rainDensity(weather);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx || density === 0) return;

    let width = 0;
    let height = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    const resize = () => {
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const heavy = weather.condition === "heavy-rain" || weather.condition === "thunderstorm";
    const drops: Drop[] = Array.from({ length: density }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      len: (heavy ? 14 : 9) + Math.random() * (heavy ? 12 : 8),
      speed: (heavy ? 13 : 9) + Math.random() * 5,
    }));
    // Resizing a canvas resets its context, so styles are set per frame.
    const stroke = dark ? "rgba(200, 220, 255, 0.30)" : "rgba(70, 110, 160, 0.22)";
    const lineWidth = heavy ? 1 : 0.8;

    // Screen-space slant: the wind blows toward (from + 180°); rotate by
    // the map's bearing so rain keeps the real direction as the map turns.
    const slant = () => {
      const toward = ((weather.windFromDeg + 180 - map.getBearing()) * Math.PI) / 180;
      return Math.sin(toward) * Math.min(0.45, weather.windKmh / 60);
    };

    const draw = (dx: number) => {
      ctx.clearRect(0, 0, width, height);
      ctx.strokeStyle = stroke;
      ctx.lineWidth = lineWidth;
      ctx.lineCap = "round";
      ctx.beginPath();
      for (const d of drops) {
        ctx.moveTo(d.x, d.y);
        ctx.lineTo(d.x + dx * d.len, d.y + d.len);
      }
      ctx.stroke();
    };

    if (prefersReducedMotion()) {
      draw(slant());
      return () => ro.disconnect();
    }

    let raf = 0;
    const tick = () => {
      const dx = slant();
      for (const d of drops) {
        d.y += d.speed;
        d.x += dx * d.speed;
        if (d.y > height + d.len) {
          d.y = -d.len - Math.random() * 40;
          d.x = Math.random() * (width + 80) - 40;
        }
        if (d.x > width + 40) d.x -= width + 80;
        if (d.x < -40) d.x += width + 80;
      }
      draw(dx);
      raf = requestAnimationFrame(tick);
    };
    // A hidden tab needs no rain; rAF already pauses, this also skips work.
    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("visibilitychange", onVisibility);
      ro.disconnect();
    };
  }, [map, density, dark, weather.condition, weather.windFromDeg, weather.windKmh]);

  if (density === 0) return null;
  return <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />;
}

/** A soft veil that thickens as visibility drops below 2 km. */
function FogVeil({ weather }: { weather: WeatherNow }) {
  const dark = useThemeStore((s) => s.resolved === "dark");
  const wet = weather.condition === "heavy-rain" || weather.condition === "thunderstorm";
  const fog = Math.max(0, Math.min(1, (2000 - weather.visibilityM) / 1800));
  if (fog === 0 && !wet) return null;
  const veil = dark ? "150, 160, 175" : "220, 224, 230";
  const opacity = Math.max(fog * 0.55, wet ? 0.1 : 0);
  return (
    <div
      className="weather-fog absolute -inset-[10%]"
      style={{
        opacity,
        // A hint of softening sells the fog; kept under 1 px so road
        // colours and markers stay legible through it.
        backdropFilter: fog > 0 ? `blur(${(fog * 0.8).toFixed(2)}px)` : undefined,
        background: `radial-gradient(ellipse at 30% 40%, rgba(${veil}, 0.9), transparent 60%),
          radial-gradient(ellipse at 75% 65%, rgba(${veil}, 0.8), transparent 55%),
          rgba(${veil}, 0.35)`,
      }}
    />
  );
}

/**
 * A rare double flash, 6–14 s apart: far under WCAG 2.3.1's three flashes a
 * second, and dimmed rather than white-out. Skipped under reduced motion.
 */
function Lightning() {
  const [flash, setFlash] = useState(0);
  useEffect(() => {
    if (prefersReducedMotion()) return;
    const timers: number[] = [];
    const at = (ms: number, fn: () => void) => timers.push(window.setTimeout(fn, ms));
    const schedule = () =>
      at(6000 + Math.random() * 8000, () => {
        setFlash(0.28);
        at(90, () => setFlash(0));
        at(260, () => setFlash(0.14));
        at(330, () => setFlash(0));
        schedule();
      });
    schedule();
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, []);
  return <div className="absolute inset-0 bg-white transition-opacity duration-75" style={{ opacity: flash }} />;
}
