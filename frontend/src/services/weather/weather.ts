/**
 * Live weather for the corridor from Open-Meteo: free, no key, CC BY 4.0
 * (credit shown in the map attribution). Non-commercial use allows 10,000
 * calls a day; the console polls every 10 minutes.
 * https://open-meteo.com/en/terms
 */

export type WeatherCondition =
  | "clear"
  | "cloudy"
  | "fog"
  | "drizzle"
  | "rain"
  | "heavy-rain"
  | "thunderstorm";

export interface WeatherNow {
  condition: WeatherCondition;
  temperatureC: number;
  /** Rain rate in mm/h (Open-Meteo reports mm per 15-minute interval). */
  rainMmPerH: number;
  /** Direction the wind blows FROM, degrees clockwise from north. */
  windFromDeg: number;
  windKmh: number;
  visibilityM: number;
  cloudCover: number;
  isDay: boolean;
  /** Next hours, soonest first. */
  outlook: Array<{ time: string; rainChance: number; condition: WeatherCondition }>;
}

/**
 * WMO weather interpretation codes (the table in Open-Meteo's docs) to the
 * handful of looks the map can draw. Measured rain upgrades a code: an
 * 8 mm/h "moderate rain" reading is drawn as heavy rain.
 */
export function classify(code: number, rainMmPerH = 0): WeatherCondition {
  if (code >= 95) return "thunderstorm";
  if (code === 45 || code === 48) return "fog";
  const rainy = (code >= 61 && code <= 67) || (code >= 80 && code <= 82);
  const drizzly = code >= 51 && code <= 57;
  if (rainy || drizzly || rainMmPerH > 0) {
    if (rainMmPerH >= 7.5 || code === 65 || code === 67 || code === 82) return "heavy-rain";
    if (drizzly && rainMmPerH < 1) return "drizzle";
    return rainMmPerH > 0 && rainMmPerH < 0.5 && !rainy ? "drizzle" : "rain";
  }
  if (code >= 2) return "cloudy";
  return "clear";
}

/** Drops per frame the overlay draws for a condition, 0 when dry. */
export function rainDensity(w: Pick<WeatherNow, "condition" | "rainMmPerH">): number {
  switch (w.condition) {
    case "drizzle":
      return 90;
    case "rain":
      return Math.min(260, 140 + w.rainMmPerH * 15);
    case "heavy-rain":
    case "thunderstorm":
      return 340;
    default:
      return 0;
  }
}

/** What the weather means for road traffic, in one line; null when nothing. */
export function trafficAdvice(w: WeatherNow): string | null {
  switch (w.condition) {
    case "thunderstorm":
      return "Storm: expect slower traffic and possible waterlogging";
    case "heavy-rain":
      return "Heavy rain: expect slower traffic and longer stops";
    case "rain":
      return "Rain: roads may be slower than usual";
    case "fog":
      return "Low visibility: drivers will keep longer gaps";
    default:
      return w.visibilityM < 2000 ? "Low visibility: drivers will keep longer gaps" : null;
  }
}

interface OpenMeteoResponse {
  current: {
    time: string;
    interval: number;
    temperature_2m: number;
    precipitation: number;
    weather_code: number;
    cloud_cover: number;
    wind_speed_10m: number;
    wind_direction_10m: number;
    visibility: number;
    is_day: number;
  };
  hourly: { time: string[]; precipitation_probability: number[]; weather_code: number[] };
}

export async function fetchWeather(
  latitude: number,
  longitude: number,
  signal?: AbortSignal,
): Promise<WeatherNow> {
  const q = new URLSearchParams({
    latitude: latitude.toFixed(4),
    longitude: longitude.toFixed(4),
    current:
      "temperature_2m,precipitation,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m,visibility,is_day",
    hourly: "precipitation_probability,weather_code",
    forecast_hours: "5",
    timezone: "auto",
  });
  const res = await fetch(`https://api.open-meteo.com/v1/forecast?${q}`, { signal });
  if (!res.ok) throw new Error(`Open-Meteo ${res.status}`);
  const body = (await res.json()) as OpenMeteoResponse;
  const c = body.current;
  const rainMmPerH = c.precipitation * (3600 / (c.interval || 900));
  const nowHour = c.time.slice(0, 13);
  const outlook = body.hourly.time
    .map((time, i) => ({
      time,
      rainChance: body.hourly.precipitation_probability[i] ?? 0,
      condition: classify(body.hourly.weather_code[i] ?? 0),
    }))
    .filter((h) => h.time.slice(0, 13) > nowHour)
    .slice(0, 3);
  return {
    condition: classify(c.weather_code, rainMmPerH),
    temperatureC: c.temperature_2m,
    rainMmPerH,
    windFromDeg: c.wind_direction_10m,
    windKmh: c.wind_speed_10m,
    visibilityM: c.visibility,
    cloudCover: c.cloud_cover,
    isDay: c.is_day === 1,
    outlook,
  };
}

/** Demo presets for presentations: a storm on a sunny day. */
export const DEMO_WEATHER: Record<Exclude<WeatherCondition, "cloudy" | "drizzle">, WeatherNow> = {
  clear: demo("clear", 31, 0, 8000),
  rain: demo("rain", 26, 4, 6000),
  "heavy-rain": demo("heavy-rain", 24, 14, 3000),
  thunderstorm: demo("thunderstorm", 24, 22, 2500),
  fog: demo("fog", 21, 0, 400),
};

function demo(condition: WeatherCondition, t: number, rain: number, vis: number): WeatherNow {
  return {
    condition,
    temperatureC: t,
    rainMmPerH: rain,
    windFromDeg: 250,
    windKmh: condition === "thunderstorm" ? 38 : 14,
    visibilityM: vis,
    cloudCover: condition === "clear" ? 10 : 95,
    isDay: true,
    outlook: [],
  };
}
