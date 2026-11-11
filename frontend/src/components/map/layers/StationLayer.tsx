import { useEffect, useRef } from "react";
import { Marker } from "maplibre-gl";
import { useMapInstance } from "@/components/map/MapContext";
import { stations, STATION_LABEL } from "@/data/stations";

const POLICE = "#2f7bff";
const FIRE = "#ff5a1f";

/** Police and fire stations: a coloured disc with P / F and the station's name
 *  beside it. HTML markers rather than a symbol layer: those need the style's
 *  glyphs, which are not there until the basemap has loaded. */
export function StationLayer({ visible }: { visible: boolean }) {
  const map = useMapInstance();
  const markers = useRef<Marker[]>([]);

  useEffect(() => {
    markers.current = stations.map((s) => {
      const color = s.kind === "police" ? POLICE : FIRE;
      const el = document.createElement("div");
      el.title = `${s.name} · ${STATION_LABEL[s.kind]}${s.offRoadM > 100 ? ` · ${(s.offRoadM / 1000).toFixed(1)} km from the mapped roads` : ""}`;
      el.style.cssText = "display:flex;flex-direction:column;align-items:center;pointer-events:auto;";
      const disc = document.createElement("div");
      disc.textContent = s.kind === "police" ? "P" : "F";
      disc.style.cssText = `width:24px;height:24px;border-radius:50%;background:${color};color:#fff;font:700 12px/24px system-ui,sans-serif;text-align:center;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.45);`;
      const name = document.createElement("div");
      name.textContent = s.name;
      name.style.cssText = `margin-top:2px;max-width:110px;text-align:center;font:600 11px/1.2 system-ui,sans-serif;color:${color};text-shadow:0 0 3px #000,0 0 3px #000;`;
      el.append(disc, name);
      return new Marker({ element: el, anchor: "top", offset: [0, -12] }).setLngLat(s.at).addTo(map);
    });
    return () => {
      markers.current.forEach((m) => m.remove());
      markers.current = [];
    };
  }, [map]);

  useEffect(() => {
    markers.current.forEach((m) => {
      m.getElement().style.display = visible ? "" : "none";
    });
  }, [visible]);

  return null;
}
