import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { DEFAULT_CENTER } from "@/store/mapStore";
import { CITIES_LABEL, HOME_CITY, SHOWN_CITIES, formatLatLng } from "@/data/city";
import { useTransitionStore } from "@/store/transitionStore";
import type { EarthCamera } from "./cinematicEarth";

/**
 * Landing → console cinematic: a single continuous camera move from high
 * orbit down onto Vijayawada, rendered by CinematicEarth (a photoreal
 * three.js Earth — see cinematicEarth.ts).
 *
 * Why it stays smooth:
 *
 * - The whole move is ONE timeline. Longitude/latitude, altitude, field of
 *   view and roll are each a function of the same clock with their own ease,
 *   so there are no phase seams where velocity could jump.
 * - Altitude is interpolated in log space, the way a real zoom feels: each
 *   second covers the same *ratio* of distance, from 4.2 Earth radii down to
 *   ~640 km (below that the 4K imagery goes soft — the console takes over), instead of racing through orbit and crawling at the end.
 * - Per-frame work never goes through React. One requestAnimationFrame loop
 *   moves the camera, renders, and writes the HUD readouts/reticle straight
 *   to DOM refs. React state changes only on the four caption changes.
 * - The first frame (shader compile, texture upload) is drawn while still
 *   invisible. The console route then mounts (MapLibre, WebSocket, stores)
 *   behind the overlay while the Earth holds still, and the camera only
 *   starts once frames are arriving on time again — so none of that cost
 *   lands mid-move. The clock also advances at most MAX_FRAME_MS per frame,
 *   so any stray hitch slows the camera for a beat rather than jumping it.
 * - The reveal is a crossfade while the camera is still descending, into a
 *   console map that finishes the same zoom (TrafficMap eases in on arrival),
 *   so the dive reads as one motion from space to street level.
 */

const TARGET = { lon: DEFAULT_CENTER.longitude, lat: DEFAULT_CENTER.latitude };

/** ms — the camera move itself, from first frame to rest. Sized so the whole
 * cinematic lands at ~9 s end to end (fade-in + settle hold + move up to the
 * reveal + fade-out). */
const MOTION_MS = 6400;
/** Fraction of MOTION_MS at which the console starts showing through. */
const REVEAL_AT = 0.91;
/** The hidden console is made visible a beat before the reveal, once the
 * haze is nearly opaque: its first rasterization stalls the compositor for a
 * few hundred ms, which is invisible on an almost-solid frame. */
const UNCOVER_AT = 0.87;
const ENTER_MS = 700;
const EXIT_MS = 1100;
/** Console mounts under the overlay once the landing page has faded. */
const NAVIGATE_AFTER_MS = ENTER_MS + 150;
/** Longest step the clock may take in one frame. A main-thread hitch then
 * slows the move for a beat instead of making the camera jump. */
const MAX_FRAME_MS = 34;
/** The camera starts once this many consecutive frames arrive within
 * QUIET_FRAME_MS — i.e. the console has finished warming up — or after
 * MAX_HOLD_MS regardless. */
const QUIET_FRAMES_NEEDED = 12;
const QUIET_FRAME_MS = 24;
const MAX_HOLD_MS = 2500;
/** Don't hold the visitor hostage to a slow network. */
const TEXTURE_TIMEOUT_MS = 8000;

const EASE: [number, number, number, number] = [0.65, 0, 0.35, 1];

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);
const smoothstep = (a: number, b: number, x: number) => {
  const t = clamp01((x - a) / (b - a));
  return t * t * (3 - 2 * t);
};

const ALT_START = 4.2;
const ALT_END = 0.1;

