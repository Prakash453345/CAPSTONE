import rawNetwork from "../../../scenarios/networks/vijayawada/vijayawada_corridor.geojson?raw";
import type { FeatureCollection } from "geojson";
import { cumulativeLengths, haversineMeters, type LngLat } from "@/utils/geo";
import { ROAD_NAMES } from "@/data/roadNames";

/** Geometry from the same checked-in network used by the SUMO exporter. */
const network = JSON.parse(rawNetwork) as FeatureCollection;
export interface RoadEdge {
  id: string;
  name: string | null;
  numLanes: number;
  speedLimitMps: number;
  path: LngLat[];
  cum: number[];
  lengthM: number;
}
export const roadEdges: RoadEdge[] = network.features.flatMap((f) => {
  if (f.geometry.type !== "LineString" || f.properties?.kind !== "edge")
    return [];
  const path = f.geometry.coordinates as LngLat[];
  const cum = cumulativeLengths(path);
  return [
    {
      id: String(f.properties.edge_id),
      name: (f.properties.name as string | null) ?? ROAD_NAMES[String(f.properties.edge_id)] ?? null,
      numLanes: Number(f.properties.num_lanes),
      speedLimitMps: Number(f.properties.speed_limit_mps),
      path,
      cum,
      lengthM: cum[cum.length - 1],
    },
  ];
});
export const junctions = network.features.flatMap((f) => {
  if (f.geometry.type !== "Point" || f.properties?.kind !== "junction")
    return [];
  return [
    {
      id: String(f.properties.junction_id),
      lng: f.geometry.coordinates[0],
      lat: f.geometry.coordinates[1],
      isTrafficLight: Boolean(f.properties.is_traffic_light),
    },
  ];
});
export const signalJunctions = junctions.filter((j) => j.isTrafficLight);
export const edgeById = new Map(roadEdges.map((e) => [e.id, e]));
export const junctionById = new Map(junctions.map((j) => [j.id, j]));
const points = roadEdges.flatMap((e) => e.path);
export const networkBounds = {
  minLng: Math.min(...points.map((p) => p[0])),
  maxLng: Math.max(...points.map((p) => p[0])),
  minLat: Math.min(...points.map((p) => p[1])),
  maxLat: Math.max(...points.map((p) => p[1])),
};
/** A road's display name: its street, or "Service road" when unnamed. */
export function roadLabel(edgeOrId: RoadEdge | string | undefined | null): string {
  const e = typeof edgeOrId === "string" ? edgeById.get(edgeOrId) : edgeOrId;
  if (!e) return typeof edgeOrId === "string" ? "Unknown road" : "Unknown road";
  return e.name ?? "Service road";
}

const junctionNames = new Map<string, string>();
/** Name a junction after the streets that meet there: "MG Road at Eat Street". */
export function shortJunctionName(id: string): string {
  const cached = junctionNames.get(id);
  if (cached) return cached;
  const j = junctionById.get(id);
  let name = `Junction ${id.slice(-4)}`;
  if (j) {
    const here: LngLat = [j.lng, j.lat];
    const streets = new Set<string>();
    for (const e of roadEdges) {
      if (!e.name) continue;
      const a = e.path[0];
      const b = e.path[e.path.length - 1];
      if (haversineMeters(here, a) < 30 || haversineMeters(here, b) < 30) streets.add(e.name);
    }
    const list = [...streets].sort((x, y) => (x === "MG Road" ? -1 : y === "MG Road" ? 1 : x.localeCompare(y)));
    if (list.length >= 2) name = `${list[0]} at ${list[1]}`;
    else if (list.length === 1) name = `${list[0]} junction`;
  }
  junctionNames.set(id, name);
  return name;
}

/** Geographic adjacency for the illustrative browser demo only, NOT emergency routing. */
export const edgeAdjacency = new Map(
  roadEdges.map((edge) => {
    const end = edge.path[edge.path.length - 1];
    const links = roadEdges
      .filter((e) => e.id !== edge.id)
      .flatMap((e) => {
        if (haversineMeters(end, e.path[0]) < 45)
          return [{ edgeId: e.id, reversed: false }];
        if (haversineMeters(end, e.path[e.path.length - 1]) < 45)
          return [{ edgeId: e.id, reversed: true }];
        return [];
      });
    return [edge.id, links];
  }),
);

export function nearestEdge(
  point: LngLat,
  maxDistanceM = 45,
): { edge: RoadEdge; snapped: LngLat; distanceM: number } | null {
  let best: ReturnType<typeof nearestEdge> = null;
  const scale = Math.cos((point[1] * Math.PI) / 180);
  for (const edge of roadEdges) {
    for (let i = 1; i < edge.path.length; i++) {
      const a = edge.path[i - 1],
        b = edge.path[i];
      const dx = (b[0] - a[0]) * scale,
        dy = b[1] - a[1];
      const denominator = dx * dx + dy * dy;
      const t =
        denominator === 0
          ? 0
          : Math.max(
              0,
              Math.min(
                1,
                ((point[0] - a[0]) * scale * dx + (point[1] - a[1]) * dy) /
                  denominator,
              ),
            );
      const snapped: LngLat = [
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
      ];
      const distanceM = haversineMeters(point, snapped);
      if (distanceM <= maxDistanceM && (!best || distanceM < best.distanceM))
        best = { edge, snapped, distanceM };
    }
  }
  return best;
}
