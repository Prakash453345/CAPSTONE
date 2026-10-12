/**
 * Where each emergency vehicle is drawn right now: the per-frame interpolated
 * position and heading `EmergencyVehicleLayer` renders, keyed by request id.
 *
 * A plain mutable map rather than store state on purpose: it changes every
 * animation frame, and its one reader (`FollowCamera`) also runs per frame, so
 * routing it through React would re-render at 60 Hz for nothing. Following the
 * drawn position (not the raw ~1 Hz reports) is what keeps the vehicle still
 * on screen while the map moves under it.
 */
export interface RenderedVehicle {
  lng: number;
  lat: number;
  /** degrees clockwise from north, the direction the marker points */
  heading: number;
}

export const renderedVehicles = new Map<string, RenderedVehicle>();
