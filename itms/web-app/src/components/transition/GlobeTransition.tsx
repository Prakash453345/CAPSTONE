import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, animate, motion } from "framer-motion";
import { DEFAULT_CENTER } from "@/store/mapStore";
import { useTransitionStore } from "@/store/transitionStore";
import { Globe3D, type GlobeMarker } from "@/components/ui/3d-globe";
import { LoaderOne } from "@/components/ui/loader";

/**
 * Landing → console cinematic: "Globe-to-Console".
 *
 * TacticalGlobe3D (see src/vendor/TacticalGlobe3D.js) has no camera-distance
 * or zoom API — only orthographic rotation (rotateY/rotateZ = latitude/
 * longitude) driven by props. So this sequence uses the one real capability
 * the globe exposes — rotating it to genuinely bring Vijayawada to the
 * center of the sphere — and fakes the "diving toward the surface" feeling
 * with a CSS transform scale + blur + fade-to-black on its container.
 *
 * Two things make this feel smooth rather than stuttery, both deliberate:
 *
 * 1. Every phase uses the SAME ease-in-out curve and starts/ends at zero
 *    velocity. Chaining ease-OUT segments back-to-back (as an earlier
 *    version did) leaves each phase ending at ~0 speed but the next one
 *    starting at full speed — that velocity jump at every seam reads as a
 *    stutter even at a perfect frame rate. Ease-in-out removes the jump.
 * 2. Only rotation (rz/ry) is driven from JS, because it has to flow into
 *    React props with no built-in tweening on the globe's side. Scale,
 *    blur, the fade-to-black and the progress bar are plain CSS
 *    transitions — the browser compositor animates those smoothly even
 *    while the globe's own per-frame SVG redraw (recomputing ~180
 *    countries' paths every tick) is busy on the main thread. During the
 *    dive/blackout/hold tail there is no per-frame JS at all.
 *
 * The real destination — the actual /console route with its live MapLibre
 * map, WebSocket feed and Zustand stores — only starts mounting at the
 * start of the dive phase (not earlier), so its own mount cost (WebGL
 * context, tile fetches, socket handshake) never competes with the
 * globe's rotation, which is the part where main-thread contention would
 * be most visible. It still gets the whole dive + blackout + hold + exit
 * fade to finish connecting before the reveal.
 */

type Phase = "idle" | "global" | "regional" | "local" | "dive" | "blackout";

interface Cam {
  rz: number; // rotateZ (lambda) — degrees of longitude centered on-screen
  ry: number; // rotateY (phi) — degrees of latitude centered on-screen
}

type CubicBezier = readonly [number, number, number, number];
const EASE_INOUT: CubicBezier = [0.65, 0, 0.35, 1];
const EASE_INOUT_CSS = "cubic-bezier(0.65, 0, 0.35, 1)";
const EASE_DIVE_CSS = "cubic-bezier(0.55, 0, 1, 0.45)"; // continues from local's v=0, accelerates through the punch

const ROT: Record<"start" | "global" | "regional" | "local", Cam> = {
  start: { rz: -55, ry: 9 },
  global: { rz: -18, ry: 10 },
  regional: { rz: 40, ry: 13 },
  local: { rz: DEFAULT_CENTER.longitude, ry: DEFAULT_CENTER.latitude },
};

const SCALE = { start: 0.72, global: 1, regional: 1.85, local: 3.4, dive: 21 } as const;

/** Premium, unhurried pacing — ms per phase. */
const DURATION = {
  enter: 850,
  global: 1500,
  regional: 1700,
  local: 1500,
  dive: 1150,
  blackout: 600,
  hold: 450,
  exit: 950,
} as const;

/** The punch-through beat at the end of dive: flash up, drop the (by-then
 * fully hidden) globe, fade to solid black underneath, then let the flash
 * clear. Kept separate from DURATION.blackout's CSS transition so the black
 * fade can be fast enough to be fully opaque well before the flash finishes
 * clearing — no frame is ever caught between the two. */
const BLACK_FADE_MS = 380;
const FLASH_IN_MS = 120;
const FLASH_HOLD_MS = 200;
const FLASH_OUT_MS = DURATION.blackout - FLASH_HOLD_MS;

