import { useEffect, useMemo, useRef } from "react";
import { prefersReducedMotion } from "@/utils/motion";
import type { GeoJSONSource, MapMouseEvent } from "maplibre-gl";
import type { FeatureCollection, Point } from "geojson";
import { useMapInstance } from "@/components/map/MapContext";
import { isMapAlive } from "@/components/map/mapSafe";
import { useIncidentStore } from "@/store/incidentStore";
import { useFrameLoop } from "@/components/map/useFrameLoop";
import { useChangeGuard } from "@/components/map/useChangeGuard";
import { CORRIDOR_ACCENT_COLOR, SIGNAL_COLOR } from "@/components/map/mapColors";

const SRC = "signals";
const HALO = "signals-halo";
const DOT = "signals-dot";
const PREEMPT_RING = "signals-preempt-ring";
const FAULT_RING = "signals-fault-ring";

/** Cyan — the same accent `emergencyGeo.ts` uses for a mission's green
 *  corridor, so "this junction is coordinating for an emergency vehicle"
 *  reads as one consistent colour language across the map, distinct from
 *  ordinary green/red phase colour. */
const PREEMPT_COLOR = CORRIDOR_ACCENT_COLOR;
/** Amber, not `SIGNAL_COLOR.red` — a fault is a distinct condition from
 *  "just not under control right now" (which already renders red), so it
 *  needs its own colour, not a louder version of an existing one. */
const FAULT_COLOR = "#ffa726";

/**
 * Signalised junctions, coloured by an approximation, not a real per-approach
 * phase reading (see the `Colour is approximate` legend note this layer's
 * data ultimately feeds): "green" means a `SignalChanged` for this junction
 * arrived recently (the arbiter is actively commanding it), "red" means it
 * hasn't — Sim mode's fixed-time cycle is the only place green/yellow/red
 * reflects an actual timed phase. A junction currently held by the green
 * corridor (`Intersection.preempted`) gets a pulsing cyan ring on top, and one
 * in a failsafe state (`Intersection.fault`, Phase 10) gets a blinking amber
 * ring — visually distinct from each other and from ordinary green/red, so an
 * operator can tell "coordinating for an ambulance" from "faulted" from
 * "just idle" at a glance. Click selects the intersection.
 */
