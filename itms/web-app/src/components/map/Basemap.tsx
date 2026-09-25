import { useEffect, useState } from "react";
import { useMapInstance } from "@/components/map/MapContext";
import { setBasemap } from "@/components/map/mapStyle";
import { OSM_PREFIX, googleLookBasemap } from "@/components/map/googleLookStyle";
import {
  forgetGoogleSession,
  googleCopyright,
  googleSession,
  googleTileUrl,
  hasGoogleKey,
} from "@/components/map/googleTiles";
import { useThemeStore } from "@/store/themeStore";

/**
 * Owns the basemap: Google Maps tiles when VITE_GOOGLE_MAPS_API_KEY is set,
 * otherwise (or if Google refuses the key) OpenFreeMap vector data recoloured
 * to Google's palette. Follows the light / dark theme, and renders the
 * attribution Google's terms require.
 */
export function Basemap() {
  const map = useMapInstance();
  const theme = useThemeStore((s) => s.resolved);
  const [googleSessionId, setGoogleSessionId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const showOsm = () => {
      if (cancelled) return;
      setGoogleSessionId(null);
      googleLookBasemap(theme)
        .then((style) => !cancelled && setBasemap(map, theme, { provider: "osm", style }))
        .catch((err: unknown) => console.warn("Basemap unavailable; overlays still render.", err));
    };
    if (!hasGoogleKey) {
      showOsm();
      return () => {
        cancelled = true;
      };
    }
    googleSession(theme)
      .then(({ session }) => {
        if (cancelled) return;
        setGoogleSessionId(session);
        // Attribution is rendered by <GoogleAttribution>, per Google's terms.
        setBasemap(map, theme, { provider: "google", tiles: [googleTileUrl(session)] });
      })
      .catch((err: unknown) => {
        console.warn("Google Map Tiles unavailable, using the OpenFreeMap basemap.", err);
        forgetGoogleSession(theme);
        showOsm();
      });
    return () => {
      cancelled = true;
    };
  }, [map, theme]);

  // OpenFreeMap's POI layers name a few icons its sprite doesn't ship (atm,
  // office, gate…). Google hides those minor pins anyway, so stand in a blank
  // image rather than log a warning per tile. Overlay icons replace-on-add
  // (mapIcons.ts), so this can't shadow them.
  useEffect(() => {
    const blank = { width: 1, height: 1, data: new Uint8Array(4) };
    const fill = (e: { id: string }) => {
      if (!map.hasImage(e.id)) map.addImage(e.id, blank);
    };
    map.on("styleimagemissing", fill);
    return () => {
      map.off("styleimagemissing", fill);
    };
  }, [map]);

  // Like Google Maps, buildings stay flat footprints until the map is tilted.
  useEffect(() => {
    const sync = () => {
      if (!map.getLayer(BUILDINGS_3D)) return;
      map.setLayoutProperty(BUILDINGS_3D, "visibility", map.getPitch() > 20 ? "visible" : "none");
    };
    sync();
    map.on("pitchend", sync);
    map.on("styledata", sync);
    return () => {
      map.off("pitchend", sync);
      map.off("styledata", sync);
    };
  }, [map]);

  return googleSessionId ? <GoogleAttribution session={googleSessionId} /> : null;
}

const BUILDINGS_3D = OSM_PREFIX + "building-3d";

function GoogleAttribution({ session }: { session: string }) {
  const map = useMapInstance();
  const [copyright, setCopyright] = useState("Map data ©Google");

  useEffect(() => {
    let timer = 0;
    let cancelled = false;
    const refresh = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const b = map.getBounds();
        googleCopyright(session, map.getZoom(), {
          north: b.getNorth(),
          south: b.getSouth(),
          east: b.getEast(),
          west: b.getWest(),
        })
          .then((c) => !cancelled && setCopyright(c))
          .catch(() => undefined);
      }, 800);
    };
    refresh();
    map.on("moveend", refresh);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      map.off("moveend", refresh);
    };
  }, [map, session]);

  return (
    <>
      <div
        aria-label="Google Maps"
        className="pointer-events-none absolute bottom-2 left-1/2 z-[1] -translate-x-1/2 select-none text-[15px] font-medium tracking-tight text-[#5f6368] [text-shadow:0_0_2px_#fff,0_0_2px_#fff,0_0_3px_#fff] dark:text-[#e8eaed] dark:[text-shadow:0_0_2px_#000,0_0_3px_#000]"
      >
        Google Maps
      </div>
      <div className="pointer-events-none absolute bottom-0 right-0 z-[1] rounded-tl bg-surface/80 px-1.5 py-px text-[10px] text-muted-foreground">
        {copyright}
      </div>
    </>
  );
}
