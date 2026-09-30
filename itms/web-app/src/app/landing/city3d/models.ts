import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

/**
 * Vehicle bodies for the 3D city, modelled from side profiles.
 *
 * Each body is a few extruded silhouettes with rounded (bevelled) edges: the
 * lower body in paint, the glasshouse in tinted glass, a painted roof cap on
 * top. Parts are merged per material so every vehicle type draws as a
 * handful of instanced meshes, whatever the traffic count.
 *
 * Vehicle space: +x forward, +y up, z across; the ground is y = 0; metres.
 */

export type Kind = "hatch" | "sedan" | "suv" | "auto" | "bike" | "bus" | "ambulance";
export type Slot = "paint" | "accent" | "glass" | "dark" | "head" | "tail";
export const SLOTS: Slot[] = ["paint", "accent", "glass", "dark", "head", "tail"];

export interface Model {
  kind: Kind;
  len: number;
  wid: number;
  parts: Partial<Record<Slot, THREE.BufferGeometry>>;
  /** wheel centres [x, z] and radius / tyre width */
  wheels: [number, number][];
  wheelR: number;
  wheelW: number;
}

type P = [number, number][];

function extrude(pts: P, width: number, bevel = 0.07) {
  const shape = new THREE.Shape(pts.map(([x, y]) => new THREE.Vector2(x, y)));
  const depth = Math.max(0.01, width - 2 * bevel);
  const g = new THREE.ExtrudeGeometry(shape, {
    depth,
    bevelEnabled: bevel > 0,
    bevelThickness: bevel,
    bevelSize: bevel,
    bevelSegments: 3,
    curveSegments: 6,
  });
  g.translate(0, 0, -depth / 2);
  return g;
}

function box(w: number, h: number, d: number, x: number, y: number, z: number) {
  return new THREE.BoxGeometry(w, h, d).translate(x, y, z);
}

function merge(gs: THREE.BufferGeometry[]) {
  const clean = gs.map((g) => {
    const n = g.index ? g.toNonIndexed() : g;
    for (const k of Object.keys(n.attributes)) if (k !== "position" && k !== "normal") n.deleteAttribute(k);
    return n;
  });
  const m = mergeGeometries(clean, false)!;
  m.computeBoundingSphere();
  return m;
}

/** Head and tail lamps at both corners. */
function lamps(len: number, wid: number, y: number, inset = 0.16) {
  const z = wid / 2 - inset - 0.16;
  return {
    head: merge([box(0.06, 0.13, 0.34, len / 2, y, z), box(0.06, 0.13, 0.34, len / 2, y, -z)]),
    tail: merge([box(0.06, 0.14, 0.36, -len / 2, y + 0.04, z), box(0.06, 0.14, 0.36, -len / 2, y + 0.04, -z)]),
  };
}

function car(
  kind: Kind,
  len: number,
  wid: number,
  lower: P,
  cabin: P,
  roof: [number, number, number], // x0, x1, y
  lampY: number,
): Model {
  const cabW = wid - 0.2;
  const [r0, r1, ry] = roof;
  const parts: Model["parts"] = {
    paint: merge([
      extrude(lower, wid, 0.13),
      extrude(
        [
          [r0, ry - 0.05],
          [r1, ry - 0.05],
          [r1 - 0.04, ry + 0.03],
          [r0 + 0.04, ry + 0.04],
        ],
        cabW - 0.02,
        0.04,
      ),
    ]),
    glass: merge([extrude(cabin, cabW, 0.08)]),
    dark: merge([
      box(len - 0.5, 0.28, wid - 0.25, 0, 0.36, 0), // underbody fills the wheel arches
      box(0.12, 0.16, wid - 0.1, len / 2 - 0.02, 0.42, 0), // bumpers
      box(0.12, 0.16, wid - 0.1, -len / 2 + 0.02, 0.42, 0),
      box(0.16, 0.12, 0.1, len * 0.18, lampY + 0.32, wid / 2 + 0.06), // mirrors
      box(0.16, 0.12, 0.1, len * 0.18, lampY + 0.32, -wid / 2 - 0.06),
    ]),
    ...lamps(len, wid, lampY),
  };
  const wx = len / 2 - 0.78;
  const wz = wid / 2 - 0.2;
  return {
    kind,
    len,
    wid,
    parts,
    wheels: [
      [wx, wz],
      [wx, -wz],
      [-wx + 0.05, wz],
      [-wx + 0.05, -wz],
    ],
    wheelR: 0.32,
    wheelW: 0.22,
  };
}

