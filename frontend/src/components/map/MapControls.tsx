import { useEffect, useRef, useState } from "react";
import { Plus, Minus, Locate, Box, Layers, Maximize2, Minimize2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useMapInstance } from "@/components/map/MapContext";
import { useMapStore, type MapLayerId } from "@/store/mapStore";
import { useMapChromeStore } from "@/store/mapChromeStore";
import { cityAt, cityBounds, networkBounds } from "@/data/network";
import { HOME_CITY } from "@/data/city";
import { cn } from "@/utils/cn";
import { USER_GESTURE } from "@/components/map/mapChrome";

const LAYER_LABELS: Record<MapLayerId, string> = {
  vehicles: "Vehicles",
  signals: "Signals",
  congestion: "Congestion",
  incidents: "Incidents",
  anomalies: "Anomalies",
  emergency: "Emergency",
  weather: "Weather",
};

export function MapControls({
  fullscreen = false,
  onExitFullscreen,
  children,
}: {
  fullscreen?: boolean;
  onExitFullscreen?: () => void;
  /** Extra controls stacked under the compass (the weather chip). */
  children?: React.ReactNode;
}) {
  const navigate = useNavigate();
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

  // Back to the whole of the city in view, not both cities at once.
  const recenter = () => {
    const c = map.getCenter();
    const b = cityBounds.get(cityAt(c.lng, c.lat) ?? HOME_CITY.id) ?? networkBounds;
    map.fitBounds(
      [
        [b.minLng, b.minLat],
        [b.maxLng, b.maxLat],
      ],
      { padding: 64, duration: 700, pitch: map.getPitch() > 5 ? 55 : 0 },
      USER_GESTURE,
    );
  };

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
    map.easeTo({ pitch: is3d ? 0 : 55, duration: 700, easing: EASE_EMPHASIZED }, USER_GESTURE);
  };

  const resetNorth = () => {
    map.easeTo({ bearing: 0, pitch: 0, duration: 700, easing: EASE_EMPHASIZED }, USER_GESTURE);
  };

  // Apple Maps' arrangement: map tools in one glass capsule at the top right,
  // the compass beneath it, and the zoom pair at the bottom right. The column
  // spans the map's height, so the layers menu can never run off it.
  return (
    <div
      style={{ right: "calc(12px + var(--inset-r, 0px))" }}
      className="pointer-events-none absolute bottom-10 top-3 z-[2] flex flex-col items-end justify-between gap-2"
    >
      <div className="flex flex-col items-end gap-2.5">
        <div ref={popoverRef} className="pointer-events-auto relative">
          <ControlCard>
            <ControlBtn
              label="Map layers"
              active={layersOpen}
              onClick={() => toggleSheet("layers")}
              ariaExpanded={layersOpen}
            >
              <Layers />
            </ControlBtn>
            <Divider />
            <ControlBtn label={is3d ? "Switch to 2D" : "Switch to 3D"} active={is3d} onClick={toggle3d}>
              <Box />
            </ControlBtn>
            <Divider />
            <ControlBtn label="Recenter on corridor" onClick={recenter}>
              <Locate />
            </ControlBtn>
            <Divider />
            {fullscreen ? (
              <ControlBtn label="Exit full screen" onClick={() => onExitFullscreen?.()}>
                <Minimize2 />
              </ControlBtn>
            ) : (
              <ControlBtn label="Full screen map" onClick={() => navigate("/console/map")}>
                <Maximize2 />
              </ControlBtn>
            )}
          </ControlCard>
          {layersOpen && (
            <div className="glass-strong absolute right-12 top-0 w-56 origin-top-right animate-sheet-in overflow-y-auto rounded-[14px] py-2">
              <div className="px-4 pb-1 pt-1 text-[13px] font-semibold text-foreground">Map details</div>
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
                    className="flex w-full items-center justify-between px-4 py-2 text-sm text-foreground transition-colors hover:bg-glass-hover"
                  >
                    <span>{LAYER_LABELS[id]}</span>
                    <span
                      className={cn(
                        "flex h-[22px] w-[38px] items-center rounded-full p-0.5 transition-colors duration-200",
                        on ? "justify-end bg-[#34c759]" : "justify-start bg-input",
                      )}
                    >
                      <span className="size-[18px] rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.3)]" />
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <button
          type="button"
          aria-label="Reset to north, flat view"
          title="Reset to north, flat view"
          onClick={resetNorth}
          className="glass glass-hover pointer-events-auto grid size-10 place-items-center rounded-full"
        >
          <Compass bearing={camera.bearing} tilted={showCompass} />
        </button>

        {children}
      </div>

      <ControlCard>
        <ControlBtn label="Zoom in" onClick={() => map.zoomIn(undefined, USER_GESTURE)}>
          <Plus />
        </ControlBtn>
        <Divider />
        <ControlBtn label="Zoom out" onClick={() => map.zoomOut(undefined, USER_GESTURE)}>
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

/** Apple's compass: an N with a red pointer on a ticked bezel, turned against the map. */
function Compass({ bearing, tilted }: { bearing: number; tilted: boolean }) {
  return (
    <svg
      viewBox="0 0 40 40"
      aria-hidden
      style={{ transform: `rotate(${-bearing}deg)` }}
      className="size-10 transition-transform duration-100"
    >
      {Array.from({ length: 12 }, (_, i) => (
        <line
          key={i}
          x1="20"
          y1="3.5"
          x2="20"
          y2={i % 3 === 0 ? 6.5 : 5.5}
          transform={`rotate(${i * 30} 20 20)`}
          className="stroke-muted-foreground"
          strokeWidth={i % 3 === 0 ? 1.4 : 0.9}
          strokeLinecap="round"
          opacity={i === 0 ? 0 : 0.7}
        />
      ))}
      <path d="M20 1.5 23 7h-6Z" fill="#ff3b30" />
      <text
        x="20"
        y="25"
        textAnchor="middle"
        className={cn("fill-foreground text-[13px] font-semibold", tilted && "fill-primary")}
      >
        N
      </text>
    </svg>
  );
}

function Divider() {
  return <div className="mx-2.5 h-px bg-[var(--glass-edge)]" />;
}

function ControlCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="glass pointer-events-auto flex flex-col overflow-hidden rounded-[12px]">
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
        "grid size-10 place-items-center text-foreground/80 transition-colors duration-150 ease-out hover:bg-glass-hover hover:text-foreground active:bg-glass-hover [&_svg]:size-[18px] [&_svg]:stroke-[1.9]",
        active && "text-primary hover:text-primary",
      )}
    >
      {children}
    </button>
  );
}