export function SignalLayer({ visible }: { visible: boolean }) {
  const map = useMapInstance();
  const intersections = useIncidentStore((s) => s.intersections);
  const selectIntersection = useIncidentStore((s) => s.selectIntersection);
  const selectedId = useIncidentStore((s) => s.selectedIntersectionId);
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
        id: HALO,
        type: "circle",
        source: SRC,
        paint: {
          // Quiet when zoomed out: a halo on every one of 120+ junctions is noise.
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 13.5, 0, 15, 8, 17, 16],
          "circle-color": ["get", "color"],
          "circle-opacity": 0.18,
        },
      });
      map.addLayer({
        id: PREEMPT_RING,
        type: "circle",
        source: SRC,
        filter: ["get", "preempted"],
        paint: {
          "circle-radius": 12,
          "circle-color": "transparent",
          "circle-stroke-color": PREEMPT_COLOR,
          "circle-stroke-width": 2,
          "circle-stroke-opacity": 0.85,
        },
      });
      map.addLayer({
        id: FAULT_RING,
        type: "circle",
        source: SRC,
        filter: ["get", "faulted"],
        paint: {
          "circle-radius": 10,
          "circle-color": "transparent",
          "circle-stroke-color": FAULT_COLOR,
          "circle-stroke-width": 2.5,
          "circle-stroke-opacity": 0.9,
        },
      });
      map.addLayer({
        id: DOT,
        type: "circle",
        source: SRC,
        paint: {
          // Small and soft when zoomed out, full size and outlined up close.
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 2.2, 14, 3.2, 16, 5.5, 17.5, 7.5],
          "circle-color": ["get", "color"],
          "circle-opacity": ["interpolate", ["linear"], ["zoom"], 12, 0.6, 15, 1],
          "circle-stroke-color": [
            "case",
            ["get", "faulted"], FAULT_COLOR,
            ["get", "preempted"], PREEMPT_COLOR,
            ["get", "selected"], "#ffffff",
            "rgba(10, 14, 20, 0.6)",
          ],
          "circle-stroke-width": [
            "case",
            ["any", ["get", "faulted"], ["get", "preempted"], ["get", "selected"]],
            2,
            ["interpolate", ["linear"], ["zoom"], 13, 0, 15, 1],
          ],
        },
      });
    }

    const onClick = (e: MapMouseEvent) => {
      const hits = map.queryRenderedFeatures(e.point, { layers: [DOT] });
      const id = hits[0]?.properties?.id as string | undefined;
      if (id) selectIntersection(id);
    };
    const onEnter = () => (map.getCanvas().style.cursor = "pointer");
    const onLeave = () => (map.getCanvas().style.cursor = "");
    map.on("click", DOT, onClick);
    map.on("mouseenter", DOT, onEnter);
    map.on("mouseleave", DOT, onLeave);

    return () => {
      if (!isMapAlive(map)) return;
      map.off("click", DOT, onClick);
      map.off("mouseenter", DOT, onEnter);
      map.off("mouseleave", DOT, onLeave);
      for (const id of [DOT, FAULT_RING, PREEMPT_RING, HALO])
        if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SRC)) map.removeSource(SRC);
    };
  }, [map, selectIntersection]);

  // The rings only animate while a junction is held for an ambulance or has faulted.
  const needsPulse = useMemo(() => intersections.some((i) => i.preempted || i.fault != null), [intersections]);
  useFrameLoop(needsPulse, () => {
    if (!isMapAlive(map)) return;
    const elapsed = performance.now() - startedAt.current;
    if (map.getLayer(PREEMPT_RING)) {
      const phase = prefersReducedMotion() ? 0 : (elapsed % 1200) / 1200;
      map.setPaintProperty(PREEMPT_RING, "circle-radius", 10 + phase * 16);
      map.setPaintProperty(PREEMPT_RING, "circle-stroke-opacity", 0.9 * (1 - phase));
    }
    if (map.getLayer(FAULT_RING)) {
      // A sharp on/off blink (not a smooth expand-fade like the corridor ring)
      // reads as "alert", not "calm coordination": faults are more urgent.
      const on = prefersReducedMotion() || Math.floor(elapsed / 350) % 2 === 0;
      map.setPaintProperty(FAULT_RING, "circle-stroke-opacity", on ? 0.9 : 0.15);
    }
  });

  useEffect(() => {
    if (!isMapAlive(map)) return;
    const v = visible ? "visible" : "none";
    for (const id of [DOT, FAULT_RING, PREEMPT_RING, HALO])
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", v);
  }, [map, visible]);

  useEffect(() => {
    if (!isMapAlive(map)) return;
    const src = map.getSource(SRC) as GeoJSONSource | undefined;
    if (!src) return;
    const signature =
      `${selectedId}|` +
      intersections.map((i) => `${i.id}${i.signalState[0]}${i.preempted ? 1 : 0}${i.fault ? 1 : 0}`).join(",");
    if (!changed(signature)) return;
    const data: FeatureCollection<Point> = {
      type: "FeatureCollection",
      features: intersections.map((it) => ({
        type: "Feature",
        id: it.id,
        properties: {
          id: it.id,
          name: it.name,
          color: SIGNAL_COLOR[it.signalState],
          selected: it.id === selectedId,
          preempted: it.preempted ?? false,
          faulted: it.fault != null,
        },
        geometry: { type: "Point", coordinates: [it.longitude, it.latitude] },
      })),
    };
    src.setData(data);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `changed` is stable per mount
  }, [map, intersections, selectedId]);

  return null;
}
