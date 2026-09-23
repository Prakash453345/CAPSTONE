import { useEffect, useRef } from "react";
import type { GeoJSONSource, MapMouseEvent } from "maplibre-gl";
import type { FeatureCollection, Point } from "geojson";
import { useMapInstance } from "@/components/map/MapContext";
import { isMapAlive } from "@/components/map/mapSafe";
import { useIncidentStore } from "@/store/incidentStore";
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
  const raf = useRef(0);

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
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 6, 17, 16],
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
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 3.5, 17, 7],
          "circle-color": ["get", "color"],
          "circle-stroke-color": [
            "case",
            ["get", "faulted"], FAULT_COLOR,
            ["get", "preempted"], PREEMPT_COLOR,
            ["get", "selected"], "#ffffff",
            "#0a0e14",
          ],
          "circle-stroke-width": [
            "case",
            ["any", ["get", "faulted"], ["get", "preempted"], ["get", "selected"]], 2, 1,
          ],
        },
      });
    }

    const start = performance.now();
    const pulse = () => {
      if (!isMapAlive(map)) return;
      if (map.getLayer(PREEMPT_RING)) {
        const phase = ((performance.now() - start) % 1200) / 1200;
        map.setPaintProperty(PREEMPT_RING, "circle-radius", 10 + phase * 16);
        map.setPaintProperty(PREEMPT_RING, "circle-stroke-opacity", 0.9 * (1 - phase));
      }
      if (map.getLayer(FAULT_RING)) {
        // A sharp on/off blink (not a smooth expand-fade like the corridor
        // ring above) reads as "alert", not "calm coordination" -- faults are
        // more urgent than a routine preemption.
        const on = Math.floor((performance.now() - start) / 350) % 2 === 0;
        map.setPaintProperty(FAULT_RING, "circle-stroke-opacity", on ? 0.9 : 0.15);
      }
      raf.current = requestAnimationFrame(pulse);
    };
    raf.current = requestAnimationFrame(pulse);

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
      cancelAnimationFrame(raf.current);
      if (!isMapAlive(map)) return;
      map.off("click", DOT, onClick);
      map.off("mouseenter", DOT, onEnter);
      map.off("mouseleave", DOT, onLeave);
      for (const id of [DOT, FAULT_RING, PREEMPT_RING, HALO])
        if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(SRC)) map.removeSource(SRC);
    };
  }, [map, selectIntersection]);

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
  }, [map, intersections, selectedId]);

  return null;
}
