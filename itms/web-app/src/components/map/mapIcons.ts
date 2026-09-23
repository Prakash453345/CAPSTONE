/**
 * MapLibre symbol sprites for fleet vehicles.
 *
 * WebGL cannot sample SVG-backed HTMLImageElement textures (they upload as
 * fully transparent — the reason the arrow → SVG swap hid every vehicle).
 * Sprites are therefore rasterized to canvas `ImageData` (the same shape the
 * original arrow markers used) and registered with `map.addImage`. Silhouettes
 * stay stylized top-down
 * (fleet / command-center), nose-up so `icon-rotate` matches compass heading.
 */
import type { Map as MapLibreMap } from "maplibre-gl";
import type { EmergencyVehicleKind, VehicleType } from "@/types";

export const VEHICLE_ICON_ID: Record<VehicleType, string> = {
  car: "itms-veh-car",
  bus: "itms-veh-bus",
  truck: "itms-veh-truck",
  motorcycle: "itms-veh-moto",
  ambulance: "itms-veh-amb",
};

export const EMERGENCY_ICON_ID: Record<EmergencyVehicleKind, string> = {
  ambulance: "itms-em-ambulance",
  fire_truck: "itms-em-fire",
  police: "itms-em-police",
};

/**
 * Two otherwise identical ambulance sprites let the beacon change colour in
 * the symbol layer.  This keeps the effect in WebGL rather than creating an
 * animated DOM marker for every live unit.
 */
export const AMBULANCE_BEACON_ICON_ID = {
  red: "itms-em-ambulance-beacon-red",
  blue: "itms-em-ambulance-beacon-blue",
} as const;

export type MapSprite = ImageData;

const OUTLINE = "rgba(6, 10, 16, 0.92)";
const GLASS = "rgba(8, 14, 22, 0.5)";
const GLASS_HI = "rgba(255, 255, 255, 0.22)";
const LIGHT = "rgba(255, 255, 255, 0.7)";

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  const rr = Math.max(0, Math.min(r, w / 2, h / 2));
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

function paintBody(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
  fill: string,
) {
  roundRect(ctx, x, y, w, h, r);
  ctx.fillStyle = fill;
  ctx.fill();
  ctx.lineJoin = "round";
  ctx.lineWidth = 1.6;
  ctx.strokeStyle = OUTLINE;
  ctx.stroke();
}

function windshield(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r = 2,
) {
  roundRect(ctx, x, y, w, h, r);
  ctx.fillStyle = GLASS;
  ctx.fill();
  ctx.fillStyle = GLASS_HI;
  roundRect(ctx, x + 1, y + 0.6, w * 0.45, Math.max(1.2, h * 0.35), 1);
  ctx.fill();
}

function shadow(ctx: CanvasRenderingContext2D, cx: number, cy: number, rx: number, ry: number) {
  ctx.beginPath();
  ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(0, 0, 0, 0.32)";
  ctx.fill();
}

function canvas2d(size: number): { ctx: CanvasRenderingContext2D | null; canvas: HTMLCanvasElement } {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  return { canvas, ctx: canvas.getContext("2d", { willReadFrequently: true }) };
}

function readSprite(ctx: CanvasRenderingContext2D | null, size: number): ImageData {
  if (ctx) return ctx.getImageData(0, 0, size, size);
  return new ImageData(size, size);
}

/** Opaque-pixel count — tests use this to prove the sprite is not an empty texture. */
export function opaquePixelCount(sprite: ImageData): number {
  let n = 0;
  for (let i = 3; i < sprite.data.length; i += 4) if (sprite.data[i] > 8) n += 1;
  return n;
}

export function makeVehicleIcon(type: VehicleType, color: string, size = 64): ImageData {
  const { ctx } = canvas2d(size);
  if (ctx) {
    ctx.clearRect(0, 0, size, size);
    drawFleet(ctx, type, color, size, false);
  }
  return readSprite(ctx, size);
}

export function makeEmergencyIcon(
  kind: EmergencyVehicleKind,
  color: string,
  size = 80,
  flashRed = true,
): ImageData {
  const { ctx } = canvas2d(size);
  if (ctx) {
    ctx.clearRect(0, 0, size, size);
    drawEmergency(ctx, kind, color, size, flashRed);
  }
  return readSprite(ctx, size);
}

/**
 * Register a canvas `ImageData` sprite. SVG-backed HTMLImageElements upload as
 * fully transparent in WebGL; do not pass those here.
 */
export function upsertMapImage(map: MapLibreMap, id: string, image: ImageData, pixelRatio = 2) {
  try {
    if (map.hasImage(id)) map.removeImage(id);
  } catch {
    /* still referenced — addImage will replace or throw */
  }
  map.addImage(id, image, { pixelRatio, sdf: false });
}

