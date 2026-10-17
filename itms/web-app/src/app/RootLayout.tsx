import { useEffect, type ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { GlobeTransition } from "@/components/transition/GlobeTransition";
import { useAuthStore } from "@/store/authStore";
import { useTransitionStore } from "@/store/transitionStore";

/**
 * Shared shell for every route. Its only job beyond `<Outlet/>` is to host
 * the cinematic globe overlay so it survives the landing→console navigation
 * instead of unmounting/remounting with the page it's flying between — see
 * GlobeTransition for the sequence itself.
 *
 * While the overlay fully covers the destination route, that route is kept at
 * `opacity: 0`: it still mounts, lays out, connects and gets rasterized (the
 * map needs its real size), but the compositor skips drawing its blurred
 * panels and live map every frame — work that otherwise competes with the
 * globe for the GPU. Opacity rather than `visibility: hidden`, because the
 * latter skips painting too, and the whole console then paints in one
 * ~400 ms burst when it is uncovered. The globe uncovers it just before the
 * reveal.
 */
export function RootLayout() {
  useSessionCheck();
  return (
    <div className="h-full">
      <Cover>
        <Outlet />
      </Cover>
      <GlobeTransition />
    </div>
  );
}

/** Owns the store subscription so flipping the cover re-renders only this
 * wrapper — `children` keeps its identity, so React skips the whole route
 * tree beneath it instead of re-rendering the console mid-cinematic. */
function Cover({ children }: { children: ReactNode }) {
  const covering = useTransitionStore((s) => s.covering);
  const { pathname } = useLocation();
  const covered = covering && pathname !== "/";
  return (
    <div className="h-full" style={covered ? { opacity: 0, pointerEvents: "none" } : undefined}>
      {children}
    </div>
  );
}

/** Asks the server who is signed in once at start, and again whenever the tab
 * comes back to the foreground, so a session that expired (or was ended from
 * another tab or by an administrator) while the page sat idle is noticed
 * before the operator acts on stale data. A failed re-check never signs
 * anyone out; only the server's "not signed in" does. */
function useSessionCheck() {
  useEffect(() => {
    const check = () => void useAuthStore.getState().check();
    const onVisible = () => document.visibilityState === "visible" && check();
    check();
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);
}
