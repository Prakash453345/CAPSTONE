import type { LatLng } from "@/types";

/** The cities the console shows. Both by default; `VITE_CITY` narrows it to
 *  one ("vijayawada" or "amaravati", or a comma list). Each city's road
 *  network is bundled in src/data/network.ts; this is what the UI says about it. */
export type CityId = "vijayawada" | "amaravati";

export interface City {
  id: CityId;
  name: string;
  /** Where the map opens when it is the only city (`VITE_MAP_CENTER` overrides it). */
  center: LatLng;
  /** One line under the city's name in the globe transition. */
  blurb: string;
}

/** In display order: the first shown city is the "home" one (globe intro, weather). */
export const CITIES: City[] = [
  {
    id: "vijayawada",
    name: "Vijayawada",
    center: { latitude: 16.5062, longitude: 80.6335 },
    blurb: "20 signalised junctions · pilot deployment",
  },
  {
    id: "amaravati",
    name: "Amaravati",
    center: { latitude: 16.514, longitude: 80.4945 },
    blurb: "121 signalised junctions · capital region",
  },
];

export const cityById = new Map(CITIES.map((c) => [c.id, c]));

/** The cities a `VITE_CITY` value selects: unset, empty, "all", "both" or
 *  nothing recognisable means every city. */
export function citiesFor(setting: string | undefined): City[] {
  const raw = (setting ?? "").trim().toLowerCase();
  if (!raw || raw === "all" || raw === "both") return CITIES;
  const wanted = new Set(raw.split(",").map((s) => s.trim()));
  const picked = CITIES.filter((c) => wanted.has(c.id));
  return picked.length ? picked : CITIES;
}

export const SHOWN_CITIES: City[] = citiesFor(import.meta.env.VITE_CITY as string | undefined);
export const HOME_CITY: City = SHOWN_CITIES[0];
/** "Vijayawada · Amaravati", or the one city's name. */
export const CITIES_LABEL = SHOWN_CITIES.map((c) => c.name).join(" · ");

/** "16.5062° N · 80.6335° E" */
export function formatLatLng({ latitude, longitude }: LatLng): string {
  const ns = latitude >= 0 ? "N" : "S";
  const ew = longitude >= 0 ? "E" : "W";
  return `${Math.abs(latitude).toFixed(4)}° ${ns} · ${Math.abs(longitude).toFixed(4)}° ${ew}`;
}
