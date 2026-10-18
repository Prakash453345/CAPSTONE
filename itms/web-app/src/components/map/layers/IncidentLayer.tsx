import { useEffect, useRef, useMemo } from "react";
import { prefersReducedMotion } from "@/utils/motion";
import type { GeoJSONSource, MapMouseEvent } from "maplibre-gl";
import type { FeatureCollection, Point } from "geojson";
import { useMapInstance } from "@/components/map/MapContext";
import { useFrameLoop } from "@/components/map/useFrameLoop";
import { useChangeGuard } from "@/components/map/useChangeGuard";
import { isMapAlive } from "@/components/map/mapSafe";
import { useIncidentStore } from "@/store/incidentStore";
import { useMapStore } from "@/store/mapStore";
import { SEVERITY_COLOR } from "@/components/map/mapColors";

const SRC = "incidents";
const PULSE = "incidents-pulse";
const DOT = "incidents-dot";

/** Incident markers with a pulsing affected-area ring. Click selects + focuses. */
export function IncidentLayer({ visible }: { visible: boolean }) {
  const map = useMapInstance();
  const incidents = useIncidentStore((s) => s.incidents);
  const selectedId = useIncidentStore((s) => s.selectedIncidentId);
  const selectIncident = useIncidentStore((s) => s.selectIncident);
  const focusOn = useMapStore((s) => s.focusOn);
  const startedAt = useRef(performance.now());
  const changed = useChangeGuard();

  useEffect(() => {
    if (!map.getSource(SRC)) {
      const empty: FeatureCollection = {
        type: "FeatureCollection",
        features: [],
      };
      map.addSource(SRC, { type: "geojson", data: empty });

      map.addLayer({
        id: PULSE,
        type: "circle",
        source: SRC,
        filter: ["!=", ["get", "status"], "resolved"],
        paint: {
          "circle-radius": 10,
          "circle-color": ["get", "color"],
          "circle-opacity": 0.25,
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-width": 1,
          "circle-stroke-opacity": 0.5,
        },
      });

      map.addLayer({
        id: DOT,
        type: "circle",
        source: SRC,
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            12,
            5.5,
            17,
            9,
          ],
          "circle-color": [
            "case",
            ["==", ["get", "status"], "candidate"],
            "#0a0e14",
            ["get", "color"],
          ],
          "circle-stroke-color": [
            "case",
            ["get", "selected"],
            "#ffffff",
            ["get", "color"],
          ],
          "circle-stroke-width": [
            "case",
            ["get", "selected"],
            3,
            ["==", ["get", "status"], "candidate"],
            2,
            1.5,
          ],
        },
      });
    }

    const onClick = (e: MapMouseEvent) => {
      const hits = map.queryRenderedFeatures(e.point, { layers: [DOT] });
      const props = hits[0]?.properties as
        | { id: string; lng: number; lat: number }
        | undefined;
      if (props) {
        selectIncident(props.id);
        focusOn({ latitude: props.lat, longitude: props.lng }, 16.5);
      }
    };
    const onEnter = () => (map.getCanvas().style.cursor = "pointer");
    const onLeave = () => (map.getCanvas().style.cursor = "");
    map.on("click", DOT, onClick);
    map.on("mouseenter", DOT, onEnter);
    map.on("mouseleave", DOT, onLeave);

    return () => {
      map.off("click", DOT, onClick);
      map.off("mouseenter", DOT, onEnter);
      map.off("mouseleave", DOT, onLeave);
      for (const id of [DOT, PULSE]) if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SRC)) map.removeSource(SRC);
    };
  }, [map, selectIncident, focusOn]);

  const needsPulse = useMemo(() => incidents.some((i) => i.status !== "resolved"), [incidents]);
  useFrameLoop(needsPulse, () => {
    if (!isMapAlive(map) || !map.getLayer(PULSE)) return;
    const phase = prefersReducedMotion() ? 0 : ((performance.now() - startedAt.current) % 1800) / 1800;
    map.setPaintProperty(PULSE, "circle-radius", 10 + phase * 34);
    map.setPaintProperty(PULSE, "circle-opacity", 0.28 * (1 - phase));
    map.setPaintProperty(PULSE, "circle-stroke-opacity", 0.5 * (1 - phase));
  });

  useEffect(() => {
    const v = visible ? "visible" : "none";
    for (const id of [DOT, PULSE])
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", v);
  }, [map, visible]);

  useEffect(() => {
    const src = map.getSource(SRC) as GeoJSONSource | undefined;
    if (!src) return;
    const signature = `${selectedId}|` + incidents.map((i) => `${i.id}${i.status}${i.severity}${i.latitude}${i.longitude}`).join(",");
    if (!changed(signature)) return;
    const data: FeatureCollection<Point> = {
      type: "FeatureCollection",
      features: incidents.map((inc) => ({
        type: "Feature",
        id: inc.id,
        properties: {
          id: inc.id,
          status: inc.status,
          color: inc.severityKnown === false ? "#b4a3ef" : SEVERITY_COLOR[inc.severity],
          selected: inc.id === selectedId,
          lng: inc.longitude,
          lat: inc.latitude,
        },
        geometry: { type: "Point", coordinates: [inc.longitude, inc.latitude] },
      })),
    };
    src.setData(data);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `changed` is stable per mount
  }, [map, incidents, selectedId]);

  return null;
}
