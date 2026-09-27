import { create } from "zustand";
import { DEMO_WEATHER, fetchWeather, type WeatherNow } from "@/services/weather/weather";

export type DemoWeather = keyof typeof DEMO_WEATHER;

interface WeatherState {
  live: WeatherNow | null;
  status: "idle" | "loading" | "ok" | "error";
  /** A presenter-chosen preset that replaces live weather; null = live. */
  demo: DemoWeather | null;
  setDemo: (demo: DemoWeather | null) => void;
  refresh: (latitude: number, longitude: number) => Promise<void>;
}

export const useWeatherStore = create<WeatherState>((set, get) => ({
  live: null,
  status: "idle",
  demo: null,
  setDemo: (demo) => set({ demo }),
  refresh: async (latitude, longitude) => {
    if (get().status === "loading") return;
    set({ status: get().live ? "ok" : "loading" });
    try {
      set({ live: await fetchWeather(latitude, longitude), status: "ok" });
    } catch {
      // Keep the last good reading; the chip shows it as possibly stale.
      set({ status: "error" });
    }
  },
}));

/** The weather the map should show: the demo preset if one is chosen. */
export function useEffectiveWeather(): WeatherNow | null {
  return useWeatherStore((s) => (s.demo ? DEMO_WEATHER[s.demo] : s.live));
}