function drawFleet(
  ctx: CanvasRenderingContext2D,
  type: VehicleType,
  color: string,
  size: number,
  flashRed: boolean,
) {
  const s = size / 64;
  ctx.save();
  ctx.scale(s, s);
  shadow(ctx, 32, 34, 11, 22);

  switch (type) {
    case "bus":
      paintBody(ctx, 21, 6, 22, 52, 5, color);
      windshield(ctx, 24, 9, 16, 8, 2);
      for (let y = 20; y <= 46; y += 9) {
        roundRect(ctx, 24, y, 16, 6, 1.5);
        ctx.fillStyle = "rgba(8,14,22,0.22)";
        ctx.fill();
      }
      ctx.fillStyle = LIGHT;
      ctx.fillRect(24, 7, 5, 2);
      ctx.fillRect(35, 7, 5, 2);
      break;
    case "truck": {
      paintBody(ctx, 21, 24, 22, 34, 3, "#3a414e");
      paintBody(ctx, 22, 6, 20, 18, 4, color);
      windshield(ctx, 25, 8, 14, 7, 2);
      ctx.fillStyle = LIGHT;
      ctx.fillRect(25, 7, 4, 2);
      ctx.fillRect(35, 7, 4, 2);
      break;
    }
    case "motorcycle": {
      ctx.fillStyle = OUTLINE;
      ctx.beginPath();
      ctx.ellipse(32, 18, 5, 6.5, 0, 0, Math.PI * 2);
      ctx.ellipse(32, 46, 5, 6.5, 0, 0, Math.PI * 2);
      ctx.fill();
      paintBody(ctx, 27.5, 16, 9, 32, 4, color);
      windshield(ctx, 28.5, 18, 7, 6, 2);
      ctx.fillStyle = LIGHT;
      ctx.fillRect(30, 16.5, 4, 1.6);
      break;
    }
    case "ambulance":
      drawAmbulance(ctx, color, flashRed);
      break;
    default:
      paintBody(ctx, 22, 10, 20, 44, 7, color);
      windshield(ctx, 25, 14, 14, 9, 3);
      roundRect(ctx, 25, 36, 14, 10, 3);
      ctx.fillStyle = "rgba(8,14,22,0.16)";
      ctx.fill();
      ctx.fillStyle = LIGHT;
      ctx.fillRect(25, 12, 4, 2);
      ctx.fillRect(35, 12, 4, 2);
      break;
  }
  ctx.restore();
}

function drawAmbulance(ctx: CanvasRenderingContext2D, color: string, flashRed: boolean) {
  paintBody(ctx, 18, 6, 28, 52, 6, color);
  windshield(ctx, 22, 10, 20, 10, 2);
  roundRect(ctx, 22, 24, 20, 24, 3);
  ctx.fillStyle = "rgba(255,255,255,0.12)";
  ctx.fill();
  roundRect(ctx, 24, 7, 16, 4, 1.5);
  ctx.fillStyle = flashRed ? "#ff3b4a" : "#3d7dff";
  ctx.fill();
  ctx.fillStyle = flashRed ? "#3d7dff" : "#ff3b4a";
  ctx.fillRect(32, 7, 8, 4);
  ctx.fillStyle = "#ff3344";
  ctx.fillRect(29, 30, 6, 16);
  ctx.fillRect(24, 35, 16, 6);
}

function drawEmergency(
  ctx: CanvasRenderingContext2D,
  kind: EmergencyVehicleKind,
  color: string,
  size: number,
  flashRed: boolean,
) {
  const s = size / 80;
  ctx.save();
  ctx.scale(s, s);
  shadow(ctx, 40, 42, 16, 24);

  if (kind === "fire_truck") {
    paintBody(ctx, 24, 28, 32, 44, 4, "#c4452d");
    paintBody(ctx, 26, 8, 28, 22, 5, color);
    windshield(ctx, 30, 12, 20, 10, 2);
    roundRect(ctx, 30, 8, 20, 5, 1.5);
    ctx.fillStyle = flashRed ? "#ff3b4a" : "#3d7dff";
    ctx.fill();
    ctx.fillStyle = "#ffcc66";
    ctx.fillRect(30, 9, 6, 2.5);
    ctx.fillRect(44, 9, 6, 2.5);
  } else if (kind === "police") {
    paintBody(ctx, 26, 12, 28, 56, 8, color);
    windshield(ctx, 30, 18, 20, 12, 3);
    roundRect(ctx, 30, 44, 20, 12, 3);
    ctx.fillStyle = "rgba(8,14,22,0.2)";
    ctx.fill();
    roundRect(ctx, 32, 10, 16, 5, 2);
    ctx.fillStyle = flashRed ? "#ff4d5a" : "#5aa0ff";
    ctx.fill();
    ctx.fillStyle = flashRed ? "#5aa0ff" : "#ff4d5a";
    ctx.fillRect(40, 10, 8, 5);
  } else {
    paintBody(ctx, 22, 6, 36, 68, 8, color);
    windshield(ctx, 27, 11, 26, 13, 3);
    roundRect(ctx, 27, 30, 26, 32, 4);
    ctx.fillStyle = "rgba(255,255,255,0.14)";
    ctx.fill();
    roundRect(ctx, 30, 8, 20, 6, 2);
    ctx.fillStyle = flashRed ? "#ff3b4a" : "#3d7dff";
    ctx.fill();
    ctx.fillStyle = flashRed ? "#3d7dff" : "#ff3b4a";
    ctx.fillRect(40, 8, 10, 6);
    ctx.fillStyle = "#ff3344";
    ctx.fillRect(37, 38, 8, 20);
    ctx.fillRect(30, 44, 22, 8);
  }
  ctx.restore();
}

export function iconIdForVehicleType(type: string): string {
  return VEHICLE_ICON_ID[type as VehicleType] ?? VEHICLE_ICON_ID.car;
}

export function iconIdForEmergencyKind(kind: string): string {
  return EMERGENCY_ICON_ID[kind as EmergencyVehicleKind] ?? EMERGENCY_ICON_ID.ambulance;
}
