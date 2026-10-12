import * as THREE from "three";
import { AV, CityWorld, clamp01, CROSS_X, ease, greenLeft, INCIDENT_X, lightOf, type Junction } from "./world";

/**
 * The landing page's 3D scenes. Each is a camera and a few story beats on
 * top of the same CityWorld:
 *
 *  - story:    the scroll-driven incident, from breakdown to the ambulance arriving
 *  - junction: one crossroads whose green time follows its queues
 *  - cctv:     the same breakdown as a traffic camera sees it, with detections
 *  - corridor: the ambulance run on a loop, lights turning green ahead of it
 */

export interface Scene3D {
  world: CityWorld;
  setRunning(on: boolean): void;
  dispose(): void;
}

const V = (x: number, y: number, z: number) => new THREE.Vector3(x, y, z);
const IX = INCIDENT_X;

// ------------------------------------------------------------ the ambulance's way in

function ambulancePath() {
  const p = new THREE.CurvePath<THREE.Vector3>();
  const lane = -AV.fast + 0.6; // hugging the median so traffic can make room on its left
  p.add(new THREE.LineCurve3(V(-163, 0, -22), V(-163, 0, -15)));
  p.add(new THREE.QuadraticBezierCurve3(V(-163, 0, -15), V(-163, 0, lane), V(-150, 0, lane)));
  p.add(new THREE.LineCurve3(V(-150, 0, lane), V(IX - 38, 0, lane)));
  p.add(new THREE.CubicBezierCurve3(V(IX - 38, 0, lane), V(IX - 28, 0, lane), V(IX - 26, 0, -AV.kerb - 0.4), V(IX - 16, 0, -AV.kerb - 0.4)));
  p.add(new THREE.LineCurve3(V(IX - 16, 0, -AV.kerb - 0.4), V(IX - 11, 0, -AV.kerb - 0.4)));
  return p;
}

function pose(path: THREE.CurvePath<THREE.Vector3>, d: number) {
  const L = path.getLength();
  const u = clamp01(d / L);
  const p = path.getPointAt(u);
  const t = path.getTangentAt(u);
  return { x: p.x, z: p.z, yaw: Math.atan2(-t.z, t.x) };
}

