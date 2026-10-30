import { useEffect, useRef, useState } from "react";
import { LngLatBounds, type PaddingOptions } from "maplibre-gl";
import { LocateFixed, Navigation, Route } from "lucide-react";
import { useMapInstance } from "@/components/map/MapContext";
import { isMapAlive } from "@/components/map/mapSafe";
import { renderedVehicles } from "@/components/map/renderedVehicles";
import { isDriving, trimRoute } from "@/components/map/emergencyGeo";
import { MAP_CHIP, MAP_CHIP_ACTIVE } from "@/components/map/mapChrome";
import { selectSelectedRequest, useEmergencyStore } from "@/store/emergencyStore";
import { prefersReducedMotion } from "@/utils/motion";
import { angleDelta, bearingDeg, haversineMeters } from "@/utils/geo";
import { cn } from "@/utils/cn";
import { unitName } from "@/components/console/words";

type Mode = "follow" | "overview";

const FOLLOW_ZOOM = 16.8;
const FOLLOW_PITCH = 55;
/** Fraction of the map height kept above the vehicle in follow mode: the
 *  vehicle sits low on screen so the road ahead is what you see, as in a
 *  navigation app. */
const LOOK_AHEAD = 0.42;
/** Per-frame easing toward the follow view. Bearing is low enough that a
 *  junction turn reads as a smooth swing, not a snap; zoom, tilt and framing
 *  settle in about a second when following starts. */
const BEARING_EASE = 0.08;
const VIEW_EASE = 0.08;
/** The map turns to the direction the vehicle has actually travelled over at
 *  least this distance. The marker's own frame-to-frame heading swings by
 *  tens of degrees at low speed and would make the whole map wobble. */
const HEADING_BASELINE_M = 10;
/** For the first second the camera glides onto the vehicle; after that it
 *  locks on, so the vehicle stays exactly where it is on screen. */
const ENTRY_MS = 1_000;
const OVERVIEW_REFIT_MS = 3_000;
const NO_PADDING: PaddingOptions = { top: 0, bottom: 0, left: 0, right: 0 };

/**
 * Navigation-style camera for the selected emergency vehicle while it drives.
 *
 * - Follow: the map keeps the vehicle fixed low on screen, turned so it drives
 *   "up", tilted to show the road ahead.
 * - Overview: north-up, fitted to the vehicle and the road it still has to
 *   cover, refitted as that shrinks.
 *
 * The operator always wins: any drag, zoom, rotate or tilt of their own
 * pauses the camera and offers "Re-centre", as in Google Maps. It starts in
 * follow mode whenever a selected vehicle starts driving, and hands the map
 * back (flat, north-up) when the trip ends.
 *
 * `leftInset` is the width the route panel covers on the map's left, kept
 * clear so the vehicle is never framed underneath it.
 */
