import { useEffect, useRef, useState } from "react";
import Lenis from "lenis";
import "lenis/dist/lenis.css";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { useTransitionStore } from "@/store/transitionStore";
import "./landing.css";
import { Nav } from "./chrome";
import { Hero } from "./Hero";
import { Corridor } from "./Corridor";
import { Finale } from "./Finale";
import { Features } from "./Features";
import { Capabilities, Faq, Footer, Manifesto, Metrics } from "./sections";

function prefersReducedMotion() {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

/**
 * The public landing page at "/". A night-time, cinematic take on the product:
 * a WebGL avenue where signals turn green ahead of an ambulance, a scroll-driven
 * map that plays one incident from detection to a cleared corridor, then the
 * features, the safety rules and a way into the demo. No intro screen: the
 * headline is the first thing anyone sees.
 *
 * Every link to "/console" hands off to the Globe-to-Console cinematic (see
 * GlobeTransition) instead of navigating directly -- once signed in. Signed
 * out, it goes to /login first.
 */
export function LandingPage() {
  const rootRef = useRef<HTMLDivElement>(null);
  const lenisRef = useRef<Lenis | null>(null);
  const transitioning = useTransitionStore((s) => s.active);
  const startTransition = useTransitionStore((s) => s.start);
  const navigate = useNavigate();
  const [reduced] = useState(prefersReducedMotion);

  useEffect(() => {
    document.title = "Traffix: traffic lights that clear the way for ambulances";
    // Warm the cinematic's Earth textures while the visitor reads, so the
    // dive starts the instant they click through. Imported here rather than
    // at the top so three.js stays out of the landing page's first download.
    const warm = () =>
      void import("@/components/transition/cinematicEarth")
        .then((m) => m.preloadEarthTextures())
        .catch(() => {});
    const idle = window.requestIdleCallback?.(warm, { timeout: 2500 });
    const fallback = idle === undefined ? window.setTimeout(warm, 1200) : undefined;
    return () => {
      if (idle !== undefined) window.cancelIdleCallback(idle);
      if (fallback !== undefined) window.clearTimeout(fallback);
    };
  }, []);

  // Inertial smooth scrolling. It drives the native scroll position, so
  // framer-motion's scroll tracking and position: sticky work unchanged.
  useEffect(() => {
    if (reduced) return;
    const lenis = new Lenis({ lerp: 0.085, wheelMultiplier: 0.95, touchMultiplier: 1.4 });
    lenisRef.current = lenis;
    let raf = requestAnimationFrame(function loop(t) {
      lenis.raf(t);
      raf = requestAnimationFrame(loop);
    });
    return () => {
      cancelAnimationFrame(raf);
      lenis.destroy();
      lenisRef.current = null;
    };
  }, [reduced]);

  // Hold the page still while the transition runs.
  useEffect(() => {
    const lenis = lenisRef.current;
    if (transitioning) lenis?.stop();
    else lenis?.start();
  }, [transitioning]);

  // Links: "/console" starts the cinematic; in-page anchors glide there.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const onClick = (e: MouseEvent) => {
      const anchor = (e.target as HTMLElement).closest("a");
      if (!anchor) return;
      const href = anchor.getAttribute("href") ?? "";
      if (href === "/console") {
        e.preventDefault();
        // The cinematic ends inside the console, which needs a session. Signed
        // out (or not yet known), go and sign in first rather than diving
        // through the globe only to be turned back at the door.
        if (useAuthStore.getState().status !== "authed") {
          navigate("/login?next=%2Fconsole");
          return;
        }
        startTransition(); // no-ops if a transition is already running
        return;
      }
      if (href.startsWith("#")) {
        const target = document.getElementById(href.slice(1));
        if (!target) return;
        e.preventDefault();
        const lenis = lenisRef.current;
        if (lenis) lenis.scrollTo(target, { duration: 1.8, easing: (t) => 1 - Math.pow(1 - t, 4) });
        else target.scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
      }
    };
    root.addEventListener("click", onClick);
    return () => root.removeEventListener("click", onClick);
  }, [startTransition, navigate, reduced]);

  // Fade + lock the landing page the instant a transition starts, so the
  // globe overlay is never covering content that's still fully interactive.
  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    root.style.transition = "opacity 480ms ease, filter 480ms ease";
    root.style.opacity = transitioning ? "0" : "1";
    root.style.filter = transitioning ? "blur(6px)" : "none";
    root.style.pointerEvents = transitioning ? "none" : "";
  }, [transitioning]);

  return (
    <div className="lp" ref={rootRef}>
      <Nav />
      <main>
        <Hero paused={transitioning} reduced={reduced} />
        <Manifesto />
        <Corridor paused={transitioning} reduced={reduced} />
        <Features reduced={reduced} />
        <Capabilities />
        <Metrics />
        <Faq />
        <Finale reduced={reduced} />
      </main>
      <Footer />
    </div>
  );
}
