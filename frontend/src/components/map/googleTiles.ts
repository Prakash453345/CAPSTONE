import type { ResolvedTheme } from "@/store/themeStore";

/**
 * Google Maps basemap through the Map Tiles API (2D roadmap tiles).
 *
 * The tiles are ordinary raster images, so MapLibre keeps rendering every
 * TRAFFIX overlay on top of them unchanged. Google's policy for third-party
 * renderers applies: the "Google Maps" mark and the data copyright from the
 * viewport endpoint must stay visible (see GoogleAttribution in TrafficMap).
 *
 * Billing: 2D tiles have a free monthly allowance of 100,000 tile requests;
 * the key needs a Google Cloud project with billing enabled and the
 * "Map Tiles API" turned on.
 */

const KEY: string | undefined = import.meta.env.VITE_GOOGLE_MAPS_API_KEY;
const API = "https://tile.googleapis.com";

export const hasGoogleKey = Boolean(KEY && KEY !== "your_api_key_here");

/** Google Maps' night palette: neutral greys, dark navy water, muted parks. */
const DARK_STYLES = [
  { elementType: "geometry", stylers: [{ color: "#1f2124" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#9aa0a6" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#1f2124" }] },
  { elementType: "labels.icon", stylers: [{ saturation: -60 }, { lightness: -20 }] },
  { featureType: "administrative", elementType: "geometry", stylers: [{ color: "#3c4043" }] },
  { featureType: "landscape.man_made", elementType: "geometry", stylers: [{ color: "#232528" }] },
  { featureType: "poi", elementType: "geometry", stylers: [{ color: "#26292d" }] },
  { featureType: "poi.park", elementType: "geometry", stylers: [{ color: "#1d2b23" }] },
  { featureType: "poi.park", elementType: "labels.text.fill", stylers: [{ color: "#6b9a76" }] },
  { featureType: "road", elementType: "geometry.fill", stylers: [{ color: "#3c4043" }] },
  { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#1f2124" }] },
  { featureType: "road", elementType: "labels.text.fill", stylers: [{ color: "#bdc1c6" }] },
  { featureType: "road.arterial", elementType: "geometry.fill", stylers: [{ color: "#46494d" }] },
  { featureType: "road.highway", elementType: "geometry.fill", stylers: [{ color: "#5f6368" }] },
  { featureType: "road.highway", elementType: "labels.text.fill", stylers: [{ color: "#e8eaed" }] },
  { featureType: "transit", elementType: "geometry", stylers: [{ color: "#2f3336" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#0e1726" }] },
  { featureType: "water", elementType: "labels.text.fill", stylers: [{ color: "#4e6d70" }] },
];

interface Session {
  session: string;
  /** Unix seconds. */
  expiry: number;
}

const cacheKey = (theme: ResolvedTheme) => `traffix.gtiles.${theme}`;
const inflight = new Map<ResolvedTheme, Promise<Session>>();

async function createSession(theme: ResolvedTheme): Promise<Session> {
  const res = await fetch(`${API}/v1/createSession?key=${KEY}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mapType: "roadmap",
      language: "en-US",
      region: "IN",
      scale: "scaleFactor2x",
      highDpi: true,
      ...(theme === "dark" ? { styles: DARK_STYLES } : {}),
    }),
  });
  if (!res.ok) {
    throw new Error(`Map Tiles createSession ${res.status}: ${await res.text()}`);
  }
  const body = (await res.json()) as { session: string; expiry: string | number };
  return { session: body.session, expiry: Number(body.expiry) };
}

/** A session token for this theme, reused until a day before it expires
 *  (they last about two weeks), so reloads don't mint new sessions. */
export function googleSession(theme: ResolvedTheme): Promise<Session> {
  try {
    const cached = JSON.parse(localStorage.getItem(cacheKey(theme)) ?? "null") as Session | null;
    if (cached && cached.expiry - Date.now() / 1000 > 86_400) return Promise.resolve(cached);
  } catch {
    // unreadable cache: mint a new session
  }
  let pending = inflight.get(theme);
  if (!pending) {
    pending = createSession(theme)
      .then((s) => {
        try {
          localStorage.setItem(cacheKey(theme), JSON.stringify(s));
        } catch {
          // fine: the session just isn't reused next load
        }
        return s;
      })
      .finally(() => inflight.delete(theme));
    inflight.set(theme, pending);
  }
  return pending;
}

export function forgetGoogleSession(theme: ResolvedTheme) {
  try {
    localStorage.removeItem(cacheKey(theme));
  } catch {
    // nothing cached
  }
}

export function googleTileUrl(session: string): string {
  return `${API}/v1/2dtiles/{z}/{x}/{y}?session=${session}&key=${KEY}`;
}

/** The data copyright Google requires for the area on screen. */
export async function googleCopyright(
  session: string,
  zoom: number,
  bounds: { north: number; south: number; east: number; west: number },
): Promise<string> {
  const q = new URLSearchParams({
    session,
    key: KEY ?? "",
    zoom: String(Math.round(zoom)),
    north: bounds.north.toFixed(5),
    south: bounds.south.toFixed(5),
    east: bounds.east.toFixed(5),
    west: bounds.west.toFixed(5),
  });
  const res = await fetch(`${API}/tile/v1/viewport?${q}`);
  if (!res.ok) throw new Error(`Map Tiles viewport ${res.status}`);
  const body = (await res.json()) as { copyright?: string };
  return body.copyright ?? "Map data ©Google";
}