function build(kind: Kind): Model {
  switch (kind) {
    case "hatch":
      return car(
        kind,
        3.8,
        1.7,
        [[-1.86, 0.3], [1.86, 0.3], [1.9, 0.62], [1.72, 0.82], [0.7, 0.92], [-1.78, 0.96], [-1.9, 0.72]],
        [[-1.74, 0.92], [0.72, 0.9], [0.18, 1.42], [-1.56, 1.44]],
        [-1.5, 0.14, 1.44],
        0.72,
      );
    case "sedan":
      return car(
        kind,
        4.5,
        1.78,
        [[-2.2, 0.3], [2.2, 0.3], [2.24, 0.6], [2.06, 0.8], [1.0, 0.9], [-1.45, 0.93], [-2.12, 0.88], [-2.25, 0.64]],
        [[-1.4, 0.9], [1.02, 0.88], [0.42, 1.38], [-0.86, 1.4]],
        [-0.8, 0.38, 1.4],
        0.7,
      );
    case "suv":
      return car(
        kind,
        4.6,
        1.88,
        [[-2.25, 0.34], [2.25, 0.34], [2.3, 0.72], [2.12, 0.98], [1.1, 1.06], [-2.18, 1.1], [-2.3, 0.84]],
        [[-2.16, 1.06], [1.12, 1.04], [0.55, 1.7], [-2.02, 1.74]],
        [-1.96, 0.5, 1.74],
        0.86,
      );
    case "auto": {
      // the three-wheeler: yellow-green lower body, black canvas hood, one nose wheel
      const parts: Model["parts"] = {
        paint: merge([extrude([[-1.3, 0.24], [1.08, 0.24], [1.36, 0.56], [1.26, 0.98], [0.92, 1.02], [-1.3, 1.02]], 1.34, 0.08)]),
        dark: merge([
          extrude([[-1.32, 1.0], [0.96, 1.0], [0.8, 1.74], [-1.22, 1.8]], 1.4, 0.07),
          box(0.12, 0.1, 1.2, -1.32, 0.4, 0),
        ]),
        glass: merge([box(0.06, 0.58, 1.08, 0.94, 1.34, 0)]),
        head: merge([box(0.08, 0.12, 0.16, 1.36, 0.7, 0)]),
        tail: merge([box(0.05, 0.1, 0.2, -1.33, 0.7, 0.48), box(0.05, 0.1, 0.2, -1.33, 0.7, -0.48)]),
      };
      return { kind, len: 2.7, wid: 1.4, parts, wheels: [[0.9, 0], [-0.85, 0.55], [-0.85, -0.55]], wheelR: 0.24, wheelW: 0.16 };
    }
    case "bike": {
      const parts: Model["parts"] = {
        paint: merge([extrude([[-0.7, 0.42], [0.6, 0.42], [0.72, 0.7], [0.1, 0.82], [-0.72, 0.7]], 0.32, 0.06)]),
        dark: merge([
          box(0.42, 0.62, 0.42, -0.12, 1.16, 0), // rider
          box(0.06, 0.06, 0.66, 0.5, 1.02, 0), // handlebar
          new THREE.SphereGeometry(0.16, 12, 10).translate(-0.05, 1.6, 0), // helmet
        ]),
        head: merge([box(0.06, 0.1, 0.12, 0.74, 0.72, 0)]),
        tail: merge([box(0.05, 0.08, 0.12, -0.74, 0.66, 0)]),
      };
      return { kind, len: 2.0, wid: 0.7, parts, wheels: [[0.66, 0], [-0.66, 0]], wheelR: 0.3, wheelW: 0.1 };
    }
    case "bus": {
      const L = 11;
      const W = 2.5;
      const parts: Model["parts"] = {
        paint: merge([extrude([[-L / 2, 0.42], [L / 2, 0.42], [L / 2, 3.0], [-L / 2, 3.0]], W, 0.16)]),
        accent: merge([box(L + 0.04, 0.26, W + 0.04, 0, 1.18, 0)]),
        glass: merge([box(L - 1.0, 0.92, W + 0.06, -0.3, 2.14, 0), box(0.08, 1.35, W - 0.3, L / 2 + 0.1, 1.95, 0)]),
        dark: merge([box(L - 1, 0.3, W - 0.2, 0, 0.42, 0), box(1.4, 0.26, 1.2, -1.5, 3.12, 0)]),
        ...lamps(L + 0.3, W, 0.75, 0.2),
      };
      return { kind, len: L, wid: W, parts, wheels: [[3.7, 1.05], [3.7, -1.05], [-3.4, 1.05], [-3.4, -1.05]], wheelR: 0.5, wheelW: 0.3 };
    }
    case "ambulance": {
      const W = 2.02;
      const parts: Model["parts"] = {
        paint: merge([
          extrude([[-2.62, 0.38], [0.92, 0.38], [0.92, 2.62], [-2.62, 2.62]], W, 0.1), // patient box
          extrude([[0.9, 0.38], [2.6, 0.38], [2.66, 0.86], [2.4, 1.1], [0.9, 1.14]], W - 0.1, 0.08), // cab
          box(0.8, 0.06, W - 0.3, 1.35, 1.95, 0), // cab roof
        ]),
        accent: merge([
          box(3.58, 0.24, W + 0.03, -0.85, 1.34, 0), // red band
          box(1.3, 0.04, 0.36, -0.9, 2.64, 0), // roof cross
          box(0.36, 0.04, 1.3, -0.9, 2.64, 0),
        ]),
        glass: merge([extrude([[0.92, 1.1], [2.34, 1.1], [1.78, 1.9], [0.92, 1.94]], W - 0.22, 0.05)]),
        dark: merge([box(4.6, 0.3, W - 0.3, 0, 0.38, 0), box(0.14, 0.16, W - 0.1, 2.62, 0.46, 0), box(0.2, 0.08, 1.5, 0.75, 2.66, 0)]),
        ...lamps(5.28, W, 0.74),
      };
      return { kind, len: 5.3, wid: W, parts, wheels: [[1.75, 0.82], [1.75, -0.82], [-1.7, 0.82], [-1.7, -0.82]], wheelR: 0.38, wheelW: 0.24 };
    }
  }
}

const cache = new Map<Kind, Model>();
export function model(kind: Kind) {
  let m = cache.get(kind);
  if (!m) cache.set(kind, (m = build(kind)));
  return m;
}

/** A unit tyre with a lighter hub, axis along z; scaled per vehicle. */
export function wheelGeometry() {
  const tyre = new THREE.CylinderGeometry(1, 1, 1, 20).rotateX(Math.PI / 2);
  return tyre;
}

export const PAINTS = {
  car: ["#e9ecef", "#e9ecef", "#f4f4f1", "#c2c7ce", "#a9afb8", "#7f8791", "#3b4048", "#1d2026", "#9a2327", "#b8352d", "#2d4f8e", "#40679f", "#6f5c49", "#c3b196"],
  auto: ["#e3bd2c", "#e3bd2c", "#3d8a4a"],
  bike: ["#1d2026", "#9a2327", "#2d4f8e", "#5b6068", "#c9ccd1"],
  bus: ["#eceee9", "#dfe3dc"],
  busAccent: ["#3a8f5a", "#c8412e", "#2e62b0"],
};
