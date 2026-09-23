import React, { useEffect, useRef, useState } from "react";
import Globe, { type GlobeMethods } from "react-globe.gl";
import * as THREE from "three";

export interface GlobeMarker {
  lat?: number;
  latitude?: number;
  lng?: number;
  longitude?: number;
  src?: string;
  label?: string;
  description?: string;
  color?: string;
}

export interface GlobeConfig {
  atmosphereColor?: string;
  atmosphereIntensity?: number; // 0 to 100 roughly maps to altitude
  bumpScale?: number;
  autoRotateSpeed?: number;
  gridOpacity?: number; // from the previous tactical globe
}

type NormalizedMarker = GlobeMarker & { lat: number; lng: number };

export interface Globe3DProps {
  markers?: GlobeMarker[];
  config?: GlobeConfig;
  onMarkerClick?: (marker: GlobeMarker) => void;
  onMarkerHover?: (marker: GlobeMarker | null) => void;
  // Allows parent to control the camera position programmatically
  pointOfView?: { lat: number; lng: number; altitude?: number };
}

export const Globe3D = React.forwardRef<GlobeMethods | undefined, Globe3DProps>(
  ({ markers = [], config = {}, onMarkerClick, onMarkerHover, pointOfView }, ref) => {
    const globeRef = useRef<GlobeMethods | undefined>(undefined);
    const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
    const containerRef = useRef<HTMLDivElement>(null);

    React.useImperativeHandle(ref, () => globeRef.current);

    // Normalize markers so both lat/lng and latitude/longitude work
    const normalizedMarkers = markers.map((m) => ({
      ...m,
      lat: m.lat ?? m.latitude ?? 0,
      lng: m.lng ?? m.longitude ?? 0,
    }));

    // Handle responsive sizing
    useEffect(() => {
      const observer = new ResizeObserver((entries) => {
        if (entries[0]) {
          setDimensions({
            width: entries[0].contentRect.width,
            height: entries[0].contentRect.height,
          });
        }
      });
      if (containerRef.current) {
        observer.observe(containerRef.current);
      }
      return () => observer.disconnect();
    }, []);

    // Update point of view when prop changes (for cinematic transitions)
    useEffect(() => {
      if (pointOfView && globeRef.current) {
        globeRef.current.pointOfView(pointOfView, 0);
      }
    }, [pointOfView]);

    // Handle controls and damping
    useEffect(() => {
      if (globeRef.current) {
        const controls = globeRef.current.controls();
        controls.enableDamping = false; // Prevent fighting with manual pointOfView updates
        controls.enableZoom = false; // Prevent accidental scrolling
        if (config.autoRotateSpeed) {
          controls.autoRotate = true;
          controls.autoRotateSpeed = config.autoRotateSpeed;
        } else {
          controls.autoRotate = false;
        }
      }
    }, [config.autoRotateSpeed]);

    // Custom material adjustments for a premium look
    useEffect(() => {
      if (globeRef.current) {
        // react-globe.gl's GlobeMethods typings omit globe.gl's own
        // globeMaterial() accessor; it exists at runtime.
        const material = (
          globeRef.current as unknown as { globeMaterial(): THREE.MeshPhongMaterial }
        ).globeMaterial();
        // The bumpScale prop needs a bump texture which we load in the component
        material.bumpScale = config.bumpScale ?? 5;
        // Make the oceans look deep and premium
        material.color = new THREE.Color("#0c151a");
        material.emissive = new THREE.Color("#050b0e");
        material.emissiveIntensity = 0.5;
      }
    }, [config.bumpScale]);

    return (
      <div ref={containerRef} className="h-full w-full">
        {dimensions.width > 0 && (
          <Globe
            ref={globeRef}
            width={dimensions.width}
            height={dimensions.height}
            // Use high-res dark earth for a premium tactical look
            globeImageUrl="//unpkg.com/three-globe/example/img/earth-dark.jpg"
            bumpImageUrl="//unpkg.com/three-globe/example/img/earth-topology.png"
            backgroundColor="rgba(0,0,0,0)"
            atmosphereColor={config.atmosphereColor || "#3fe0ff"}
            atmosphereAltitude={config.atmosphereIntensity ? config.atmosphereIntensity / 100 : 0.15}
            showGraticules={config.gridOpacity !== undefined && config.gridOpacity > 0}
            // Remove rings if we just want markers, or we could add rings here too
            htmlElementsData={normalizedMarkers}
            htmlElement={(datum: object) => {
              const d = datum as NormalizedMarker;
              const el = document.createElement("div"); // react-globe.gl applies its own transform here
              
              const inner = document.createElement("div");
              inner.style.display = "flex";
              inner.style.alignItems = "center";
              inner.style.cursor = "pointer";
              inner.style.color = d.color || "#3fe0ff";
              inner.style.fontSize = "11px";
              inner.style.fontWeight = "bold";
              inner.style.letterSpacing = "1px";
              inner.style.pointerEvents = "auto";
              inner.style.position = "absolute";
              inner.style.transition = "z-index 0.2s";
              inner.style.zIndex = "1";

              const isImg = !!d.src;
              const offset = isImg ? 12 : 4;
              inner.style.transform = `translate(-${offset}px, -${offset}px)`;

              if (d.src) {
                const img = document.createElement("img");
                img.src = d.src;
                img.style.width = "24px";
                img.style.height = "24px";
                img.style.borderRadius = "50%";
                img.style.border = `2px solid ${d.color || "#3fe0ff"}`;
                img.style.display = "block";
                inner.appendChild(img);
              } else {
                const dot = document.createElement("div");
                dot.style.width = "8px";
                dot.style.height = "8px";
                dot.style.borderRadius = "50%";
                dot.style.backgroundColor = d.color || "#3fe0ff";
                dot.style.boxShadow = `0 0 10px ${d.color || "#3fe0ff"}`;
                dot.style.display = "block";
                inner.appendChild(dot);
              }

              if (d.label) {
                const text = document.createElement("div");
                text.innerText = d.label;
                text.style.whiteSpace = "nowrap";
                text.style.textShadow = "0 2px 4px rgba(0,0,0,0.8)";
                text.style.background = "rgba(10, 14, 17, 0.85)";
                text.style.padding = "4px 8px";
                text.style.borderRadius = "6px";
                text.style.border = `1px solid ${d.color ? d.color + '40' : 'rgba(63, 224, 255, 0.25)'}`;
                text.style.backdropFilter = "blur(4px)";
                text.style.marginLeft = "8px";
                inner.appendChild(text);
              }

              inner.onmouseenter = () => {
                inner.style.zIndex = "100";
                onMarkerHover?.(d);
              };
              inner.onmouseleave = () => {
                inner.style.zIndex = "1";
                onMarkerHover?.(null);
              };
              inner.onclick = () => onMarkerClick?.(d);
              
              el.appendChild(inner);
              return el;
            }}
          />
        )}
      </div>
    );
  }
);
