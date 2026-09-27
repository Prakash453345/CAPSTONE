import { useEffect, useRef, useState } from "react";
import { Plus, Minus, Locate, Box, Layers } from "lucide-react";
import { useMapInstance } from "@/components/map/MapContext";
import { useMapStore, type MapLayerId } from "@/store/mapStore";
import { useMapChromeStore } from "@/store/mapChromeStore";
import { networkBounds } from "@/data/network";
import { cn } from "@/utils/cn";

const LAYER_LABELS: Record<MapLayerId, string> = {
  vehicles: "Vehicles",
  signals: "Signals",
  congestion: "Congestion",
  incidents: "Incidents",
  anomalies: "Anomalies",
  emergency: "Emergency",
  weather: "Weather",
};

export function MapControls() {
  const map = useMapInstance();
  const activeLayers = useMapStore((s) => s.activeLayers);
  const toggleLayer = useMapStore((s) => s.toggleLayer);
  const [camera, setCamera] = useState(() => ({ bearing: map.getBearing(), pitch: map.getPitch() }));
  const layersOpen = useMapChromeStore((s) => s.sheet === "layers");
  const toggleSheet = useMapChromeStore((s) => s.toggle);
  const closeSheet = useMapChromeStore((s) => s.close);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!layersOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!popoverRef.current?.contains(e.target as Node)) closeSheet("layers");
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [layersOpen, closeSheet]);

  const recenter = () =>
    map.fitBounds(
      [
        [networkBounds.minLng, networkBounds.minLat],
        [networkBounds.maxLng, networkBounds.maxLat],
      ],
      { padding: 64, duration: 700, pitch: map.getPitch() > 5 ? 55 : 0 },
    );

  // Camera state drives the 3D toggle and the compass, so a right-drag tilt
  // or a two-finger rotate updates them just like the buttons do.
  useEffect(() => {
    const sync = () => {
      const bearing = Math.round(map.getBearing() * 10) / 10;
      const pitch = Math.round(map.getPitch());
      setCamera((c) => (c.bearing === bearing && c.pitch === pitch ? c : { bearing, pitch }));
    };
    map.on("rotate", sync);
    map.on("pitch", sync);
    return () => {
      map.off("rotate", sync);
      map.off("pitch", sync);
    };
  }, [map]);

  const is3d = camera.pitch > 5;
  const showCompass = is3d || Math.abs(camera.bearing) > 0.5;

  const toggle3d = () => {
    map.easeTo({ pitch: is3d ? 0 : 55, duration: 700, easing: EASE_EMPHASIZED });
  };

  const resetNorth = () => {
    map.easeTo({ bearing: 0, pitch: 0, duration: 700, easing: EASE_EMPHASIZED });
  };

  // Google Maps' arrangement: one-off tools stacked above the zoom pair,
  // bottom-right, each a 40px white card with Material elevation. The column
  // spans the map's height (below the weather chip) so the layers menu,
  // anchored to its bottom, can never grow past the top of the map.
  return (
    <div className="pointer-events-none absolute bottom-10 right-3 top-[4.25rem] z-[2] flex flex-col items-end justify-end gap-2">
      {showCompass && (
        <div className="animate-sheet-in">
          <ControlCard>
            <ControlBtn label="Reset to north, flat view" onClick={resetNorth}>
              <CompassNeedle bearing={camera.bearing} />
            </ControlBtn>
          </ControlCard>
        </div>
      )}

      <div ref={popoverRef} className="pointer-events-auto">
        <ControlCard>
          <ControlBtn
            label="Map layers"
            active={layersOpen}
            onClick={() => toggleSheet("layers")}
            ariaExpanded={layersOpen}
          >
            <Layers />
          </ControlBtn>
        </ControlCard>
        {layersOpen && (
          <div className="absolute bottom-0 right-12 max-h-full w-56 origin-bottom-right animate-sheet-in overflow-y-auto rounded-xl bg-surface-raised py-2 shadow-elevation-3">
            <div className="px-4 pb-1 pt-1 text-sm font-medium text-foreground">Map details</div>
            {(Object.keys(LAYER_LABELS) as MapLayerId[]).map((id) => {
              const on = activeLayers.has(id);
              return (
                <button
                  key={id}
                  type="button"
                  role="switch"
                  aria-checked={on}
                  aria-label={LAYER_LABELS[id]}
                  onClick={() => toggleLayer(id)}
                  className="flex w-full items-center justify-between px-4 py-2 text-sm text-foreground transition-colors hover:bg-muted"
                >
                  <span>{LAYER_LABELS[id]}</span>
                  <span
                    className={cn(
                      "flex h-5 w-9 items-center rounded-full p-0.5 transition-colors duration-200",
                      on ? "justify-end bg-primary" : "justify-start bg-input",
                    )}
                  >
                    <span className="size-4 rounded-full bg-white shadow-elevation-1" />
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <ControlCard>
        <ControlBtn label={is3d ? "Switch to 2D" : "Switch to 3D"} active={is3d} onClick={toggle3d}>
          <Box />
        </ControlBtn>
      </ControlCard>

      <ControlCard>
        <ControlBtn label="Recenter on corridor" onClick={recenter}>
          <Locate />
        </ControlBtn>
      </ControlCard>

      <ControlCard>
        <ControlBtn label="Zoom in" onClick={() => map.zoomIn()}>
          <Plus />
        </ControlBtn>
        <div className="mx-auto h-px w-7 bg-border" />
        <ControlBtn label="Zoom out" onClick={() => map.zoomOut()}>
          <Minus />
        </ControlBtn>
      </ControlCard>
    </div>
  );
}

/** Material "emphasized" curve: fast start, long gentle settle, like Maps' camera. */
function EASE_EMPHASIZED(t: number) {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

/** Google's compass: red north half, grey south half, turned against the map. */
function CompassNeedle({ bearing }: { bearing: number }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden style={{ transform: `rotate(${-bearing}deg)` }} className="transition-transform duration-100">
      <path d="M12 3 16 12H8Z" fill="#ea4335" />
      <path d="M12 21 8 12h8Z" className="fill-muted-foreground" />
    </svg>
  );
}

function ControlCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="pointer-events-auto flex flex-col overflow-hidden rounded-lg bg-surface-raised shadow-elevation-1">
      {children}
    </div>
  );
}

function ControlBtn({
  label,
  onClick,
  active,
  ariaExpanded,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  ariaExpanded?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-expanded={ariaExpanded}
      title={label}
      onClick={onClick}
      className={cn(
        "grid size-10 place-items-center text-muted-foreground transition-colors duration-150 ease-out hover:bg-muted hover:text-foreground active:bg-input/60 [&_svg]:size-5 [&_svg]:stroke-[1.75]",
        active && "text-primary hover:text-primary",
      )}
    >
      {children}
    </button>
  );
}
