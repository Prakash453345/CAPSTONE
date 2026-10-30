import type { Map as MapLibreMap } from "maplibre-gl";

/**
 * True while `map` is still a live, usable MapLibre instance — false once
 * `.remove()` has torn it down. Almost every Map method (`getLayer`,
 * `setPaintProperty`, ...) reads from the instance's internal style, which
 * `.remove()` clears; calling one after that throws from deep inside
 * MapLibre's own code ("Cannot read properties of undefined (reading
 * '...')") rather than anything traceable to our components, and — since
 * it happens from a `requestAnimationFrame` callback or an effect cleanup,
 * not during a React render — it isn't caught by `RouteError`'s render
 * boundary either; it surfaces as an unhandled rejection that still takes
 * the app down. `_removed` isn't public API, but it's the exact flag
 * MapLibre itself sets in `remove()`, so it's the precise question we need
 * answered, not an approximation of it.
 *
 * Every layer component's cleanup and animation-loop code must check this
 * before touching `map` — a real, recurring race in this app: two
 * `TrafficMap`s can be mounted at once (Split View), each tearing down
 * independently, and a layer's `requestAnimationFrame` loop can still have a
 * frame in flight when its own `TrafficMap` unmounts.
 */
export function isMapAlive(map: MapLibreMap): boolean {
  try {
    return !(map as unknown as { _removed?: boolean })._removed;
  } catch {
    return false;
  }
}
