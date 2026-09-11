import { useEffect, useRef, useState } from "react";
import { Plus, Minus, Locate, Box, Layers } from "lucide-react";
import { useMapInstance } from "@/components/map/MapContext";
import { useMapStore, type MapLayerId } from "@/store/mapStore";
import { networkBounds } from "@/data/network";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/cn";

const LAYER_LABELS: Record<MapLayerId, string> = {
  vehicles: "Vehicles",
  signals: "Signals",
  congestion: "Congestion",
  incidents: "Incidents",
  anomalies: "Anomalies",
  emergency: "Emergency",
};

export function MapControls() {
  const map = useMapInstance();
  const activeLayers = useMapStore((s) => s.activeLayers);
  const toggleLayer = useMapStore((s) => s.toggleLayer);
  const [is3d, setIs3d] = useState(false);
  const [layersOpen, setLayersOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!layersOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!popoverRef.current?.contains(e.target as Node)) setLayersOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [layersOpen]);

  const recenter = () =>
    map.fitBounds(
      [
        [networkBounds.minLng, networkBounds.minLat],
        [networkBounds.maxLng, networkBounds.maxLat],
      ],
      { padding: 64, duration: 700, pitch: is3d ? 50 : 0 },
    );

  const toggle3d = () => {
    const next = !is3d;
    setIs3d(next);
    map.easeTo({ pitch: next ? 50 : 0, duration: 500 });
  };

  return (
    <div className="pointer-events-none absolute right-3 top-3 flex flex-col items-end gap-2">
      <div className="pointer-events-auto flex flex-col overflow-hidden rounded-lg border border-border bg-surface/90 backdrop-blur-sm shadow-panel">
        <ControlBtn label="Zoom in" onClick={() => map.zoomIn()}>
          <Plus />
        </ControlBtn>
        <div className="h-px bg-border" />
        <ControlBtn label="Zoom out" onClick={() => map.zoomOut()}>
          <Minus />
        </ControlBtn>
      </div>

      <div className="pointer-events-auto flex flex-col overflow-hidden rounded-lg border border-border bg-surface/90 backdrop-blur-sm shadow-panel">
        <ControlBtn label="Recenter on corridor" onClick={recenter}>
          <Locate />
        </ControlBtn>
        <div className="h-px bg-border" />
        <ControlBtn
          label={is3d ? "Switch to 2D" : "Switch to 3D"}
          active={is3d}
          onClick={toggle3d}
        >
          <Box />
        </ControlBtn>
      </div>

      <div ref={popoverRef} className="pointer-events-auto relative">
        <Button
          variant={layersOpen ? "primary" : "default"}
          size="icon-sm"
          aria-label="Map layers"
          aria-expanded={layersOpen}
          onClick={() => setLayersOpen((o) => !o)}
          className="shadow-panel"
        >
          <Layers />
        </Button>
        {layersOpen && (
          <div className="absolute right-0 top-10 w-44 rounded-lg border border-border bg-surface-raised p-1.5 shadow-panel-lg">
            <div className="px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
              Map layers
            </div>
            {(Object.keys(LAYER_LABELS) as MapLayerId[]).map((id) => {
              const on = activeLayers.has(id);
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => toggleLayer(id)}
                  className="flex w-full items-center justify-between rounded-md px-2 py-1.5 text-sm text-foreground transition-colors hover:bg-muted"
                >
                  <span>{LAYER_LABELS[id]}</span>
                  <span
                    className={cn(
                      "flex h-4 w-7 items-center rounded-full border border-border p-0.5 transition-colors",
                      on ? "justify-end bg-primary/70" : "justify-start bg-muted",
                    )}
                  >
                    <span className="h-3 w-3 rounded-full bg-foreground" />
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function ControlBtn({
  label,
  onClick,
  active,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className={cn(
        "grid h-8 w-8 place-items-center text-muted-foreground transition-colors hover:bg-muted hover:text-foreground [&_svg]:size-4",
        active && "bg-primary-muted/60 text-primary",
      )}
    >
      {children}
    </button>
  );
}
