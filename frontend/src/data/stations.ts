// The police and fire stations the simulator sends crews from: the same file
// sim-service reads (responder_depots.json), so the map shows exactly the
// places a unit can start from. A station marked `dispatch: false` (the Cyber
// Crime unit) is not a base for patrol cars and is left off.
import depots from "../../../backend/data/scenarios/networks/vijayawada/responder_depots.json";
import { LIVE_CITY } from "@/data/city";
import { roadEdges } from "@/data/network";

export type StationKind = "police" | "fire_station";

export interface Station {
  id: string;
  name: string;
  kind: StationKind;
  /** Where the building is. */
  lat: number;
  lon: number;
  /** Where a crew leaves from: the nearest point on the road network. */
  at: [number, number];
  /** How far the building is from that road, in metres. */
  offRoadM: number;
}

export const STATION_LABEL: Record<StationKind, string> = {
  police: "Police station",
  fire_station: "Fire station",
};

const M_PER_DEG_LAT = 111_320;

/** The nearest point on the live city's roads to (lat, lon), as the simulator
 *  parks a crew: stations are drawn there, on the network, not where the
 *  building stands. */
export function nearestRoadPoint(lat: number, lon: number): { at: [number, number]; distM: number } | null {
  const kx = M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180);
  let best: { at: [number, number]; distM: number } | null = null;
  for (const e of roadEdges) {
    if (e.city !== LIVE_CITY) continue;
    for (let i = 0; i + 1 < e.path.length; i++) {
      const [ax, ay] = e.path[i]!;
      const [bx, by] = e.path[i + 1]!;
      const dx = (bx - ax) * kx;
      const dy = (by - ay) * M_PER_DEG_LAT;
      const len2 = dx * dx + dy * dy;
      const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, (((lon - ax) * kx) * dx + ((lat - ay) * M_PER_DEG_LAT) * dy) / len2));
      const px = ax + (bx - ax) * t;
      const py = ay + (by - ay) * t;
      const distM = Math.hypot((lon - px) * kx, (lat - py) * M_PER_DEG_LAT);
      if (!best || distM < best.distM) best = { at: [px, py], distM };
    }
  }
  return best;
}

export const stations: Station[] = (depots.depots as Array<Omit<Station, "at" | "offRoadM"> & { dispatch?: boolean }>)
  .filter((d) => (d.kind === "police" || d.kind === "fire_station") && d.dispatch !== false)
  .map(({ id, name, kind, lat, lon }) => {
    const road = nearestRoadPoint(lat, lon);
    return { id, name, kind, lat, lon, at: road?.at ?? [lon, lat], offRoadM: road ? Math.round(road.distM) : 0 };
  });