const ROTATE_TOTAL_MS = DURATION.global + DURATION.regional + DURATION.local;
const SEQUENCE_MS = ROTATE_TOTAL_MS + DURATION.dive + DURATION.blackout;
const CUM = {
  global: DURATION.global / SEQUENCE_MS,
  regional: (DURATION.global + DURATION.regional) / SEQUENCE_MS,
  local: ROTATE_TOTAL_MS / SEQUENCE_MS,
  dive: (ROTATE_TOTAL_MS + DURATION.dive) / SEQUENCE_MS,
  blackout: 1,
};

const WORLD_MARKERS: GlobeMarker[] = [
  { label: "NORTH AMERICA", latitude: 38.9, longitude: -77.0, color: "#5f6b70" },
  { label: "EUROPE", latitude: 51.5, longitude: -0.12, color: "#5f6b70" },
  { label: "EAST ASIA", latitude: 35.68, longitude: 139.65, color: "#5f6b70" },
  { label: "OCEANIA", latitude: -33.87, longitude: 151.21, color: "#5f6b70" },
  {
    label: "VIJAYAWADA",
    description: "Deployment site",
    latitude: DEFAULT_CENTER.latitude,
    longitude: DEFAULT_CENTER.longitude,
    color: "#3fe0ff",
  },
];

const REGIONAL_MARKERS: GlobeMarker[] = [
  {
    label: "VIJAYAWADA",
    description: "Pilot network",
    latitude: DEFAULT_CENTER.latitude,
    longitude: DEFAULT_CENTER.longitude,
    color: "#3fe0ff",
  },
];

const LOCAL_MARKERS: GlobeMarker[] = [];

const PHASE_COPY: Record<Phase, { title: string; sub: string }> = {
  idle: { title: "", sub: "" },
  global: { title: "GLOBAL STRATEGIC VIEW", sub: "Traffic monitoring network — worldwide" },
  regional: { title: "REGIONAL FOCUS", sub: "South Asia corridor" },
  local: { title: "VIJAYAWADA TRAFFIC NETWORK", sub: "20 junctions · pilot deployment" },
  dive: { title: "LIVE COMMAND CENTER", sub: "Connecting to real-time traffic data" },
  blackout: { title: "LIVE COMMAND CENTER", sub: "Connecting to real-time traffic data" },
};

/** Static — hoisted so it's never rebuilt on the per-frame rotation re-renders. */
const CORNER_BRACKETS = (
  <>
    <div className="absolute left-6 top-6 h-8 w-8 border-l border-t border-[#3fe0ff]/40" />
    <div className="absolute right-6 top-6 h-8 w-8 border-r border-t border-[#3fe0ff]/40" />
    <div className="absolute bottom-6 left-6 h-8 w-8 border-b border-l border-[#3fe0ff]/40" />
    <div className="absolute bottom-6 right-6 h-8 w-8 border-b border-r border-[#3fe0ff]/40" />
  </>
);

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t;
}