/** The camera at normalized time t ∈ [0, 1]. */
function cameraAt(t: number): EarthCamera {
  // Arrive over the target a little early so the last stretch is a pure descent.
  const travel = easeInOutCubic(clamp01(t / 0.8));
  const lon = lerp(TARGET.lon - 66, TARGET.lon, travel);
  // A shallow arc through the northern sky rather than a straight line.
  const lat = lerp(22, TARGET.lat, travel) + Math.sin(Math.PI * travel) * 5;
  const s = 0.5 - 0.5 * Math.cos(Math.PI * t);
  const alt = ALT_START * Math.pow(ALT_END / ALT_START, s);
  const fov = lerp(30, 46, smoothstep(0.5, 1, t));
  const roll = -8 * (1 - easeOutCubic(clamp01(t / 0.7)));
  return { lon, lat, alt, fov, roll };
}

type Caption = "orbit" | "region" | "city" | "live";

const CAPTIONS: Record<Caption, { kicker: string; title: string; sub: string }> = {
  orbit: { kicker: "Orbital view", title: "Earth", sub: "Traffic intelligence network" },
  region: { kicker: "Regional approach", title: "South Asia", sub: "Andhra Pradesh · Krishna corridor" },
  city: {
    kicker: "Target acquired",
    title: CITIES_LABEL,
    sub: SHOWN_CITIES.length > 1 ? "Pilot deployment and capital region" : HOME_CITY.blurb,
  },
  live: { kicker: "Handing over", title: "Live Command Center", sub: "Connecting to real-time traffic data" },
};

function captionAt(t: number): Caption {
  if (t < 0.3) return "orbit";
  if (t < 0.56) return "region";
  if (t < REVEAL_AT) return "city";
  return "live";
}

function fmtLat(v: number) {
  return `${Math.abs(v).toFixed(4)}° ${v >= 0 ? "N" : "S"}`;
}
function fmtLon(v: number) {
  return `${Math.abs(v).toFixed(4)}° ${v >= 0 ? "E" : "W"}`;
}
function fmtAlt(earthRadii: number) {
  const km = earthRadii * 6371;
  return km >= 1000 ? `${Math.round(km).toLocaleString("en-US")} km` : `${km.toFixed(1)} km`;
}

/** Static film grain — one inline SVG, never animated. */
const GRAIN =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.55 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>\")";

export function GlobeTransition() {
  const active = useTransitionStore((s) => s.active);
  return <AnimatePresence>{active && <TransitionStage key="globe-transition" />}</AnimatePresence>;
}

