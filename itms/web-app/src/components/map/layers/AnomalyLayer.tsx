import { useEffect, useRef } from "react";
import { prefersReducedMotion } from "@/utils/motion";
import type { GeoJSONSource, MapMouseEvent } from "maplibre-gl";
import type { Feature, FeatureCollection, LineString, Point } from "geojson";
import { useMapInstance } from "@/components/map/MapContext";
import { useIncidentStore } from "@/store/incidentStore";
import { useMapStore } from "@/store/mapStore";
import { edgeById } from "@/data/network";
import { ANOMALY_SEVERITY_COLOR } from "@/components/map/mapColors";
import { pointAlongPath } from "@/utils/geo";

const EDGE_SRC = "anomaly-edges";
const MARK_SRC = "anomaly-marks";
const EDGE_LINE = "anomaly-edge-line";
const EDGE_GLOW = "anomaly-edge-glow";
const MARK_RING = "anomaly-mark-ring";
const MARK_DOT = "anomaly-mark-dot";

/**
 * Operator- and detector-created anomalies. Visually distinct from
 * IncidentLayer's dots: a highlighted stretch of the affected edge plus a
 * diamond-ish marker, coloured by severity, dimmed once terminal. Click
 * selects the anomaly (cross-workspace sync).
 */
export function AnomalyLayer({ visible }: { visible: boolean }) {
  const map = useMapInstance();
  const anomalies = useIncidentStore((s) => s.anomalies);
  const selectedId = useIncidentStore((s) => s.selectedAnomalyId);
  const selectAnomaly = useIncidentStore((s) => s.selectAnomaly);
  const focusOn = useMapStore((s) => s.focusOn);
  const raf = useRef<number>(0);

  useEffect(() => {
    if (!map.getSource(EDGE_SRC)) {
      const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
      map.addSource(EDGE_SRC, { type: "geojson", data: empty });
      map.addSource(MARK_SRC, { type: "geojson", data: empty });

      map.addLayer({
        id: EDGE_GLOW,
        type: "line",
        source: EDGE_SRC,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 12, 8, 17, 22],
          "line-opacity": ["case", ["get", "terminal"], 0.06, 0.18],
          "line-blur": 4,
        },
      });
      map.addLayer({
        id: EDGE_LINE,
        type: "line",
        source: EDGE_SRC,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["get", "color"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 12, 2.5, 17, 6],
          "line-opacity": ["case", ["get", "terminal"], 0.25, 0.9],
          "line-dasharray": [1.5, 1],
        },
      });
      map.addLayer({
        id: MARK_RING,
        type: "circle",
        source: MARK_SRC,
        paint: {
          "circle-radius": 11,
          "circle-color": ["get", "color"],
          "circle-opacity": 0,
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-width": ["case", ["get", "selected"], 3, 1.5],
          "circle-stroke-opacity": ["case", ["get", "terminal"], 0.3, 0.9],
        },
      });
      map.addLayer({
        id: MARK_DOT,
        type: "circle",
        source: MARK_SRC,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 4.5, 17, 8],
          "circle-color": ["get", "color"],
          "circle-opacity": ["case", ["get", "terminal"], 0.4, 1],
          "circle-stroke-color": "#0a0e14",
          "circle-stroke-width": 1.5,
        },
      });
    }

    const onClick = (e: MapMouseEvent) => {
      const hit = map.queryRenderedFeatures(e.point, { layers: [MARK_DOT] })[0];
      const props = hit?.properties as { id: string; lng: number; lat: number } | undefined;
      if (props) {
        selectAnomaly(props.id);
        focusOn({ latitude: props.lat, longitude: props.lng }, 16.5);
      }
    };
    const onEnter = () => (map.getCanvas().style.cursor = "pointer");
    const onLeave = () => (map.getCanvas().style.cursor = "");
    map.on("click", MARK_DOT, onClick);
    map.on("mouseenter", MARK_DOT, onEnter);
    map.on("mouseleave", MARK_DOT, onLeave);

    const start = performance.now();
    const pulse = () => {
      if (map.getLayer(MARK_RING)) {
        const phase = prefersReducedMotion() ? 0 : ((performance.now() - start) % 1600) / 1600;
        map.setPaintProperty(MARK_RING, "circle-radius", 10 + phase * 22);
        map.setPaintProperty(MARK_RING, "circle-stroke-opacity", 0.6 * (1 - phase));
      }
      raf.current = requestAnimationFrame(pulse);
    };
    raf.current = requestAnimationFrame(pulse);

    return () => {
      cancelAnimationFrame(raf.current);
      map.off("click", MARK_DOT, onClick);
      map.off("mouseenter", MARK_DOT, onEnter);
      map.off("mouseleave", MARK_DOT, onLeave);
      for (const id of [MARK_DOT, MARK_RING, EDGE_LINE, EDGE_GLOW])
        if (map.getLayer(id)) map.removeLayer(id);
      for (const id of [EDGE_SRC, MARK_SRC]) if (map.getSource(id)) map.removeSource(id);
    };
  }, [map, selectAnomaly, focusOn]);

  useEffect(() => {
    const v = visible ? "visible" : "none";
    for (const id of [MARK_DOT, MARK_RING, EDGE_LINE, EDGE_GLOW])
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", v);
  }, [map, visible]);

  useEffect(() => {
    const edgeSrc = map.getSource(EDGE_SRC) as GeoJSONSource | undefined;
    const markSrc = map.getSource(MARK_SRC) as GeoJSONSource | undefined;
    if (!edgeSrc || !markSrc) return;

    const edgeFeatures: Feature<LineString>[] = [];
    const markFeatures: Feature<Point>[] = [];

    for (const a of anomalies) {
      const edge = edgeById.get(a.edgeId);
      if (!edge) continue;
      const color = ANOMALY_SEVERITY_COLOR[a.severity] ?? ANOMALY_SEVERITY_COLOR.medium;
      const terminal = a.status !== "active";

      edgeFeatures.push({
        type: "Feature",
        properties: { id: a.id, color, terminal },
        geometry: { type: "LineString", coordinates: edge.path },
      });

      // marker at the affected edge's midpoint
      const p = pointAlongPath(edge.path, edge.cum, edge.lengthM * 0.5);
      markFeatures.push({
        type: "Feature",
        properties: {
          id: a.id,
          color,
          terminal,
          selected: a.id === selectedId,
          lng: p.lng,
          lat: p.lat,
        },
        geometry: { type: "Point", coordinates: [p.lng, p.lat] },
      });
    }

    edgeSrc.setData({ type: "FeatureCollection", features: edgeFeatures });
    markSrc.setData({ type: "FeatureCollection", features: markFeatures });
  }, [map, anomalies, selectedId]);

  return null;
}
