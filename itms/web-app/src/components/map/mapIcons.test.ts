import { describe, expect, it } from "vitest";
import type { EmergencyVehicleKind, VehicleType } from "@/types";
import { VEHICLE_COLOR } from "@/components/map/mapColors";
import {
  AMBULANCE_BEACON_ICON_ID,
  EMERGENCY_ICON_ID,
  VEHICLE_ICON_ID,
  iconIdForEmergencyKind,
  iconIdForVehicleType,
  makeEmergencyIcon,
  makeVehicleIcon,
  opaquePixelCount,
} from "@/components/map/mapIcons";

const FLEET: VehicleType[] = ["car", "bus", "truck", "motorcycle", "ambulance"];
const EMERGENCY: EmergencyVehicleKind[] = ["ambulance", "fire_truck", "police"];

function canRasterize(): boolean {
  if (typeof document === "undefined") return false;
  const c = document.createElement("canvas");
  return Boolean(c.getContext("2d"));
}

describe("mapIcons", () => {
  it("assigns a unique sprite id to every fleet type", () => {
    const ids = FLEET.map((t) => VEHICLE_ICON_ID[t]);
    expect(new Set(ids).size).toBe(FLEET.length);
    for (const id of ids) expect(id.startsWith("itms-veh-")).toBe(true);
  });

  it("assigns a unique sprite id to every emergency kind", () => {
    const ids = EMERGENCY.map((k) => EMERGENCY_ICON_ID[k]);
    expect(new Set(ids).size).toBe(EMERGENCY.length);
  });

  it("provides distinct red and blue ambulance beacon sprite ids", () => {
    expect(AMBULANCE_BEACON_ICON_ID.red).not.toBe(AMBULANCE_BEACON_ICON_ID.blue);
  });

  it("falls back unknown types to car / ambulance", () => {
    expect(iconIdForVehicleType("auto")).toBe(VEHICLE_ICON_ID.car);
    expect(iconIdForEmergencyKind("helicopter")).toBe(EMERGENCY_ICON_ID.ambulance);
  });

  it("rasterizes fleet sprites with opaque pixels (WebGL-safe Uint8Array)", () => {
    if (!canRasterize()) return;
    for (const type of FLEET) {
      const sprite = makeVehicleIcon(type, VEHICLE_COLOR[type]);
      expect(sprite.width).toBe(64);
      expect(sprite.data).toBeInstanceOf(Uint8ClampedArray);
      expect(opaquePixelCount(sprite)).toBeGreaterThan(80);
    }
  });

  it("rasterizes emergency sprites with opaque pixels", () => {
    if (!canRasterize()) return;
    for (const kind of EMERGENCY) {
      const sprite = makeEmergencyIcon(kind, "#ff5470");
      expect(sprite.width).toBe(80);
      expect(opaquePixelCount(sprite)).toBeGreaterThan(120);
    }
  });

  it("rasterizes visibly different ambulance beacon phases", () => {
    if (!canRasterize()) return;
    const red = makeEmergencyIcon("ambulance", "#ff5470", 80, true);
    const blue = makeEmergencyIcon("ambulance", "#ff5470", 80, false);
    expect([...red.data]).not.toEqual([...blue.data]);
  });
});