function TransitionStage() {
  const finish = useTransitionStore((s) => s.finish);
  const uncover = useTransitionStore((s) => s.uncover);
  const navigate = useNavigate();

  const hostRef = useRef<HTMLDivElement>(null);
  const canvasWrapRef = useRef<HTMLDivElement>(null);
  const hazeRef = useRef<HTMLDivElement>(null);
  const reticleRef = useRef<HTMLDivElement>(null);
  const latRef = useRef<HTMLSpanElement>(null);
  const lonRef = useRef<HTMLSpanElement>(null);
  const altRef = useRef<HTMLSpanElement>(null);
  const progressRef = useRef<HTMLDivElement>(null);

  const [caption, setCaption] = useState<Caption | null>(null);
  const [loading, setLoading] = useState(true);

  const navigatedRef = useRef(false);
  const finishedRef = useRef(false);

  const goToConsole = useCallback(() => {
    if (navigatedRef.current) return;
    navigatedRef.current = true;
    navigate("/console");
  }, [navigate]);

  const reveal = useCallback(() => {
    if (finishedRef.current) return;
    finishedRef.current = true;
    goToConsole();
    finish();
  }, [finish, goToConsole]);

  useEffect(() => {
    const host = hostRef.current;
    const wrap = canvasWrapRef.current;
    if (!host || !wrap) return;

    let cancelled = false;
    let raf = 0;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let earth: any = null;
    let cleanupResize: (() => void) | null = null;
    const timers: number[] = [];
    const later = (fn: () => void, ms: number) => timers.push(window.setTimeout(fn, ms));

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      later(reveal, 350);
      return () => timers.forEach(clearTimeout);
    }

    later(goToConsole, NAVIGATE_AFTER_MS);

    // A fresh canvas per run: a canvas whose context was released can't host
    // a new renderer (this also keeps React StrictMode's double mount honest).
    const canvas = document.createElement("canvas");
    canvas.style.cssText = "position:absolute;inset:0;width:100%;height:100%;display:block;";
    wrap.appendChild(canvas);

    const timeout = new Promise<null>((resolve) => later(() => resolve(null), TEXTURE_TIMEOUT_MS));

    const moduleLoad = import("./cinematicEarth");
    const texLoad = moduleLoad.then(({ preloadEarthTextures }) => preloadEarthTextures());

    Promise.race([texLoad, timeout])
      .then(async (tex) => {
        if (cancelled) return;
        if (!tex) throw new Error("textures timed out");
        const { CinematicEarth } = await moduleLoad;
        earth = new CinematicEarth(canvas, tex);
        const size = () => earth?.setSize(host.clientWidth, host.clientHeight);
        size();
        window.addEventListener("resize", size);
        cleanupResize = () => window.removeEventListener("resize", size);

        // Draw the first frame while still invisible — during the overlay's
        // fade-in — so shader compilation and texture upload are paid up
        // front and never cost a frame mid-motion.
        earth.setCamera(cameraAt(0));
        earth.render(0);
        setLoading(false);
        wrap.style.opacity = "1";

        // The Earth fades in at once, but the camera holds still until the
        // console behind the overlay has finished warming up (its mount,
        // map style, first data batches) and frames are arriving on time
        // again. A stall on a still frame is invisible; mid-move it's a
        // stutter.
        const shownAt = performance.now();
        let moving = false;
        let quietFrames = 0;
        let prev = 0;
        let elapsed = 0;
        let lastCaption: Caption | null = null;
        const tick = (now: number) => {
          if (cancelled || !earth) return;
          const dt = prev ? now - prev : 0;
          prev = now;
          if (!moving) {
            quietFrames = dt > 0 && dt < QUIET_FRAME_MS ? quietFrames + 1 : 0;
            const settled = navigatedRef.current && quietFrames >= QUIET_FRAMES_NEEDED;
            moving = settled || now - shownAt > MAX_HOLD_MS;
          } else {
            elapsed += Math.min(dt, MAX_FRAME_MS);
          }
          const t = clamp01(elapsed / MOTION_MS);

          const cam = cameraAt(t);
          earth.setCamera(cam);
          earth.render(elapsed / 1000);

          const w = host.clientWidth;
          const h = host.clientHeight;

          if (latRef.current) latRef.current.textContent = fmtLat(cam.lat);
          if (lonRef.current) lonRef.current.textContent = fmtLon(cam.lon);
          if (altRef.current) altRef.current.textContent = fmtAlt(cam.alt);
          if (progressRef.current) progressRef.current.style.transform = `scaleX(${t})`;

          // Reticle locks onto Vijayawada once it is well in view.
          const ret = reticleRef.current;
          if (ret) {
            const p = earth.project(TARGET.lon, TARGET.lat, w, h);
            const vis = p ? smoothstep(0.3, 0.42, t) * (1 - smoothstep(0.68, 0.76, t)) * smoothstep(0.08, 0.3, p.facing) : 0;
            ret.style.opacity = vis.toFixed(3);
            if (p) ret.style.transform = `translate3d(${p.x}px, ${p.y}px, 0) scale(${1.25 - 0.25 * smoothstep(0.3, 0.45, t)})`;
          }

          // Atmospheric haze as we drop through the sky, so the crossfade
          // lands on the console's own background tone. (Deliberately not a
          // CSS blur: filtering a full-screen live canvas costs whole frames
          // on integrated GPUs.)
          const haze = smoothstep(0.64, 0.87, t) * 0.94;
          if (hazeRef.current) hazeRef.current.style.opacity = haze.toFixed(3);

          const c = captionAt(t);
          if (c !== lastCaption) {
            lastCaption = c;
            setCaption(c);
          }
          if (t >= UNCOVER_AT && useTransitionStore.getState().covering) uncover();
          if (t >= REVEAL_AT) reveal();

          if (t < 1 || !finishedRef.current) raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      })
      .catch((err) => {
        // No WebGL or no textures — skip straight to the console.
        console.warn("[GlobeTransition] cinematic unavailable, going straight to the console:", err);
        if (!cancelled) later(reveal, 300);
      });

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      timers.forEach(clearTimeout);
      cleanupResize?.();
      earth?.dispose();
      canvas.remove();
    };
  }, [goToConsole, reveal, uncover]);

  // Escape / Enter skip the cinematic.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" || e.key === "Enter") reveal();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [reveal]);

  const copy = caption ? CAPTIONS[caption] : null;

  return (
    <motion.div
      ref={hostRef}
      className="fixed inset-0 z-[999] overflow-hidden bg-[#010204] text-[#e6f1f4]"
      style={{ fontFamily: "'Google Sans Flex', system-ui, sans-serif" }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1, transition: { duration: ENTER_MS / 1000, ease: EASE } }}
      exit={{ opacity: 0, transition: { duration: EXIT_MS / 1000, ease: EASE } }}
    >
      {/* the Earth — faded in once its first frame is on the GPU */}
      <div
        ref={canvasWrapRef}
        className="absolute inset-0"
        style={{ opacity: 0, transition: "opacity 1400ms cubic-bezier(0.33, 0, 0.2, 1)" }}
      />

      {/* lens vignette */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: "radial-gradient(ellipse 120% 90% at 50% 50%, transparent 55%, rgba(0,0,0,0.7) 100%)" }}
      />

      {/* descent haze — tinted to the console background so the handoff is seamless */}
      <div
        ref={hazeRef}
        className="pointer-events-none absolute inset-0"
        style={{
          opacity: 0,
          background: "radial-gradient(ellipse at 50% 50%, rgba(78,118,150,0.55) 0%, rgba(20,34,46,0.85) 55%, #0a0f15 100%)",
        }}
      />

      {/* film grain — plain alpha, no blend mode: blending over a live WebGL
          canvas forces an extra full-screen compositing pass every frame */}
      <div className="pointer-events-none absolute inset-0" style={{ backgroundImage: GRAIN, opacity: 0.035 }} />

      {/* target reticle — positioned every frame from the 3D projection */}
      <div ref={reticleRef} className="pointer-events-none absolute left-0 top-0" style={{ opacity: 0, willChange: "transform, opacity" }}>
        <div className="absolute -left-7 -top-7 h-14 w-14 rounded-full border border-[#7fe6ff]/70" />
        <div className="absolute -left-[3px] -top-[3px] h-[6px] w-[6px] rounded-full bg-[#7fe6ff] shadow-[0_0_14px_3px_rgba(127,230,255,0.7)]" />
        <div className="absolute -left-12 top-0 h-px w-4 bg-[#7fe6ff]/70" />
        <div className="absolute left-8 top-0 h-px w-4 bg-[#7fe6ff]/70" />
        <div className="absolute -top-12 left-0 h-4 w-px bg-[#7fe6ff]/70" />
        <div className="absolute left-0 top-8 h-4 w-px bg-[#7fe6ff]/70" />
        <div className="absolute left-14 -top-3 whitespace-nowrap" style={{ fontFamily: "'Google Sans Code', ui-monospace, monospace" }}>
          <div className="text-[10px] tracking-[0.28em] text-[#7fe6ff]">{HOME_CITY.name.toUpperCase()}</div>
          <div className="mt-0.5 text-[10px] tracking-[0.12em] text-white/55">{formatLatLng(DEFAULT_CENTER)}</div>
        </div>
      </div>

      {/* cinematic letterbox */}
      <motion.div
        className="pointer-events-none absolute inset-x-0 top-0 h-[8vh] origin-top bg-black"
        initial={{ scaleY: 0 }}
        animate={{ scaleY: 1 }}
        transition={{ duration: 1.1, ease: EASE, delay: 0.15 }}
      />
      <motion.div
        className="pointer-events-none absolute inset-x-0 bottom-0 h-[8vh] origin-bottom bg-black"
        initial={{ scaleY: 0 }}
        animate={{ scaleY: 1 }}
        transition={{ duration: 1.1, ease: EASE, delay: 0.15 }}
      />

      {/* HUD */}
      <div
        className="pointer-events-none absolute inset-x-6 top-[calc(8vh+20px)] flex items-start justify-between text-[10px] tracking-[0.22em] text-white/55 sm:inset-x-10"
        style={{ fontFamily: "'Google Sans Code', ui-monospace, monospace" }}
      >
        <div className="flex items-center gap-2.5">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#7fe6ff] opacity-50" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-[#7fe6ff]" />
          </span>
          ITMS · ORBITAL APPROACH
        </div>
        <div className="grid grid-cols-[auto_auto] gap-x-4 gap-y-1 text-right tabular-nums">
          <span className="text-white/35">LAT</span>
          <span ref={latRef} className="text-white/75">—</span>
          <span className="text-white/35">LON</span>
          <span ref={lonRef} className="text-white/75">—</span>
          <span className="text-white/35">ALT</span>
          <span ref={altRef} className="text-white/75">—</span>
        </div>
      </div>

      {/* lower-third caption */}
      <div className="pointer-events-none absolute bottom-[calc(8vh+36px)] left-6 right-6 sm:left-10">
        <AnimatePresence mode="wait">
          {copy && (
            <motion.div
              key={caption}
              initial={{ opacity: 0, y: 14, filter: "blur(6px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: -8, filter: "blur(6px)" }}
              transition={{ duration: 0.7, ease: EASE }}
            >
              <div
                className="flex items-center gap-3 text-[10px] tracking-[0.34em] text-[#7fe6ff]"
                style={{ fontFamily: "'Google Sans Code', ui-monospace, monospace" }}
              >
                <span className="h-px w-8 bg-[#7fe6ff]/60" />
                {copy.kicker.toUpperCase()}
              </div>
              <div className="mt-3 text-[34px] font-light leading-none tracking-[-0.01em] text-white sm:text-[48px]">
                {copy.title}
              </div>
              <div className="mt-3 text-[13px] tracking-[0.02em] text-white/55">{copy.sub}</div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* acquiring signal — only while textures are still arriving */}
      <AnimatePresence>
        {loading && (
          <motion.div
            className="pointer-events-none absolute inset-0 flex items-center justify-center text-[10px] tracking-[0.34em] text-white/45"
            style={{ fontFamily: "'Google Sans Code', ui-monospace, monospace" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: [0.35, 1, 0.35], transition: { duration: 1.8, repeat: Infinity } }}
            exit={{ opacity: 0, transition: { duration: 0.4 } }}
          >
            ACQUIRING ORBIT
          </motion.div>
        )}
      </AnimatePresence>

      {/* progress hairline + skip, sitting inside the lower letterbox */}
      <div className="absolute inset-x-6 bottom-[calc(4vh-6px)] flex items-center gap-5 sm:inset-x-10">
        <div className="h-px flex-1 overflow-hidden bg-white/10">
          <div ref={progressRef} className="h-full w-full origin-left bg-[#7fe6ff]/80" style={{ transform: "scaleX(0)" }} />
        </div>
        <button
          type="button"
          onClick={reveal}
          className="pointer-events-auto text-[10px] tracking-[0.28em] text-white/45 transition-colors hover:text-white/90"
          style={{ fontFamily: "'Google Sans Code', ui-monospace, monospace" }}
        >
          SKIP ↵
        </button>
      </div>
    </motion.div>
  );
}