export function FollowCamera({ leftInset }: { leftInset: number }) {
  const map = useMapInstance();
  const selected = useEmergencyStore(selectSelectedRequest);
  const driving = Boolean(selected && isDriving(selected) && selected.live?.lat != null);
  const requestId = driving ? selected!.id : null;

  const [mode, setMode] = useState<Mode>("follow");
  const [paused, setPaused] = useState(false);
  const routeRef = useRef<readonly string[]>([]);
  routeRef.current = selected?.route?.edges ?? [];
  const insetRef = useRef(leftInset);
  insetRef.current = leftInset;

  // a newly selected (or newly departed) vehicle starts in follow mode
  useEffect(() => {
    setMode("follow");
    setPaused(false);
  }, [requestId]);

  // the operator's own gestures pause the camera. Mouse, touch and keyboard
  // moves carry an `originalEvent`; on-map buttons tag theirs `userGesture`.
  // Programmatic moves (another panel flying the map somewhere) carry neither
  // and never pause it: while following, the camera simply takes over again.
  useEffect(() => {
    if (!requestId) return;
    const onGesture = (e: { originalEvent?: unknown; userGesture?: boolean }) => {
      if (e.originalEvent || e.userGesture) setPaused(true);
    };
    const events = ["dragstart", "zoomstart", "rotatestart", "pitchstart"] as const;
    for (const ev of events) map.on(ev, onGesture);
    return () => {
      for (const ev of events) map.off(ev, onGesture);
    };
  }, [map, requestId]);

  // drive the camera
  useEffect(() => {
    if (!requestId || paused) return;
    const reduced = prefersReducedMotion();
    let raf = 0;
    let timer = 0;
    let cancelled = false;

    const followPadding = (): PaddingOptions => {
      const h = map.getContainer().clientHeight;
      return { top: Math.round(h * LOOK_AHEAD), bottom: 0, left: insetRef.current, right: 0 };
    };

    if (mode === "follow") {
      const begin = performance.now();
      const c = map.getCenter();
      const p = map.getPadding();
      const cam = {
        lng: c.lng,
        lat: c.lat,
        zoom: map.getZoom(),
        pitch: map.getPitch(),
        bearing: map.getBearing(),
        pad: { top: p.top, bottom: p.bottom, left: p.left, right: p.right },
      };
      let anchor: [number, number] | null = null;
      let travel = renderedVehicles.get(requestId)?.heading ?? cam.bearing;
      const tick = () => {
        if (cancelled || !isMapAlive(map)) return;
        const v = renderedVehicles.get(requestId);
        if (v) {
          const here: [number, number] = [v.lng, v.lat];
          if (!anchor) anchor = here;
          else if (haversineMeters(anchor, here) >= HEADING_BASELINE_M) {
            travel = bearingDeg(anchor, here);
            anchor = here;
          }
          const entering = performance.now() - begin < ENTRY_MS;
          const k = (rate: number) => (reduced ? 1 : rate);
          const kc = reduced || !entering ? 1 : 0.15;
          cam.lng += (v.lng - cam.lng) * kc;
          cam.lat += (v.lat - cam.lat) * kc;
          cam.zoom += (FOLLOW_ZOOM - cam.zoom) * k(VIEW_EASE);
          cam.pitch += (FOLLOW_PITCH - cam.pitch) * k(VIEW_EASE);
          cam.bearing += angleDelta(cam.bearing, travel) * k(BEARING_EASE);
          const target = followPadding();
          for (const side of ["top", "bottom", "left", "right"] as const) {
            cam.pad[side] += (target[side] - cam.pad[side]) * k(VIEW_EASE);
          }
          map.jumpTo({
            center: [cam.lng, cam.lat],
            zoom: cam.zoom,
            pitch: cam.pitch,
            bearing: cam.bearing,
            padding: cam.pad,
          });
        }
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    } else {
      const fit = () => {
        if (cancelled || !isMapAlive(map)) return;
        const v = renderedVehicles.get(requestId);
        const edges = routeRef.current;
        if (v) {
          const ahead = edges.length ? trimRoute(edges, { lng: v.lng, lat: v.lat }) : [];
          const bounds = new LngLatBounds([v.lng, v.lat], [v.lng, v.lat]);
          for (const c of ahead) bounds.extend([c[0], c[1]]);
          const cam = map.cameraForBounds(bounds, {
            padding: { top: 96, bottom: 96, left: insetRef.current + 56, right: 72 },
            maxZoom: 17,
          });
          if (cam) {
            map.easeTo(
              { ...cam, bearing: 0, pitch: 0, padding: NO_PADDING, duration: reduced ? 0 : 900 },
            );
          }
        }
        timer = window.setTimeout(fit, OVERVIEW_REFIT_MS);
      };
      fit();
    }

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
    };
  }, [map, requestId, mode, paused]);

  // trip over (arrived, cancelled, deselected): hand the map back flat
  const wasActive = useRef(false);
  useEffect(() => {
    if (requestId) {
      wasActive.current = true;
      return;
    }
    if (!wasActive.current || !isMapAlive(map)) return;
    wasActive.current = false;
    map.easeTo(
      {
        pitch: 0,
        bearing: 0,
        padding: NO_PADDING,
        zoom: Math.min(map.getZoom(), 16),
        duration: prefersReducedMotion() ? 0 : 900,
      },
    );
  }, [map, requestId]);

  if (!requestId || !selected) return null;

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-10 z-10 flex justify-center px-4">
      {paused ? (
        <button
          type="button"
          onClick={() => setPaused(false)}
          className={cn(MAP_CHIP, "h-10 px-4 text-sm", MAP_CHIP_ACTIVE)}
        >
          <LocateFixed />
          Re-centre
        </button>
      ) : (
        <div
          role="group"
          aria-label={`Camera for ${unitName(selected.vehicleId)}`}
          className="pointer-events-auto flex items-center gap-1 rounded-full bg-surface-raised p-1 shadow-elevation-2"
        >
          <span className="px-2.5 text-[12px] text-muted-foreground">
            Following <span className="font-medium text-foreground">{unitName(selected.vehicleId)}</span>
          </span>
          {(
            [
              ["follow", "Follow", Navigation],
              ["overview", "Overview", Route],
            ] as const
          ).map(([value, label, Icon]) => (
            <button
              key={value}
              type="button"
              aria-pressed={mode === value}
              onClick={() => setMode(value)}
              className={cn(
                "flex h-8 items-center gap-1.5 rounded-full px-3 text-[13px] font-medium transition-colors duration-150 [&_svg]:size-4",
                mode === value
                  ? "bg-primary-muted text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon />
              {label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