function wait(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

function formatLat(v: number) {
  return `${Math.abs(v).toFixed(4)}°${v >= 0 ? "N" : "S"}`;
}

function formatLng(v: number) {
  return `${Math.abs(v).toFixed(4)}°${v >= 0 ? "E" : "W"}`;
}

export function GlobeTransition() {
  const active = useTransitionStore((s) => s.active);
  const finish = useTransitionStore((s) => s.finish);
  const navigate = useNavigate();

  const [phase, setPhase] = useState<Phase>("idle");
  const [cam, setCam] = useState<Cam>(ROT.start);
  const [markers, setMarkers] = useState<GlobeMarker[]>(WORLD_MARKERS);
  const [progress, setProgress] = useState(0);

  // CSS-transition targets: each is flipped ONCE per phase and the browser
  // compositor interpolates it — no per-frame JS involved for any of these.
  const [scaleTarget, setScaleTarget] = useState<number>(SCALE.start);
  const [scaleDurationMs, setScaleDurationMs] = useState(0);
  const [blurTarget, setBlurTarget] = useState(0);
  const [blackTarget, setBlackTarget] = useState(0);
  const [flashOn, setFlashOn] = useState(false);

  const runningRef = useRef(false);

  useEffect(() => {
    if (!active) return;
    if (runningRef.current) return; // duplicate-click guard mirrors the store's own
    runningRef.current = true;
    let cancelled = false;

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /** Rotates the globe over `ms`, driven from JS (framer-motion `animate`) since
     * the globe has no built-in tweening. Scale rides along on a plain CSS
     * transition set once, in parallel — never JS-driven. */
    async function rotatePhase(p: Phase, from: Cam, to: Cam, scale: number, ms: number, cum: number) {
      setPhase(p);
      setScaleDurationMs(ms);
      setScaleTarget(scale);
      const zero: number = 0;
      const one: number = 1;
      await animate(zero, one, {
        duration: ms / 1000,
        ease: EASE_INOUT,
        onUpdate: (t) => setCam({ rz: lerp(from.rz, to.rz, t), ry: lerp(from.ry, to.ry, t) }),
      });
      if (!cancelled) setProgress(cum);
    }

    (async () => {
      if (reduced) {
        setCam(ROT.local);
        setScaleTarget(SCALE.local);
        setScaleDurationMs(0);
        setPhase("dive");
        setMarkers(LOCAL_MARKERS);
        navigate("/console");
        await wait(400);
        if (!cancelled) finish();
        runningRef.current = false;
        return;
      }

      setCam(ROT.start);
      setScaleTarget(SCALE.start);
      setScaleDurationMs(0);
      setMarkers(WORLD_MARKERS);

      await rotatePhase("global", ROT.start, ROT.global, SCALE.global, DURATION.global, CUM.global);
      if (cancelled) return;

      setMarkers(REGIONAL_MARKERS);
      await rotatePhase("regional", ROT.global, ROT.regional, SCALE.regional, DURATION.regional, CUM.regional);
      if (cancelled) return;

      setMarkers(LOCAL_MARKERS);
      await rotatePhase("local", ROT.regional, ROT.local, SCALE.local, DURATION.local, CUM.local);
      if (cancelled) return;

      // Dive: rotation target doesn't change any more (already centered on
      // Vijayawada), so from here on nothing needs per-frame JS — scale,
      // blur, the blackout and the progress bar are all plain CSS
      // transitions running on the compositor. This is also where the real
      // console starts mounting, once the busiest rotation work is done.
      navigate("/console");
      setMarkers([]);
      setPhase("dive");
      setScaleDurationMs(DURATION.dive);
      setScaleTarget(SCALE.dive);
      setBlurTarget(20);
      setProgress(CUM.dive);
      await wait(DURATION.dive);
      if (cancelled) return;

      // Punch through: flash bright, fade to solid black, and drop the
      // globe from the tree — all in the same beat. The globe's own
      // per-frame redraw loop (recomputing every country's SVG path,
      // every tick) only stops once it's actually unmounted; leaving it
      // mounted-but-hidden behind the overlay is exactly what caused the
      // stall right before the reveal. It's safe to cut the instant the
      // flash covers the screen — black is already fully opaque well
      // before the flash finishes clearing, so nothing is ever exposed.
      setPhase("blackout");
      setBlackTarget(1);
      setFlashOn(true);
      setProgress(CUM.blackout);
      await wait(FLASH_HOLD_MS);
      if (cancelled) return;
      setFlashOn(false);
      await wait(FLASH_OUT_MS);
      if (cancelled) return;

      await wait(DURATION.hold);
      if (cancelled) return;
      finish();
      runningRef.current = false;
    })();

    return () => {
      cancelled = true;
    };
  }, [active, navigate, finish]);

  useEffect(() => {
    if (!active) {
      runningRef.current = false;
      setPhase("idle");
      setCam(ROT.start);
      setMarkers(WORLD_MARKERS);
      setScaleTarget(SCALE.start);
      setScaleDurationMs(0);
      setBlurTarget(0);
      setBlackTarget(0);
      setFlashOn(false);
      setProgress(0);
    }
  }, [active]);

  const copy = PHASE_COPY[phase];
  const rotationLive = phase === "global" || phase === "regional" || phase === "local";

  return (
    <AnimatePresence>
      {active && (
        <motion.div
          key="globe-transition"
          className="fixed inset-0 z-[999] overflow-hidden bg-[#03050a] text-[#dfeef2]"
          style={{ fontFamily: "'IBM Plex Mono', ui-monospace, monospace" }}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1, transition: { duration: DURATION.enter / 1000, ease: EASE_INOUT } }}
          exit={{ opacity: 0, transition: { duration: DURATION.exit / 1000, ease: EASE_INOUT } }}
        >
          {/* base gradient */}
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(ellipse at 50% 42%, #0b1a20 0%, #050a0d 62%, #010203 100%)",
            }}
          />

          {/* static framing vignette — never animated, so it's free */}
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(circle at 50% 50%, transparent 55%, rgba(1,2,4,0.85) 100%)",
            }}
          />

          {/* globe — scale/blur are CSS transitions (compositor-driven), rotation is the only JS-driven value.
              Unmounted once "blackout" starts: it's the ONE thing on this page with a genuine per-frame
              cost (its own internal loop recomputes every country's SVG path every tick, independent of
              React), and leaving it mounted-but-hidden behind the flash/black is what caused the stall
              right before the reveal — this is what actually stops that work, not just hiding it. */}
          {phase !== "blackout" && (
            <div
              className="absolute left-1/2 top-1/2 h-[62vmin] w-[62vmin]"
              style={{
                transform: `translate(-50%, -50%) scale(${scaleTarget})`,
                filter: blurTarget > 0.05 ? `blur(${blurTarget}px)` : undefined,
                transition: `transform ${scaleDurationMs}ms ${phase === "dive" ? EASE_DIVE_CSS : EASE_INOUT_CSS}, filter ${Math.max(scaleDurationMs, 400)}ms ease-in`,
                willChange: "transform, filter",
              }}
            >
              <Globe3D
                pointOfView={{ lat: cam.ry, lng: cam.rz, altitude: 2.5 }}
                markers={markers}
                config={{
                  atmosphereColor: "#3fe0ff",
                  atmosphereIntensity: 15,
                  bumpScale: 5,
                }}
              />
            </div>
          )}

          {/* fade to black for the reveal — fast enough to be fully opaque well before the flash below
              finishes clearing, so no frame is ever caught between the globe disappearing and black
              covering it (the flash masks that instant regardless). */}
          <div
            className="pointer-events-none absolute inset-0 bg-black"
            style={{ opacity: blackTarget, transition: `opacity ${BLACK_FADE_MS}ms ease-in`, willChange: "opacity" }}
          />

          {/* punch-through flash — the brightness (not precise timing) is what hides the globe's unmount */}
          <div
            className="pointer-events-none absolute inset-0 bg-white"
            style={{
              opacity: flashOn ? 0.92 : 0,
              transition: `opacity ${flashOn ? FLASH_IN_MS : FLASH_OUT_MS}ms ${flashOn ? "ease-out" : "ease-in"}`,
            }}
          />

          {/* HUD chrome */}
          <div className="pointer-events-none absolute inset-0">
            {CORNER_BRACKETS}

            {/* top-left status */}
            <div className="absolute left-8 top-8 flex items-center gap-2 text-[11px] tracking-[0.18em] text-[#8fa5ad]">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#3fe0ff] opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-[#3fe0ff]" />
              </span>
              NETWORK UPLINK · LIVE
            </div>

            {/* top-right coordinates */}
            <div className="absolute right-8 top-8 text-right text-[11px] tracking-[0.1em] text-[#8fa5ad]">
              <div>{formatLat(cam.ry)}</div>
              <div>{formatLng(cam.rz)}</div>
            </div>

            {/* center label */}
            <div className="absolute inset-0 flex flex-col items-center justify-center px-6 text-center">
              <AnimatePresence mode="wait">
                {(phase === "dive" || phase === "blackout") ? (
                  <motion.div
                    key="dive-loader"
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 1.05 }}
                    transition={{ duration: 0.6, ease: EASE_INOUT }}
                    className="flex flex-col items-center justify-center gap-8"
                  >
                    <LoaderOne />
                  </motion.div>
                ) : copy.title ? (
                  <motion.div
                    key={phase}
                    initial={{ opacity: 0, y: 16 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -12 }}
                    transition={{ duration: 0.55, ease: EASE_INOUT }}
                  >
                    <div className="text-[11px] font-semibold tracking-[0.3em] text-[#3fe0ff]">
                      {copy.title}
                    </div>
                    <div className="mt-2 text-[13px] tracking-[0.05em] text-[#9bb0b6]">
                      {copy.sub}
                    </div>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </div>

            {/* bottom progress — transform:scaleX so it's compositor-driven, not layout-driven */}
            <AnimatePresence>
              {(phase !== "dive" && phase !== "blackout") && (
                <motion.div 
                  initial={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="absolute inset-x-8 bottom-8"
                >
                  <div className="h-[2px] w-full overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full w-full origin-left bg-[#3fe0ff]"
                      style={{ transform: `scaleX(${progress})`, transition: "transform 420ms linear" }}
                    />
                  </div>
                  <div className="mt-2 flex justify-between text-[10px] tracking-[0.14em] text-[#5b686d]">
                    <span>ITMS COMMAND UPLINK</span>
                    <span>{Math.round(progress * 100)}%</span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
