import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { TrafficMap } from "@/components/map/TrafficMap";

/**
 * Full-screen map ("Explore map"). The shell hides its rail and top bar on
 * this route; the map's search pill carries a back arrow, as in Google Maps.
 * Back returns to wherever the operator came from, or the command centre
 * when the map was opened directly (a shared link, a refresh).
 */
export function MapPage() {
  const navigate = useNavigate();
  const location = useLocation();

  const back = useCallback(() => {
    if (location.key !== "default") navigate(-1);
    else navigate("/console");
  }, [location.key, navigate]);

  return (
    <div className="relative h-full">
      <TrafficMap fullscreen onExitFullscreen={back} />
    </div>
  );
}