/** A glowing ribbon on the road along the route: cyan where planned, green where cleared. */
function routeRibbon(path: THREE.CurvePath<THREE.Vector3>) {
  const L = path.getLength();
  const n = Math.ceil(L);
  const pos: number[] = [];
  const along: number[] = [];
  const across: number[] = [];
  const idx: number[] = [];
  const half = 1.25;
  for (let i = 0; i <= n; i++) {
    const u = i / n;
    const p = path.getPointAt(u);
    const t = path.getTangentAt(u);
    const nx = -t.z;
    const nz = t.x;
    pos.push(p.x + nx * half, 0.07, p.z + nz * half, p.x - nx * half, 0.07, p.z - nz * half);
    along.push(u * L, u * L);
    across.push(1, -1);
    if (i) idx.push((i - 1) * 2, i * 2, (i - 1) * 2 + 1, i * 2, i * 2 + 1, (i - 1) * 2 + 1);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("aAlong", new THREE.Float32BufferAttribute(along, 1));
  g.setAttribute("aAcross", new THREE.Float32BufferAttribute(across, 1));
  g.setIndex(idx);
  const mat = new THREE.ShaderMaterial({
    uniforms: { uDrawn: { value: 0 }, uCleared: { value: 0 }, uTime: { value: 0 }, uOpacity: { value: 1 } },
    vertexShader: /* glsl */ `
      attribute float aAlong;
      attribute float aAcross;
      varying float vAlong;
      varying float vAcross;
      void main() {
        vAlong = aAlong;
        vAcross = aAcross;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: /* glsl */ `
      uniform float uDrawn;
      uniform float uCleared;
      uniform float uTime;
      uniform float uOpacity;
      varying float vAlong;
      varying float vAcross;
      void main() {
        if (vAlong > uDrawn) discard;
        float edge = 1.0 - smoothstep(0.45, 1.0, abs(vAcross));
        float cleared = step(vAlong, uCleared);
        vec3 col = mix(vec3(0.3, 0.78, 1.0), vec3(0.28, 1.0, 0.62), cleared);
        float flow = 0.5 + 0.5 * sin((vAlong - uTime * 9.0) * 0.32);
        float tip = smoothstep(uDrawn - 10.0, uDrawn, vAlong) * (1.0 - cleared);
        float a = edge * (0.5 + 0.45 * flow * (1.0 - cleared) + 0.7 * cleared + 0.9 * tip) * uOpacity;
        gl_FragColor = vec4(col * a * 1.4, 1.0);
      }`,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    toneMapped: false,
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.renderOrder = 4;
  return { mesh, mat, length: L };
}

/** A soft ring that breathes on the ground. */
function groundRing(color: string) {
  const mat = new THREE.MeshBasicMaterial({ color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false, opacity: 0 });
  const mesh = new THREE.Mesh(new THREE.RingGeometry(0.86, 1, 64).rotateX(-Math.PI / 2), mat);
  mesh.position.y = 0.08;
  mesh.renderOrder = 4;
  return { mesh, mat };
}

/** Hold each avenue light green from shortly before the ambulance until it has gone through. */
function preempt(world: CityWorld, active: boolean) {
  const a = world.amb;
  for (const x of CROSS_X) {
    const j = world.junctionAt(x, 0);
    const gap = x - (a?.x ?? -1e9);
    j.force = active && a?.on && a.z > -AV.half && gap > -14 && gap < 120 ? 0 : -1;
  }
}

// ------------------------------------------------------------ 2D overlay

class Overlay {
  readonly g: CanvasRenderingContext2D;
  constructor(
    private canvas: HTMLCanvasElement,
    private world: CityWorld,
  ) {
    this.g = canvas.getContext("2d")!;
  }
  begin() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.round(this.world.cw * dpr);
    const h = Math.round(this.world.ch * dpr);
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.g.setTransform(1, 0, 0, 1, 0, 0);
    this.g.clearRect(0, 0, w, h);
    this.g.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  /** A small label pinned above a world point. */
  pin(x: number, y: number, z: number, text: string, dot: string, alpha = 1) {
    if (alpha <= 0.01) return;
    const p = this.world.project(x, y, z);
    if (!p.ok) return;
    const g = this.g;
    g.save();
    g.globalAlpha = alpha;
    g.font = "600 12.5px 'Google Sans Flex', system-ui, sans-serif";
    const w = g.measureText(text).width + 30;
    g.fillStyle = "rgba(10,13,19,.82)";
    g.beginPath();
    g.roundRect(p.x - w / 2, p.y - 36, w, 26, 13);
    g.fill();
    g.fillStyle = "rgba(10,13,19,.82)";
    g.beginPath();
    g.moveTo(p.x - 5, p.y - 10.5);
    g.lineTo(p.x + 5, p.y - 10.5);
    g.lineTo(p.x, p.y - 4);
    g.fill();
    g.fillStyle = dot;
    g.beginPath();
    g.arc(p.x - w / 2 + 13, p.y - 23, 3.5, 0, Math.PI * 2);
    g.fill();
    g.fillStyle = "#eef2f6";
    g.textBaseline = "middle";
    g.fillText(text, p.x - w / 2 + 22, p.y - 22.5);
    g.restore();
  }
}

function lifecycle(world: CityWorld, extra: () => void = () => {}): Scene3D {
  return {
    world,
    setRunning: (on) => world.setRunning(on),
    dispose: () => {
      extra();
      world.dispose();
    },
  };
}

// ------------------------------------------------------------ 1. the scroll story

export interface StoryScene extends Scene3D {
  setStory(s: number): void;
}

export function createStory(canvas: HTMLCanvasElement, overlayCanvas: HTMLCanvasElement, reducedMotion: boolean): StoryScene {
  const world = new CityWorld(canvas, { reducedMotion, incident: true, ambulance: true, density: [1 / 24, 1 / 60], seed: 11 });
  const path = ambulancePath();
  const L = path.getLength();
  const ribbon = routeRibbon(path);
  world.scene.add(ribbon.mesh);
  const incRing = groundRing("#ff5a4e");
  const baseRing = groundRing("#58d6ff");
  world.scene.add(incRing.mesh, baseRing.mesh);
  const start = pose(path, 0);
  const overlay = new Overlay(overlayCanvas, world);
  const fog = world.scene.fog as THREE.FogExp2;

  let story = 0;
  let s = 0;
  const phases = (v: number) => ({
    // the breakdown is already flagged when the section opens
    detect: 0.45 + 0.55 * clamp01(v / 0.18),
    confirm: clamp01((v - 0.22) / 0.16),
    dispatch: clamp01((v - 0.42) / 0.18),
    clear: clamp01((v - 0.62) / 0.32),
  });

  // camera marks. Close shots stay over the carriageway (|z| < 7); the
  // buildings start at |z| = 14, so the lens never meets a wall.
  const A = { pos: V(IX - 22, 4.4, 4.6), look: V(IX, 0.8, -5.8) };
  const B = { pos: V(IX - 13, 2.9, 2.6), look: V(IX, 1.0, -5.9) };
  const C = { pos: V(-48, 245, 240), look: V(-48, 0, -12) };
  const E = { pos: V(IX - 31, 5.6, 5.4), look: V(IX - 9, 1.0, -5.6) };
  const pos = new THREE.Vector3();
  const look = new THREE.Vector3();
  const tmpP = new THREE.Vector3();
  const tmpL = new THREE.Vector3();

  /** Move towards `to` with height leading (rising) or trailing (landing) the ground track. */
  const glide = (from: THREE.Vector3, to: THREE.Vector3, u: number, rising: boolean, out: THREE.Vector3) => {
    const uy = rising ? 1 - Math.pow(1 - u, 3) : Math.pow(u, 3);
    const uxz = rising ? u * u : 1 - Math.pow(1 - u, 2);
    return out.set(from.x + (to.x - from.x) * uxz, from.y + (to.y - from.y) * uy, from.z + (to.z - from.z) * uxz);
  };

  const apply = (dt: number) => {
    s += (story - s) * (reducedMotion || dt === 0 ? 1 : 1 - Math.pow(0.0025, dt));
    const ph = phases(s);
    // pull away promptly, cruise, then ease to a stop behind the car
    const d = (1 - Math.pow(1 - ph.clear, 2.2)) * L;
    const amb = pose(path, d);
    world.setAmbulance(amb);
    preempt(world, ph.clear > 0 && ph.clear < 1);

    // 1. low and close on the breakdown, easing in as it is confirmed
    const k1 = ease(clamp01(s / 0.38));
    pos.lerpVectors(A.pos, B.pos, k1);
    look.lerpVectors(A.look, B.look, k1);
    // 2. lift straight up and back to see the whole way in from the hospital
    const up = ease(clamp01((s - 0.38) / 0.2));
    if (up > 0) {
      glide(tmpP.copy(pos), C.pos, up, true, pos);
      look.lerp(C.look, up);
    }
    // 3. come down behind the ambulance and ride along the avenue, then settle
    if (ph.clear > 0) {
      const chase = tmpP.set(amb.x - 21, 7.2, 5.6);
      const chaseLook = tmpL.set(amb.x + 16, 0.9, Math.max(-6, Math.min(-1, amb.z)));
      const land = ease(clamp01((ph.clear - 0.82) / 0.18));
      chase.lerp(E.pos, land);
      chaseLook.lerp(E.look, land);
      const f = ease(clamp01(ph.clear / 0.24));
      glide(C.pos, chase, f, false, pos);
      look.lerpVectors(C.look, chaseLook, f);
    }
    // a slow, breathing drift so the frame is never frozen
    const t = world.t;
    pos.x += Math.sin(t * 0.21) * 0.6;
    pos.y += Math.sin(t * 0.17) * 0.3;
    world.camPos.copy(pos);
    world.camLook.copy(look);
    fog.density = Math.min(0.006, 0.62 / pos.distanceTo(look));

    ribbon.mat.uniforms.uDrawn!.value = ease(ph.dispatch) * L;
    ribbon.mat.uniforms.uCleared!.value = d;
    ribbon.mat.uniforms.uTime!.value = t;
    // full strength from the air, softer at street level so it never floods the frame
    const high = clamp01((pos.y - 10) / 60);
    ribbon.mat.uniforms.uOpacity!.value = (0.32 + 0.68 * high) * (1 - ease(clamp01((ph.clear - 0.9) / 0.1)) * 0.6);

    const q = (t * 0.55) % 1;
    const car = world.incidentCar!;
    incRing.mesh.position.set(car.x, 0.08, car.z);
    incRing.mesh.scale.setScalar(2.5 + q * 5);
    incRing.mat.opacity = ph.detect * (1 - q) * 0.9 * (1 - ph.clear);
    baseRing.mesh.position.set(start.x, 0.08, start.z);
    baseRing.mesh.scale.setScalar(3 + q * 5);
    baseRing.mat.opacity = ph.dispatch * (1 - q) * 0.8 * (1 - ph.clear);
  };

  world.onFrame = apply;
  world.onOverlay = () => {
    overlay.begin();
    const ph = phases(s);
    const car = world.incidentCar!;
    overlay.pin(car.x, 3.2, car.z, "Broken-down car", "#ff5a4e", clamp01(ph.detect * 3) * (1 - ph.clear));
    overlay.pin(start.x, 5, start.z, "Hospital", "#58d6ff", clamp01(ph.dispatch * 3) * (1 - ph.clear));
  };

  apply(0);
  world.renderOnce();
  return {
    ...lifecycle(world, () => ribbon.mesh.geometry.dispose()),
    setStory(v: number) {
      story = clamp01(v);
      if (!world.isRunning) world.renderOnce();
    },
  };
}

// ------------------------------------------------------------ 2. adaptive junction

export interface JunctionState {
  waiting: [number, number];
  green: [number, number];
  active: 0 | 1 | -1;
  left: number;
}

export function createJunction(canvas: HTMLCanvasElement, reducedMotion: boolean, onState: (s: JunctionState) => void): Scene3D {
  const world = new CityWorld(canvas, { reducedMotion, density: [1 / 18, 1 / 30], seed: 5 });
  const j: Junction = world.junctionAt(0, 0);
  j.green = [14, 7];
  const fog = world.scene.fog as THREE.FogExp2;
  let last: 0 | 1 | -1 = -1;
  let acc = 0;
  world.onFrame = (dt) => {
    const t = world.t;
    // looking up the cross street into the junction, between the building rows
    world.camPos.set(1.2 + Math.sin(t * 0.09) * 1.2, 26 + Math.sin(t * 0.07) * 0.6, 44);
    world.camLook.set(0, 0, -3);
    fog.density = 0.0065;
    const g0 = lightOf(j, 0, t) === "g";
    const g1 = lightOf(j, 1, t) === "g";
    const active: 0 | 1 | -1 = g0 ? 0 : g1 ? 1 : -1;
    const waiting = world.queued(j);
    // plan the next cycle from the queues as each main-road green begins
    if (active !== last && active === 0) {
      j.green = [Math.round(Math.min(24, Math.max(8, 6 + waiting[0] * 1.1))), Math.round(Math.min(15, Math.max(5, 4 + waiting[1] * 1.1)))];
    }
    last = active;
    acc += dt;
    if (acc > 0.25 || dt === 0) {
      acc = 0;
      onState({ waiting, green: j.green, active, left: active === -1 ? 0 : greenLeft(j, active, t) });
    }
  };
  world.renderOnce();
  return lifecycle(world);
}

// ------------------------------------------------------------ 3. the camera's view

export function createCctv(canvas: HTMLCanvasElement, overlayCanvas: HTMLCanvasElement, reducedMotion: boolean): Scene3D {
  const world = new CityWorld(canvas, { reducedMotion, incident: true, density: [1 / 20, 1 / 60], seed: 9, shadows: true });
  const overlay = new Overlay(overlayCanvas, world);
  const fog = world.scene.fog as THREE.FogExp2;
  world.onFrame = () => {
    // a camera on an overhead gantry above the eastbound lanes, looking down the avenue
    world.camPos.set(IX - 38, 9.5, -4);
    world.camLook.set(IX + 10, 0, -4.5);
    fog.density = 0.009;
  };
  const born = world.t - 41;
  const H: Record<string, number> = { bus: 3.1, auto: 1.8, bike: 1.7, suv: 1.75, ambulance: 2.7 };
  const label: Record<string, string> = { bike: "bike", auto: "auto", bus: "bus", hatch: "car", sedan: "car", suv: "car" };
  world.onOverlay = () => {
    overlay.begin();
    const g = overlay.g;
    g.font = "600 10.5px 'Google Sans Code', ui-monospace, monospace";
    g.textBaseline = "middle";
    const cam = world.camPos;
    for (const v of world.vehicles) {
      if (v.hidden) continue;
      const dx = v.x - cam.x;
      if (dx < 8 || dx > 72 || Math.abs(v.z) > AV.half) continue;
      const hl = v.m.len / 2;
      const hw = v.m.wid / 2;
      const h = H[v.kind] ?? 1.45;
      let x0 = Infinity;
      let y0 = Infinity;
      let x1 = -Infinity;
      let y1 = -Infinity;
      const c = Math.cos(v.yaw);
      const s = Math.sin(v.yaw);
      for (const fx of [-1, 1])
        for (const fz of [-1, 1])
          for (const y of [0, h]) {
            const lx = fx * hl;
            const lz = fz * hw;
            const p = world.project(v.x + lx * c + lz * s, y, v.z - lx * s + lz * c);
            x0 = Math.min(x0, p.x);
            y0 = Math.min(y0, p.y);
            x1 = Math.max(x1, p.x);
            y1 = Math.max(y1, p.y);
          }
      if (x1 < 0 || x0 > world.cw || y1 < 0 || y0 > world.ch) continue;
      const flagged = v.fixed;
      g.strokeStyle = flagged ? "#ff4a3d" : "rgba(130,230,255,.9)";
      g.lineWidth = flagged ? 2 : 1.2;
      g.strokeRect(x0, y0, x1 - x0, y1 - y0);
      const secs = Math.floor(world.t - born);
      const text = flagged ? `stopped in lane  0:${String(secs % 60).padStart(2, "0")}` : `${label[v.kind] ?? "car"} ${(0.86 + ((v.id * 37) % 13) / 100).toFixed(2)}`;
      const tw = g.measureText(text).width + 8;
      g.fillStyle = flagged ? "#ff4a3d" : "rgba(8,36,44,.85)";
      g.fillRect(x0, y0 - 16, tw, 15);
      g.fillStyle = flagged ? "#fff" : "#c8f4ff";
      g.fillText(text, x0 + 4, y0 - 8);
    }
  };
  world.renderOnce();
  return lifecycle(world);
}

// ------------------------------------------------------------ 4. corridor on a loop

export function createCorridorLoop(canvas: HTMLCanvasElement, overlayCanvas: HTMLCanvasElement, reducedMotion: boolean): Scene3D {
  const world = new CityWorld(canvas, { reducedMotion, incident: true, ambulance: true, density: [1 / 26, 1 / 70], seed: 3 });
  const path = ambulancePath();
  const L = path.getLength();
  const ribbon = routeRibbon(path);
  world.scene.add(ribbon.mesh);
  const overlay = new Overlay(overlayCanvas, world);
  const fog = world.scene.fog as THREE.FogExp2;
  const start = pose(path, 0);
  const RUN = 18;
  const HOLD = 3;
  let clock = reducedMotion ? RUN + 1 : 0;
  world.onFrame = (dt) => {
    clock = (clock + dt) % (RUN + HOLD + 1);
    const f = clamp01((clock - 1) / RUN);
    const d = ease(f) * L;
    const amb = pose(path, d);
    world.setAmbulance(amb);
    preempt(world, f > 0 && f < 1);
    // a drone following the run from above the rooftops on the south side
    const cx = Math.max(-150, Math.min(IX - 20, amb.x));
    world.camPos.set(cx - 62, 50, 11);
    world.camLook.set(cx + 18, 0, -3);
    fog.density = 0.004;
    ribbon.mat.uniforms.uDrawn!.value = L;
    ribbon.mat.uniforms.uCleared!.value = d;
    ribbon.mat.uniforms.uTime!.value = world.t;
  };
  world.onOverlay = () => {
    overlay.begin();
    const car = world.incidentCar!;
    overlay.pin(car.x, 3, car.z, "Broken-down car", "#ff5a4e");
    overlay.pin(start.x, 5, start.z, "Hospital", "#58d6ff");
  };
  world.renderOnce();
  return lifecycle(world, () => ribbon.mesh.geometry.dispose());
}
