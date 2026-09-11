/**
 * Per-mission colour for the map: every emergency request keeps one colour for
 * its whole lifetime, independent of how many other requests are active or in
 * what order — a stable hash of the request id, not a position in a list (a
 * list-position scheme reshuffles every other mission's colour whenever one
 * request completes or a new one starts).
 *
 * Shared by `EmergencyRouteLayer` and `EmergencyVehicleLayer` so a given
 * mission's route and its vehicle are always the same colour.
 */
const PALETTE = ["#5fd0ff", "#b78bff", "#ffb057", "#ff5470", "#6ee7b7", "#f472b6"] as const;

export function colorForRequest(requestId: string): string {
  let h = 0;
  for (let i = 0; i < requestId.length; i++) {
    h = (h * 31 + requestId.charCodeAt(i)) | 0;
  }
  return PALETTE[Math.abs(h) % PALETTE.length];
}
