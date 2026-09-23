import { Outlet } from "react-router-dom";
import { GlobeTransition } from "@/components/transition/GlobeTransition";

/**
 * Shared shell for every route. Its only job beyond `<Outlet/>` is to host
 * the cinematic globe overlay so it survives the landing→console navigation
 * instead of unmounting/remounting with the page it's flying between — see
 * GlobeTransition for the sequence itself.
 */
export function RootLayout() {
  return (
    <div className="h-full">
      <Outlet />
      <GlobeTransition />
    </div>
  );
}
