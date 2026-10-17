import { formatDistance, type Maneuver } from "@/drive/plan";

/** How far before a maneuver each spoken warning is given, farthest first. */
export const CUE_BANDS_M = [500, 200, 60] as const;

export interface Cue {
  /** Stable per maneuver and band, so each warning is spoken once. */
  key: string;
  text: string;
}

const lowerFirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

/**
 * The warning to give now for a maneuver `distM` away, or null when it is too
 * far off or nothing worth saying (the start is never announced). Only the
 * nearest band that applies is returned, so a driver who jumps from 900 m to
 * 150 m hears the 200 m warning, not the 500 m one they have already passed.
 * The wording always uses the real distance, never the band's.
 */
export function cueFor(m: Maneuver, distM: number): Cue | null {
  if (m.kind === "depart" || distM > CUE_BANDS_M[0]) return null;
  const band = [...CUE_BANDS_M].reverse().find((b) => distM <= b)!;
  if (m.kind === "arrive") {
    return { key: `${m.id}:${band}`, text: band === CUE_BANDS_M[2] ? "You are arriving at the destination" : `Destination in ${formatDistance(distM)}` };
  }
  const text = band === CUE_BANDS_M[2] ? m.text : `In ${formatDistance(distM)}, ${lowerFirst(m.text)}`;
  return { key: `${m.id}:${band}`, text };
}
