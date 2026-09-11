/**
 * Pure per-junction vehicle stats, shared by both data providers (Phase 11
 * cleanup) — `wsProvider.ts` and `mockProvider.ts` had independently
 * duplicated this exact "which vehicles are near this junction, and how fast
 * are they going" computation, magic numbers included. One implementation
 * means one place to change the proximity radius or the queue-speed
 * threshold, and no risk of the two drifting apart.
 */
import type { Vehicle } from "@/types";
import { haversineMeters, type LngLat } from "@/utils/geo";

/** A vehicle within this many metres of a junction counts toward its stats. */
export const JUNCTION_RADIUS_M = 60;
/** Below this speed (km/h), a nearby vehicle counts as queued, not moving. */
export const QUEUE_SPEED_KMH = 6;

export interface JunctionVehicleStats {
  queueLength: number;
  averageSpeed: number;
  vehicleCount: number;
}

/** `junction` as `[lng, lat]`, matching `haversineMeters`'s point shape. */
export function junctionVehicleStats(
  junction: LngLat,
  vehicles: Vehicle[],
): JunctionVehicleStats {
  const near = vehicles.filter(
    (v) => haversineMeters([v.longitude, v.latitude], junction) < JUNCTION_RADIUS_M,
  );
  const averageSpeed = near.length
    ? near.reduce((sum, v) => sum + v.speed, 0) / near.length
    : 0;
  return {
    queueLength: near.filter((v) => v.speed < QUEUE_SPEED_KMH).length,
    averageSpeed: Math.round(averageSpeed),
    vehicleCount: near.length,
  };
}
