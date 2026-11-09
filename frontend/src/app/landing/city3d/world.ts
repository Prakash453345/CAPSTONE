import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { model, PAINTS, SLOTS, wheelGeometry, type Kind, type Model, type Slot } from "./models";

/**
 * A miniature city at blue hour, rendered with three.js.
 *
 * One avenue runs east to west through the middle, with cross streets every
 * 60 m and two quieter streets parallel to it. Traffic keeps left, holds a
 * safe gap to the vehicle ahead (the Intelligent Driver Model), stops for red
 * lights, merges around a broken-down car and makes way for an ambulance.
 *
 * The landing page's scenes (see scenes.ts) are camera moves and story beats
 * on top of this one world. Units are metres; +x east, +z south, +y up.
 */

// ------------------------------------------------------------ layout

export const AV = { half: 7.9, fast: 2.35, kerb: 5.55, median: 0.75 };
export const ST = { half: 3.6, lane: 1.8 };
export const CROSS_X = [-180, -120, -60, 0, 60, 120, 180];
export const STREET_Z = [-74, 74];
const X0 = -250;
const X1 = 250;
const Z0 = -160;
const Z1 = 160;
const WALK = 3.4; // pavement width
const WALK_AV = 6.2; // the avenue's tree-lined pavements are wider
const ZEBRA = 3.2;

export const INCIDENT_X = 95;
export const HOSPITAL = { x0: -173, x1: -127, z0: -66, z1: -12 };

const clamp01 = (t: number) => Math.min(1, Math.max(0, t));
export const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
export const smooth = (t: number) => t * t * (3 - 2 * t);

function rng(seed: number) {
  let s = seed;
  return () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646;
}

// ------------------------------------------------------------ signals

export interface Junction {
  x: number;
  z: number;
  /** group 0 = east-west traffic, group 1 = north-south */
  green: [number, number];
  offset: number;
  force: -1 | 0 | 1;
  heads: { group: 0 | 1; idx: number }[];
}

const AMBER = 3;
const ALL_RED = 1.5;

export function lightOf(j: Junction, group: 0 | 1, t: number): "g" | "a" | "r" {
  if (j.force >= 0) return j.force === group ? "g" : "r";
  const [g0, g1] = j.green;
  const cyc = g0 + g1 + 2 * (AMBER + ALL_RED);
  const u = (((t + j.offset) % cyc) + cyc) % cyc;
  const start = group === 0 ? 0 : g0 + AMBER + ALL_RED;
  const len = group === 0 ? g0 : g1;
  const v = u - start;
  if (v >= 0 && v < len) return "g";
  if (v >= len && v < len + AMBER) return "a";
  return "r";
}

export function greenLeft(j: Junction, group: 0 | 1, t: number) {
  if (j.force >= 0 || lightOf(j, group, t) !== "g") return 0;
  const [g0, g1] = j.green;
  const cyc = g0 + g1 + 2 * (AMBER + ALL_RED);
  const u = (((t + j.offset) % cyc) + cyc) % cyc;
  return (group === 0 ? g0 : g1) - (u - (group === 0 ? 0 : g0 + AMBER + ALL_RED));
}

// ------------------------------------------------------------ lanes and vehicles

interface Stop {
  s: number;
  j: Junction;
  group: 0 | 1;
}

export interface Lane {
  axis: "x" | "z";
  dir: 1 | -1;
  c: number; // the lane centre's other coordinate
  min: number;
  max: number;
  speed: number;
  stops: Stop[];
  avenue: boolean;
  list: Vehicle[];
}

export interface Vehicle {
  id: number;
  kind: Kind;
  m: Model;
  slot: number; // index inside its kind's instanced meshes
  lane: Lane;
  s: number;
  v: number;
  v0: number;
  a: number;
  lat: number; // lateral offset from the lane centre (towards +z or +x)
  latGoal: number;
  fixed: boolean;
  hidden: boolean;
  x: number;
  z: number;
  yaw: number;
}

export interface WorldOptions {
  reducedMotion: boolean;
  /** traffic per metre of lane, on the avenue and elsewhere */
  density?: [number, number];
  incident?: boolean;
  ambulance?: boolean;
  seed?: number;
  shadows?: boolean;
}

export interface Ambulance {
  on: boolean;
  d: number;
  x: number;
  z: number;
  yaw: number;
  group: THREE.Group;
  beacons: THREE.MeshBasicMaterial[];
  lights: THREE.PointLight[];
}

// ------------------------------------------------------------ textures

function radialTexture(stops: [number, string][], size = 128) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  const gr = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [o, col] of stops) gr.addColorStop(o, col);
  g.fillStyle = gr;
  g.fillRect(0, 0, size, size);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** A headlight throw: bright at the bumper, spreading and fading down the road. */
function beamTexture() {
  const c = document.createElement("canvas");
  c.width = 128;
  c.height = 64;
  const g = c.getContext("2d")!;
  const img = g.createImageData(128, 64);
  for (let x = 0; x < 128; x++)
    for (let y = 0; y < 64; y++) {
      const u = x / 127;
      const v = (y - 31.5) / 31.5;
      const spread = 0.35 + u * 0.65;
      const across = Math.max(0, 1 - Math.pow(Math.abs(v) / spread, 2));
      const along = Math.pow(1 - u, 1.6) * Math.min(1, u * 12);
      const a = across * along;
      const i = (y * 128 + x) * 4;
      img.data[i] = 255;
      img.data[i + 1] = 255;
      img.data[i + 2] = 255;
      img.data[i + 3] = Math.round(a * 255);
    }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// ------------------------------------------------------------ materials

function buildingMaterial() {
  const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.88, metalness: 0 });
  mat.onBeforeCompile = (sh) => {
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vWP;\nvarying vec3 vON;")
      .replace(
        "#include <begin_vertex>",
        `#include <begin_vertex>
        vec4 wpB = vec4(transformed, 1.0);
        #ifdef USE_INSTANCING
          wpB = instanceMatrix * wpB;
        #endif
        vWP = (modelMatrix * wpB).xyz;
        vON = normal;`,
      );
    sh.fragmentShader = sh.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
        varying vec3 vWP;
        varying vec3 vON;
        float h21(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }`,
      )
      .replace(
        "#include <emissivemap_fragment>",
        `#include <emissivemap_fragment>
        if (abs(vON.y) < 0.5) {
          float u = abs(vON.x) > 0.5 ? vWP.z : vWP.x;
          vec2 block = floor(vWP.xz / 19.0);
          if (vWP.y > 3.6) {
            vec2 cell = vec2(u / 2.6, (vWP.y - 0.4) / 3.3);
            vec2 f = fract(cell);
            vec2 id = floor(cell);
            float win = smoothstep(0.26, 0.3, f.x) * smoothstep(0.74, 0.7, f.x) * smoothstep(0.3, 0.34, f.y) * smoothstep(0.78, 0.74, f.y);
            float seed = h21(id + block * 7.13 + vON.xz * 3.1);
            // whole floors of an office go dark together; homes are lit here and there
            float floorOn = step(0.35, h21(vec2(id.y, block.x + block.y * 3.0)));
            float lit = step(0.66, seed) * floorOn;
            vec3 warm = mix(vec3(1.0, 0.6, 0.3), vec3(1.0, 0.82, 0.58), h21(id * 1.7 + block));
            float glowUp = 0.75 + 0.25 * (1.0 - f.y);
            totalEmissiveRadiance += win * lit * warm * glowUp * (0.7 + 0.8 * h21(id + 3.0));
            totalEmissiveRadiance += win * (1.0 - lit) * vec3(0.012, 0.018, 0.035);
            diffuseColor.rgb *= 1.0 - win * 0.7;
          } else if (vWP.y > 0.5 && vWP.y < 3.2) {
            // shopfronts at street level
            float shop = step(0.4, h21(floor(vec2(u / 7.0, 0.0)) + block));
            float f = fract(u / 7.0);
            float glass = smoothstep(0.06, 0.1, f) * smoothstep(0.94, 0.9, f) * step(0.6, vWP.y) * step(vWP.y, 2.8);
            vec3 tint = mix(vec3(1.0, 0.78, 0.52), vec3(0.75, 0.9, 1.0), step(0.8, h21(floor(vec2(u / 7.0, 1.0)) + block)));
            totalEmissiveRadiance += glass * shop * tint * 0.9;
            diffuseColor.rgb *= 1.0 - glass * 0.6;
          }
        }`,
      );
  };
  return mat;
}

// ------------------------------------------------------------ the world

export class CityWorld {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera = new THREE.PerspectiveCamera(30, 1, 0.5, 1400);
  readonly lanes: Lane[] = [];
  readonly vehicles: Vehicle[] = [];
  readonly junctions: Junction[] = [];
  readonly amb: Ambulance | null = null;
  incidentCar: Vehicle | null = null;
  t = 0;
  /** where the camera sits and looks; scenes write these every frame */
  readonly camPos = new THREE.Vector3(0, 60, 80);
  readonly camLook = new THREE.Vector3(0, 0, 0);
  onFrame: ((dt: number) => void) | null = null;
  onOverlay: (() => void) | null = null;
  cw = 1;
  ch = 1;

  /** resolves once shaders are compiled and the first frame is drawn */
  readonly ready: Promise<void>;
  private compiled = false;
  private composer: EffectComposer;
  private bloom: UnrealBloomPass;
  private rnd: () => number;
  private raf = 0;
  private running = false;
  private last = 0;
  private ro: ResizeObserver;
  private sun: THREE.DirectionalLight;
  private shadowSpan = 0;
  private kinds = new Map<Kind, { meshes: Partial<Record<Slot, THREE.InstancedMesh>>; used: number }>();
  private wheels!: THREE.InstancedMesh;
  private beams!: THREE.InstancedMesh;
  private lampMesh!: THREE.InstancedMesh;
  private haloMesh!: THREE.InstancedMesh;
  private headCount = 0;
  private hazard: { mats: THREE.MeshBasicMaterial[]; light: THREE.PointLight; group: THREE.Group } | null = null;
  private disposables: { dispose(): void }[] = [];
  private tmpM = new THREE.Matrix4();
  private tmpQ = new THREE.Quaternion();
  private tmpV = new THREE.Vector3();
  private tmpS = new THREE.Vector3();
  private tmpC = new THREE.Color();
  private yAxis = new THREE.Vector3(0, 1, 0);

  constructor(
    private canvas: HTMLCanvasElement,
    private opts: WorldOptions,
  ) {
    this.rnd = rng(opts.seed ?? 7);
    const r = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      powerPreference: "high-performance",
      // without a usable GPU the panel stays still instead of stalling the page
      failIfMajorPerformanceCaveat: true,
    });
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.toneMappingExposure = 1.0;
    r.outputColorSpace = THREE.SRGBColorSpace;
    r.shadowMap.enabled = opts.shadows !== false;
    r.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer = r;

    // night: the same deep blue as the hero's avenue, with a warm city glow at the horizon
    const fogColor = new THREE.Color("#0b1020");
    this.scene.background = fogColor;
    this.scene.fog = new THREE.FogExp2(fogColor, 0.0048);
    this.scene.add(this.skyDome());
    const pm = new THREE.PMREMGenerator(r);
    const env = pm.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environment = env;
    this.scene.environmentIntensity = 0.22;
    this.disposables.push(env, pm);

    this.scene.add(new THREE.HemisphereLight(0x5d6fa0, 0x15110d, 0.6));
    this.sun = new THREE.DirectionalLight(0x9fb3ff, 0.55);
    this.sun.castShadow = opts.shadows !== false;
    this.sun.shadow.mapSize.set(2048, 2048);
    this.sun.shadow.bias = -0.0004;
    this.sun.shadow.normalBias = 0.03;
    this.sun.shadow.radius = 4;
    this.scene.add(this.sun, this.sun.target);

    this.buildGround();
    this.buildJunctions();
    this.buildBlocks();
    this.buildStreetLights();
    this.buildSignals();
    this.buildLanes();
    this.buildVehicles();
    if (opts.incident) this.placeIncident();
    if (opts.ambulance) (this as { amb: Ambulance | null }).amb = this.buildAmbulance();

    // let the queues form before the first frame
    for (let i = 0; i < 240; i++) this.step(0.1);
    this.syncInstances();

    // lamps, signals, headlights and beacons glow; the city itself stays below the threshold
    this.composer = new EffectComposer(r);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.7, 0.55, 0.92);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());
    this.disposables.push(this.composer);

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(canvas);
    this.resize();
    // compile off the main thread where the browser allows it, so nothing freezes
    this.ready = r
      .compileAsync(this.scene, this.camera)
      .catch(() => {})
      .then(() => {
        this.compiled = true;
        this.renderOnce();
      });
  }

  private skyDome() {
    const mat = new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      fog: false,
      vertexShader: /* glsl */ `
        varying vec3 vDir;
        void main() {
          vDir = normalize(position);
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }`,
      fragmentShader: /* glsl */ `
        varying vec3 vDir;
        void main() {
          float h = clamp(vDir.y, -0.2, 1.0);
          vec3 top = vec3(0.018, 0.026, 0.055);
          vec3 mid = vec3(0.045, 0.062, 0.12);
          vec3 glow = vec3(0.16, 0.1, 0.1);
          vec3 c = mix(mid, top, smoothstep(0.02, 0.5, h));
          c += glow * exp(-abs(h) * 18.0) * 0.7;
          gl_FragColor = vec4(c, 1.0);
        }`,
    });
    const dome = new THREE.Mesh(new THREE.SphereGeometry(1100, 32, 16), mat);
    dome.renderOrder = -1;
    return dome;
  }

  // ---------------------------------------------------------- lifecycle

  get isRunning() {
    return this.running;
  }

  setRunning(on: boolean) {
    if (on === this.running) return;
    this.running = on;
    if (on) {
      this.last = performance.now();
      this.raf = requestAnimationFrame(this.frame);
    } else cancelAnimationFrame(this.raf);
  }

  renderOnce() {
    this.onFrame?.(0);
    this.syncInstances();
    this.render();
  }

  dispose() {
    this.setRunning(false);
    this.ro.disconnect();
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.geometry) m.geometry.dispose();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
      else mat?.dispose();
    });
    this.disposables.forEach((d) => d.dispose());
    this.renderer.dispose();
  }

  private frame = (now: number) => {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this.frame);
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    const step = this.opts.reducedMotion ? 0 : dt;
    this.onFrame?.(step);
    if (step) this.step(step);
    this.syncInstances();
    this.render();
  };

  private resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.cw = Math.max(1, rect.width);
    this.ch = Math.max(1, rect.height);
    this.renderer.setSize(this.cw, this.ch, false);
    this.composer.setPixelRatio(this.renderer.getPixelRatio());
    this.composer.setSize(this.cw, this.ch);
    this.camera.aspect = this.cw / this.ch;
    this.camera.updateProjectionMatrix();
    if (!this.running && this.compiled) this.renderOnce();
  }

  private render() {
    if (!this.compiled) return;
    const cam = this.camera;
    cam.position.copy(this.camPos);
    cam.lookAt(this.camLook);
    // the shadow-casting light follows what the camera looks at
    const span = Math.min(170, Math.max(34, cam.position.distanceTo(this.camLook) * 0.62));
    if (Math.abs(span - this.shadowSpan) > this.shadowSpan * 0.08) {
      this.shadowSpan = span;
      const sc = this.sun.shadow.camera;
      sc.left = -span;
      sc.right = span;
      sc.top = span;
      sc.bottom = -span;
      sc.near = 10;
      sc.far = 420;
      sc.updateProjectionMatrix();
    }
    this.sun.target.position.copy(this.camLook);
    this.sun.position.copy(this.camLook).add(this.tmpV.set(-70, 150, 55));
    this.composer.render();
    this.onOverlay?.();
  }

  /** CSS pixel position of a world point, and whether it is in front of the camera. */
  project(x: number, y: number, z: number) {
    const v = this.tmpV.set(x, y, z).project(this.camera);
    return { x: (v.x * 0.5 + 0.5) * this.cw, y: (-v.y * 0.5 + 0.5) * this.ch, ok: v.z < 1 && v.z > -1 };
  }

  // ---------------------------------------------------------- building the city

  private mesh(geo: THREE.BufferGeometry, mat: THREE.Material, shadow: [boolean, boolean] = [false, true]) {
    const m = new THREE.Mesh(geo, mat);
    m.castShadow = shadow[0];
    m.receiveShadow = shadow[1];
    this.scene.add(m);
    return m;
  }

  private instanced(geo: THREE.BufferGeometry, mat: THREE.Material, items: THREE.Matrix4[], colors?: THREE.Color[], cast = true) {
    const m = new THREE.InstancedMesh(geo, mat, Math.max(1, items.length));
    items.forEach((it, i) => m.setMatrixAt(i, it));
    colors?.forEach((c, i) => m.setColorAt(i, c));
    m.count = items.length;
    m.castShadow = cast;
    m.receiveShadow = true;
    this.scene.add(m);
    return m;
  }

  private mat4(x: number, y: number, z: number, sx = 1, sy = 1, sz = 1, yaw = 0) {
    this.tmpQ.setFromAxisAngle(this.yAxis, yaw);
    return new THREE.Matrix4().compose(this.tmpV.set(x, y, z), this.tmpQ, this.tmpS.set(sx, sy, sz));
  }

  private buildGround() {
    const asphalt = new THREE.MeshStandardMaterial({ color: 0x1c2029, roughness: 0.82, metalness: 0.05 });
    const ground = new THREE.MeshStandardMaterial({ color: 0x12151b, roughness: 1 });
    this.mesh(new THREE.PlaneGeometry(1400, 1000).rotateX(-Math.PI / 2).translate(0, -0.02, 0), ground);

    // carriageways
    this.mesh(new THREE.PlaneGeometry(X1 - X0 + 200, AV.half * 2).rotateX(-Math.PI / 2).translate(0, 0.01, 0), asphalt);
    for (const z of STREET_Z)
      this.mesh(new THREE.PlaneGeometry(X1 - X0 + 200, ST.half * 2).rotateX(-Math.PI / 2).translate(0, 0.01, z), asphalt);
    for (const x of CROSS_X)
      this.mesh(new THREE.PlaneGeometry(ST.half * 2, Z1 - Z0 + 200).rotateX(-Math.PI / 2).translate(x, 0.011, 0), asphalt);

    // the avenue's raised median, broken at each junction, with low hedges
    const kerbMat = new THREE.MeshStandardMaterial({ color: 0x4a4f58, roughness: 0.8 });
    const shrubMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.95 });
    const medians: THREE.Matrix4[] = [];
    const shrubs: THREE.Matrix4[] = [];
    const shrubC: THREE.Color[] = [];
    const xs = [X0 - 100, ...CROSS_X, X1 + 100];
    for (let i = 0; i < xs.length - 1; i++) {
      const a = xs[i]! + ST.half + ZEBRA + 1;
      const b = xs[i + 1]! - ST.half - ZEBRA - 1;
      medians.push(this.mat4((a + b) / 2, 0.1, 0, b - a, 0.2, AV.median * 2));
      // low, rounded planting along the median
      for (let x = a + 1.5; x < b - 1.5; x += 1.6 + this.rnd() * 0.8) {
        const s = 0.45 + this.rnd() * 0.25;
        shrubs.push(this.mat4(x, 0.25, (this.rnd() - 0.5) * 0.3, s * 1.3, s * 0.8, s));
        shrubC.push(new THREE.Color().setHSL(0.36 + this.rnd() * 0.05, 0.35, 0.16 + this.rnd() * 0.06));
      }
    }
    this.instanced(new THREE.BoxGeometry(1, 1, 1), kerbMat, medians);
    this.instanced(new THREE.IcosahedronGeometry(1, 1), shrubMat, shrubs, shrubC);

    // markings
    const paint = new THREE.MeshStandardMaterial({ color: 0xd9dde3, roughness: 0.6, emissive: 0x20242a });
    const dashes: THREE.Matrix4[] = [];
    const flat = (x: number, z: number, lx: number, lz: number) => dashes.push(this.mat4(x, 0.025, z, lx, 1, lz));
    for (let i = 0; i < xs.length - 1; i++) {
      const a = xs[i]! + ST.half + ZEBRA + 0.5;
      const b = xs[i + 1]! - ST.half - ZEBRA - 0.5;
      for (let x = a + 1; x < b - 3; x += 9) for (const z of [-3.95, 3.95]) flat(x + 1.5, z, 3, 0.14);
      for (const z of [-AV.half + 0.45, AV.half - 0.45]) flat((a + b) / 2, z, b - a, 0.14);
      for (const z of STREET_Z) for (let x = a + 1; x < b - 3; x += 8) flat(x + 1.2, z, 2.4, 0.12);
    }
    const zs = [Z0 - 100, -AV.half, AV.half, Z1 + 100];
    for (const x of CROSS_X) {
      for (let k = 0; k < zs.length - 1; k++) {
        const lo = zs[k]! + (k === 0 ? 0 : ZEBRA + 0.5);
        const hi = zs[k + 1]! - (k === zs.length - 2 ? 0 : ZEBRA + 0.5);
        for (let z = lo + 1; z < hi - 3; z += 8) {
          const nearStreet = STREET_Z.some((sz) => Math.abs(z + 1.2 - sz) < ST.half + ZEBRA + 1.5);
          if (!nearStreet) flat(x, z + 1.2, 0.12, 2.4);
        }
      }
    }
    // zebra crossings on every arm of every junction
    for (const j of this.junctionSpots()) {
      const hx = ST.half;
      const hz = j.z === 0 ? AV.half : ST.half;
      for (const side of [-1, 1]) {
        const zc = j.z + side * (hz + ZEBRA / 2 + 0.3);
        for (let x = j.x - hx + 0.5; x <= j.x + hx - 0.4; x += 1.05) flat(x, zc, 0.55, ZEBRA);
        const xc = j.x + side * (hx + ZEBRA / 2 + 0.3);
        for (let z = j.z - hz + 0.5; z <= j.z + hz - 0.4; z += 1.05) flat(xc, z, ZEBRA, 0.55);
      }
    }
    this.instanced(new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2), paint, dashes, undefined, false);
  }

  private junctionSpots() {
    const out: { x: number; z: number }[] = [];
    for (const x of CROSS_X) for (const z of [0, ...STREET_Z]) out.push({ x, z });
    return out;
  }

  private buildJunctions() {
    for (const { x, z } of this.junctionSpots()) {
      this.junctions.push({
        x,
        z,
        green: z === 0 ? [16, 9] : [11, 11],
        offset: this.rnd() * 30,
        force: -1,
        heads: [],
      });
    }
  }

  junctionAt(x: number, z: number) {
    return this.junctions.find((j) => j.x === x && j.z === z)!;
  }

  private buildBlocks() {
    const pave = new THREE.MeshStandardMaterial({ color: 0x353a43, roughness: 0.85 });
    const slabs: THREE.Matrix4[] = [];
    const bld: THREE.Matrix4[] = [];
    const bldC: THREE.Color[] = [];
    const trunks: THREE.Matrix4[] = [];
    const crowns: THREE.Matrix4[] = [];
    const crownC: THREE.Color[] = [];
    const palette = ["#3a404d", "#434a57", "#4c5360", "#343a45", "#525866", "#3f4450", "#5a534c", "#4a4540", "#606774"];
    const greens = ["#1f3a28", "#27472f", "#1c3324", "#2d4e33"];
    const tree = (x: number, z: number, s = 1) => {
      trunks.push(this.mat4(x, 1.3 * s, z, 0.28 * s, 2.6 * s, 0.28 * s));
      const r = (2 + this.rnd() * 1.1) * s;
      crowns.push(this.mat4(x, 3.1 * s + r * 0.7, z, r, r * 0.9, r, this.rnd() * 6));
      crownC.push(new THREE.Color(greens[Math.floor(this.rnd() * greens.length)]!));
    };

    const xs = [X0 - 60, ...CROSS_X, X1 + 60];
    const zBands: [number, number][] = [
      [Z0 - 60, STREET_Z[0]! - ST.half],
      [STREET_Z[0]! + ST.half, -AV.half],
      [AV.half, STREET_Z[1]! - ST.half],
      [STREET_Z[1]! + ST.half, Z1 + 60],
    ];
    for (let i = 0; i < xs.length - 1; i++) {
      const bx0 = xs[i]! + ST.half;
      const bx1 = xs[i + 1]! - ST.half;
      for (const [bz0, bz1] of zBands) {
        slabs.push(this.mat4((bx0 + bx1) / 2, 0.08, (bz0 + bz1) / 2, bx1 - bx0, 0.16, bz1 - bz0));
        const lx0 = bx0 + WALK;
        const lx1 = bx1 - WALK;
        const lz0 = bz0 + (bz0 === AV.half ? WALK_AV : WALK);
        const lz1 = bz1 - (bz1 === -AV.half ? WALK_AV : WALK);
        const isHospital = lx0 < HOSPITAL.x1 && lx1 > HOSPITAL.x0 && lz1 <= -AV.half && lz0 > STREET_Z[0]!;
        if (isHospital) continue;
        const nearAvenue = Math.abs(bz0) < 10 || Math.abs(bz1) < 10;
        // parcels along x, one or two rows deep
        const depth = lz1 - lz0;
        const rows = depth > 34 ? 2 : 1;
        for (let r = 0; r < rows; r++) {
          const pz0 = lz0 + (depth / rows) * r + (r ? 1 : 0);
          const pz1 = lz0 + (depth / rows) * (r + 1) - (r === rows - 1 ? 0 : 1);
          let x = lx0;
          while (x < lx1 - 6) {
            const w = Math.min(lx1 - x, 12 + this.rnd() * 14);
            if (this.rnd() < 0.12) {
              // a small green in place of a building
              for (let k = 0; k < 3; k++) tree(x + 3 + this.rnd() * (w - 6), pz0 + 3 + this.rnd() * (pz1 - pz0 - 6));
            } else {
              const d = pz1 - pz0 - this.rnd() * 6;
              const onAv = nearAvenue && (r === 0 ? bz0 > 0 : bz1 < 0 ? r === rows - 1 : false);
              const h = (onAv ? 14 : 9) + Math.pow(this.rnd(), 1.6) * (onAv ? 30 : 22);
              const zc = r === 0 && bz0 > 0 ? pz0 + d / 2 : r === rows - 1 && bz1 < 0 ? pz1 - d / 2 : (pz0 + pz1) / 2;
              bld.push(this.mat4(x + w / 2, h / 2 + 0.16, zc, w - 1.4, h, d));
              bldC.push(new THREE.Color(palette[Math.floor(this.rnd() * palette.length)]!));
            }
            x += w;
          }
        }
      }
    }

    // street trees along the avenue
    for (let x = X0; x < X1; x += 14) {
      if (CROSS_X.some((c) => Math.abs(x - c) < ST.half + ZEBRA + 3)) continue;
      if (x > HOSPITAL.x0 - 4 && x < HOSPITAL.x1 + 4) continue;
      for (const s of [-1, 1]) tree(x + this.rnd() * 3, s * (AV.half + 2.6), 0.95);
    }

    this.instanced(new THREE.BoxGeometry(1, 1, 1), pave, slabs, undefined, false);
    const bm = this.instanced(new THREE.BoxGeometry(1, 1, 1), buildingMaterial(), bld, bldC);
    bm.castShadow = true;
    this.instanced(new THREE.CylinderGeometry(0.5, 0.6, 1, 6), new THREE.MeshStandardMaterial({ color: 0x3b2f27, roughness: 1 }), trunks);
    this.instanced(new THREE.IcosahedronGeometry(1, 1), new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.95 }), crowns, crownC);

    this.buildHospital();
  }

  private buildHospital() {
    const { x0, x1, z0, z1 } = HOSPITAL;
    const white = new THREE.MeshStandardMaterial({ color: 0xb9c0c8, roughness: 0.7 });
    const glass = new THREE.MeshPhysicalMaterial({ color: 0x1d2a36, roughness: 0.1, emissive: 0xffd9a8, emissiveIntensity: 0.55 });
    const w = x1 - x0;
    const main = this.mesh(new THREE.BoxGeometry(w, 18, 26).translate((x0 + x1) / 2, 9.16, z0 + 13), white, [true, true]);
    main.castShadow = true;
    // a low wing towards the avenue with a glass entrance
    this.mesh(new THREE.BoxGeometry(w * 0.6, 6, 14).translate((x0 + x1) / 2 + 4, 3.16, z1 - 13), white, [true, true]).castShadow = true;
    this.mesh(new THREE.BoxGeometry(w * 0.6 - 2, 4, 0.2).translate((x0 + x1) / 2 + 4, 2.2, z1 - 5.9), glass);
    // canopy over the ambulance bay
    this.mesh(new THREE.BoxGeometry(12, 0.3, 7).translate(-150, 4.2, z1 - 2), white, [true, true]).castShadow = true;
    // the red cross, lit, on the facade facing the avenue and on the roof
    const red = new THREE.MeshBasicMaterial({ color: new THREE.Color(1.6, 0.12, 0.14), toneMapped: false });
    const cx = (x0 + x1) / 2;
    for (const [w2, h2] of [
      [5.2, 1.6],
      [1.6, 5.2],
    ] as const) {
      this.mesh(new THREE.BoxGeometry(w2, h2, 0.3).translate(cx, 13, z0 + 26.2), red, [false, false]);
      this.mesh(new THREE.BoxGeometry(w2 * 1.6, 0.2, h2 * 1.6).translate(cx - 8, 18.3, z0 + 12), red, [false, false]);
    }
    // the bay and driveway down to the avenue
    const asphalt = new THREE.MeshStandardMaterial({ color: 0x2a2e35, roughness: 0.9 });
    this.mesh(new THREE.PlaneGeometry(14, z1 - (z0 + 27) + 6).rotateX(-Math.PI / 2).translate(-150, 0.17, (z0 + 27 + (-AV.half)) / 2), asphalt);
    const glow = new THREE.PointLight(0xff4a4a, 30, 30, 2);
    glow.position.set(cx, 13, z0 + 29);
    this.scene.add(glow);
  }

  private buildStreetLights() {
    const poleMat = new THREE.MeshStandardMaterial({ color: 0x2c3038, roughness: 0.6, metalness: 0.4 });
    const lampMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(2.2, 1.55, 0.95), toneMapped: false });
    const poolTex = radialTexture([
      [0, "rgba(255,200,140,0.55)"],
      [0.35, "rgba(255,180,110,0.25)"],
      [1, "rgba(255,170,100,0)"],
    ]);
    const poolMat = new THREE.MeshBasicMaterial({ map: poolTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false });
    this.disposables.push(poolTex);
    const poles: THREE.Matrix4[] = [];
    const arms: THREE.Matrix4[] = [];
    const heads: THREE.Matrix4[] = [];
    const pools: THREE.Matrix4[] = [];
    const add = (x: number, z: number, towards: number, road: "x" | "z") => {
      poles.push(this.mat4(x, 4.2, z, 0.16, 8.4, 0.16));
      if (road === "x") {
        arms.push(this.mat4(x, 8.3, z + towards * 0.9, 0.1, 0.1, 1.8));
        heads.push(this.mat4(x, 8.2, z + towards * 1.8, 0.7, 0.14, 0.34));
        pools.push(this.mat4(x, 0.035, z + towards * 4.2, 17, 1, 15));
      } else {
        arms.push(this.mat4(x + towards * 0.9, 8.3, z, 1.8, 0.1, 0.1));
        heads.push(this.mat4(x + towards * 1.8, 8.2, z, 0.34, 0.14, 0.7));
        pools.push(this.mat4(x + towards * 3.2, 0.035, z, 14, 1, 16));
      }
    };
    for (let x = X0 + 7; x < X1; x += 30) {
      if (CROSS_X.some((c) => Math.abs(x - c) < ST.half + ZEBRA + 2)) continue;
      add(x, -(AV.half + 0.5), 1, "x");
      add(x + 15, AV.half + 0.5, -1, "x");
      for (const z of STREET_Z) add(x + 6, z - ST.half - 0.5, 1, "x");
    }
    for (const x of CROSS_X)
      for (let z = Z0; z < Z1; z += 34) {
        if (Math.abs(z) < AV.half + 6 || STREET_Z.some((s) => Math.abs(z - s) < ST.half + 6)) continue;
        add(x + ST.half + 0.5, z, -1, "z");
      }
    this.instanced(new THREE.CylinderGeometry(0.5, 0.6, 1, 8), poleMat, poles);
    this.instanced(new THREE.BoxGeometry(1, 1, 1), poleMat, arms);
    this.instanced(new THREE.BoxGeometry(1, 1, 1), lampMat, heads, undefined, false);
    this.instanced(new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2), poolMat, pools, undefined, false).renderOrder = 2;
  }

  private buildSignals() {
    const poleMat = new THREE.MeshStandardMaterial({ color: 0x2a2e35, roughness: 0.55, metalness: 0.5 });
    const headMat = new THREE.MeshStandardMaterial({ color: 0x14161a, roughness: 0.5 });
    const lampMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(1, 1, 1), toneMapped: false });
    const haloTex = radialTexture([
      [0, "rgba(255,255,255,0.9)"],
      [0.25, "rgba(255,255,255,0.35)"],
      [1, "rgba(255,255,255,0)"],
    ]);
    this.disposables.push(haloTex);
    const haloMat = new THREE.MeshBasicMaterial({ map: haloTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false });
    const poles: THREE.Matrix4[] = [];
    const heads: THREE.Matrix4[] = [];
    const lamps: THREE.Matrix4[] = [];
    const halos: THREE.Matrix4[] = [];
    let idx = 0;
    for (const j of this.junctions) {
      const hz = j.z === 0 ? AV.half : ST.half;
      const hx = ST.half;
      // one head per approach, on the near-left corner (traffic keeps left)
      const approaches: [number, number, number, 0 | 1][] = [
        [j.x - hx - ZEBRA - 1.2, j.z - hz - 1.1, -Math.PI / 2, 0], // eastbound, faces west
        [j.x + hx + ZEBRA + 1.2, j.z + hz + 1.1, Math.PI / 2, 0], // westbound
        [j.x + hx + 1.1, j.z - hz - ZEBRA - 1.2, Math.PI, 1], // southbound, faces north
        [j.x - hx - 1.1, j.z + hz + ZEBRA + 1.2, 0, 1], // northbound
      ];
      for (const [x, z, yaw, group] of approaches) {
        poles.push(this.mat4(x, 2.4, z, 0.14, 4.8, 0.14));
        heads.push(this.mat4(x, 4.4, z, 0.42, 1.2, 0.36, yaw));
        // lamps sit on the face of the head that points at oncoming traffic
        const fx = Math.sin(yaw) * 0.2;
        const fz = Math.cos(yaw) * 0.2;
        for (const dy of [0.36, 0, -0.36]) {
          lamps.push(this.mat4(x + fx, 4.4 + dy, z + fz, 0.26, 0.26, 0.26));
          halos.push(this.mat4(x + fx * 1.5, 4.4 + dy, z + fz * 1.5, 1.5, 1.5, 1.5, yaw));
        }
        j.heads.push({ group, idx: idx++ });
      }
    }
    this.headCount = idx;
    this.instanced(new THREE.CylinderGeometry(0.5, 0.5, 1, 8), poleMat, poles);
    this.instanced(new THREE.BoxGeometry(1, 1, 1), headMat, heads);
    this.lampMesh = this.instanced(new THREE.SphereGeometry(0.5, 12, 10), lampMat, lamps, lamps.map(() => new THREE.Color(0x111111)), false);
    this.haloMesh = this.instanced(new THREE.PlaneGeometry(1, 1), haloMat, halos, halos.map(() => new THREE.Color(0)), false);
    this.haloMesh.renderOrder = 3;
  }

  private updateSignals() {
    const col = { r: [1.9, 0.18, 0.12], a: [1.9, 1.0, 0.1], g: [0.2, 1.9, 0.9] } as const;
    const dim = { r: [0.14, 0.02, 0.02], a: [0.14, 0.09, 0.02], g: [0.02, 0.12, 0.07] } as const;
    const order = ["r", "a", "g"] as const;
    for (const j of this.junctions)
      for (const h of j.heads) {
        const state = lightOf(j, h.group, this.t);
        order.forEach((name, k) => {
          const on = state === name;
          const c = on ? col[name] : dim[name];
          this.lampMesh.setColorAt(h.idx * 3 + k, this.tmpC.setRGB(c[0], c[1], c[2]));
          const hc = on ? col[name] : [0, 0, 0];
          this.haloMesh.setColorAt(h.idx * 3 + k, this.tmpC.setRGB(hc[0] * 0.3, hc[1] * 0.3, hc[2] * 0.3));
        });
      }
    this.lampMesh.instanceColor!.needsUpdate = true;
    this.haloMesh.instanceColor!.needsUpdate = true;
    // halos always face the camera
    const q = this.camera.quaternion;
    for (let i = 0; i < this.headCount * 3; i++) {
      this.haloMesh.getMatrixAt(i, this.tmpM);
      this.tmpM.decompose(this.tmpV, this.tmpQ, this.tmpS);
      this.tmpM.compose(this.tmpV, q, this.tmpS);
      this.haloMesh.setMatrixAt(i, this.tmpM);
    }
    this.haloMesh.instanceMatrix.needsUpdate = true;
  }

  // ---------------------------------------------------------- traffic

  private buildLanes() {
    const lane = (axis: "x" | "z", dir: 1 | -1, c: number, avenue: boolean): Lane => ({
      axis,
      dir,
      c,
      min: axis === "x" ? X0 : Z0,
      max: axis === "x" ? X1 : Z1,
      speed: avenue ? 12.5 : 9,
      stops: [],
      avenue,
      list: [],
    });
    // avenue: eastbound on the north side, two lanes each way
    this.lanes.push(lane("x", 1, -AV.fast, true), lane("x", 1, -AV.kerb, true), lane("x", -1, AV.fast, true), lane("x", -1, AV.kerb, true));
    for (const z of STREET_Z) this.lanes.push(lane("x", 1, z - ST.lane, false), lane("x", -1, z + ST.lane, false));
    for (const x of CROSS_X) this.lanes.push(lane("z", 1, x + ST.lane, false), lane("z", -1, x - ST.lane, false));

    for (const l of this.lanes) {
      for (const j of this.junctions) {
        if (l.axis === "x") {
          if (Math.abs(l.c - j.z) > (j.z === 0 ? AV.half : ST.half)) continue;
          l.stops.push({ s: j.x - l.dir * (ST.half + ZEBRA + 0.9), j, group: 0 });
        } else {
          if (Math.abs(l.c - j.x) > ST.half) continue;
          const hz = j.z === 0 ? AV.half : ST.half;
          l.stops.push({ s: j.z - l.dir * (hz + ZEBRA + 0.9), j, group: 1 });
        }
      }
      l.stops.sort((a, b) => (a.s - b.s) * l.dir);
    }
  }

  get eastFast() {
    return this.lanes[0]!;
  }
  get eastKerb() {
    return this.lanes[1]!;
  }

  private pickKind(avenue: boolean): Kind {
    const r = this.rnd();
    if (r < (avenue ? 0.05 : 0.02)) return "bus";
    if (r < 0.2) return "bike";
    if (r < 0.34) return "auto";
    if (r < 0.58) return "hatch";
    if (r < 0.84) return "sedan";
    return "suv";
  }

  private buildVehicles() {
    const [dAv, dSt] = this.opts.density ?? [1 / 26, 1 / 55];
    const planned: { lane: Lane; s: number; kind: Kind }[] = [];
    for (const l of this.lanes) {
      const dens = l.avenue ? dAv : dSt;
      let s = l.min + this.rnd() * 20;
      while (s < l.max) {
        planned.push({ lane: l, s, kind: this.pickKind(l.avenue) });
        s += (0.6 + this.rnd() * 0.8) / dens;
      }
    }
    // the ambulance and the broken-down car need a sedan slot and their own meshes
    const counts = new Map<Kind, number>();
    for (const p of planned) counts.set(p.kind, (counts.get(p.kind) ?? 0) + 1);
    counts.set("sedan", (counts.get("sedan") ?? 0) + 1);

    const mats: Record<Slot, THREE.Material> = {
      paint: new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.3, metalness: 0.15, clearcoat: 1, clearcoatRoughness: 0.06 }),
      accent: new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.45 }),
      glass: new THREE.MeshPhysicalMaterial({ color: 0x0c1118, roughness: 0.04, metalness: 0.1, clearcoat: 1, clearcoatRoughness: 0.02 }),
      dark: new THREE.MeshStandardMaterial({ color: 0x17191d, roughness: 0.75 }),
      head: new THREE.MeshBasicMaterial({ color: new THREE.Color(2.2, 2.05, 1.8), toneMapped: false }),
      tail: new THREE.MeshBasicMaterial({ color: new THREE.Color(1, 1, 1), toneMapped: false }),
    };
    let wheelTotal = 0;
    for (const [kind, n] of counts) {
      const m = model(kind);
      const meshes: Partial<Record<Slot, THREE.InstancedMesh>> = {};
      for (const slot of SLOTS) {
        const geo = m.parts[slot];
        if (!geo) continue;
        const im = new THREE.InstancedMesh(geo, mats[slot], n);
        im.castShadow = slot === "paint" || slot === "dark";
        im.receiveShadow = slot === "paint";
        im.frustumCulled = false;
        this.scene.add(im);
        meshes[slot] = im;
      }
      this.kinds.set(kind, { meshes, used: 0 });
      wheelTotal += n * m.wheels.length;
    }
    this.wheels = new THREE.InstancedMesh(wheelGeometry(), new THREE.MeshStandardMaterial({ color: 0x121316, roughness: 0.7 }), wheelTotal + 4);
    this.wheels.frustumCulled = false;
    this.scene.add(this.wheels);
    const beamTex = beamTexture();
    this.disposables.push(beamTex);
    this.beams = new THREE.InstancedMesh(
      new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2).translate(0.5, 0, 0),
      new THREE.MeshBasicMaterial({ map: beamTex, color: 0xfff0d6, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0.4, toneMapped: false }),
      planned.length + 4,
    );
    this.beams.frustumCulled = false;
    this.beams.renderOrder = 2;
    this.scene.add(this.beams);

    for (const p of planned) this.addVehicle(p.kind, p.lane, p.s);
  }

  private addVehicle(kind: Kind, lane: Lane, s: number) {
    const k = this.kinds.get(kind)!;
    const m = model(kind);
    const v: Vehicle = {
      id: this.vehicles.length,
      kind,
      m,
      slot: k.used++,
      lane,
      s,
      v: lane.speed * 0.6,
      v0: lane.speed * (kind === "auto" ? 0.75 : kind === "bus" ? 0.8 : kind === "bike" ? 1.05 : 0.85 + this.rnd() * 0.25),
      a: 0,
      lat: 0,
      latGoal: 0,
      fixed: false,
      hidden: false,
      x: 0,
      z: 0,
      yaw: 0,
    };
    const pick = <T>(xs: readonly T[]) => xs[Math.floor(this.rnd() * xs.length)]!;
    const paint = kind === "auto" ? pick(PAINTS.auto) : kind === "bike" ? pick(PAINTS.bike) : kind === "bus" ? pick(PAINTS.bus) : pick(PAINTS.car);
    k.meshes.paint?.setColorAt(v.slot, this.tmpC.set(paint));
    k.meshes.accent?.setColorAt(v.slot, this.tmpC.set(kind === "bus" ? pick(PAINTS.busAccent) : "#c8141f"));
    k.meshes.tail?.setColorAt(v.slot, this.tmpC.setRGB(0.35, 0.03, 0.02));
    for (const im of Object.values(k.meshes)) if (im?.instanceColor) im.instanceColor.needsUpdate = true;
    this.vehicles.push(v);
    return v;
  }

  private placeIncident() {
    const lane = this.eastKerb;
    // clear the kerb lane around the spot
    for (const v of this.vehicles) if (v.lane === lane && Math.abs(v.s - INCIDENT_X) < 10) v.s -= 24;
    const car = this.addVehicle("sedan", lane, INCIDENT_X);
    this.kinds.get("sedan")!.meshes.paint!.setColorAt(car.slot, this.tmpC.set("#8d949d"));
    car.fixed = true;
    car.v = 0;
    car.lat = -0.5;
    car.latGoal = -0.5;
    this.incidentCar = car;

    // hazard lamps at the four corners, a warning triangle behind
    const group = new THREE.Group();
    const mats: THREE.MeshBasicMaterial[] = [];
    for (const [x, z] of [
      [2.24, 0.68],
      [2.24, -0.68],
      [-2.24, 0.68],
      [-2.24, -0.68],
    ] as const) {
      const mat = new THREE.MeshBasicMaterial({ color: new THREE.Color(2.4, 1.3, 0.1), toneMapped: false });
      const m = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.12, 0.2), mat);
      m.position.set(x, 0.72, z);
      group.add(m);
      mats.push(mat);
    }
    const light = new THREE.PointLight(0xffa21a, 0, 14, 2);
    light.position.set(0, 1.4, 0);
    group.add(light);
    this.scene.add(group);
    const tri = new THREE.Mesh(
      new THREE.ConeGeometry(0.35, 0.6, 3),
      new THREE.MeshStandardMaterial({ color: 0xe02a1f, emissive: 0x6a0c06, roughness: 0.5 }),
    );
    tri.position.set(INCIDENT_X - 9, 0.3, -AV.kerb - 0.5);
    tri.castShadow = true;
    this.scene.add(tri);
    this.hazard = { mats, light, group };
  }

  private buildAmbulance(): Ambulance {
    const m = model("ambulance");
    const group = new THREE.Group();
    const mats: Partial<Record<Slot, THREE.Material>> = {
      paint: new THREE.MeshPhysicalMaterial({ color: 0xf3f5f7, roughness: 0.28, clearcoat: 1, clearcoatRoughness: 0.05 }),
      accent: new THREE.MeshStandardMaterial({ color: 0xc8141f, roughness: 0.45 }),
      glass: new THREE.MeshPhysicalMaterial({ color: 0x0c1118, roughness: 0.04, clearcoat: 1 }),
      dark: new THREE.MeshStandardMaterial({ color: 0x17191d, roughness: 0.75 }),
      head: new THREE.MeshBasicMaterial({ color: new THREE.Color(2.2, 2.05, 1.8), toneMapped: false }),
      tail: new THREE.MeshBasicMaterial({ color: new THREE.Color(1.2, 0.08, 0.05), toneMapped: false }),
    };
    for (const slot of SLOTS) {
      const geo = m.parts[slot];
      if (!geo) continue;
      const mesh = new THREE.Mesh(geo, mats[slot]);
      mesh.castShadow = slot === "paint";
      group.add(mesh);
    }
    for (const [x, z] of m.wheels) {
      const w = new THREE.Mesh(wheelGeometry(), new THREE.MeshStandardMaterial({ color: 0x121316, roughness: 0.7 }));
      w.scale.set(m.wheelR, m.wheelR, m.wheelW);
      w.position.set(x, m.wheelR, z);
      group.add(w);
    }
    const beacons: THREE.MeshBasicMaterial[] = [];
    for (const [z, c] of [
      [0.45, new THREE.Color(1.9, 0.12, 0.16)],
      [-0.45, new THREE.Color(0.2, 0.4, 2.0)],
    ] as const) {
      const mat = new THREE.MeshBasicMaterial({ color: c.clone(), toneMapped: false });
      mat.userData.base = c;
      const b = new THREE.Mesh(new THREE.BoxGeometry(0.26, 0.14, 0.6), mat);
      b.position.set(0.75, 2.76, z);
      group.add(b);
      beacons.push(mat);
    }
    const lights = [new THREE.PointLight(0xff2a3a, 0, 13, 2), new THREE.PointLight(0x3a6aff, 0, 13, 2)];
    lights[0]!.position.set(0.8, 3.2, 1.2);
    lights[1]!.position.set(0.8, 3.2, -1.2);
    group.add(...lights);
    // its own headlight throw
    const beam = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2).translate(0.5, 0, 0),
      (this.beams.material as THREE.MeshBasicMaterial).clone(),
    );
    beam.scale.set(15, 1, 6);
    beam.position.set(2.7, 0.04, 0);
    beam.renderOrder = 2;
    (beam.material as THREE.MeshBasicMaterial).opacity = 0.55;
    group.add(beam);
    group.visible = false;
    this.scene.add(group);
    return { on: false, d: 0, x: 0, z: 0, yaw: 0, group, beacons, lights };
  }

  /** Put the ambulance at a world pose (or hide it). */
  setAmbulance(pose: { x: number; z: number; yaw: number } | null) {
    const a = this.amb;
    if (!a) return;
    a.on = !!pose;
    a.group.visible = !!pose;
    if (!pose) return;
    a.x = pose.x;
    a.z = pose.z;
    a.yaw = pose.yaw;
    a.group.position.set(pose.x, 0, pose.z);
    a.group.rotation.y = pose.yaw;
  }

  step(dt: number) {
    this.t += dt;
    for (const l of this.lanes) {
      l.list.length = 0;
    }
    for (const v of this.vehicles) if (!v.hidden) v.lane.list.push(v);
    for (const l of this.lanes) l.list.sort((a, b) => (a.s - b.s) * l.dir);

    const amb = this.amb?.on ? this.amb : null;
    const onEastAvenue = amb && amb.z < 0 && amb.z > -AV.half;

    for (const l of this.lanes)
      for (let i = 0; i < l.list.length; i++) {
        const v = l.list[i]!;
        if (v.fixed) continue;

        // yielding: an ambulance coming up behind on the eastbound avenue
        let yieldK = 0;
        if (onEastAvenue && l.axis === "x" && l.dir === 1 && l.avenue) {
          const gap = v.s - amb!.x;
          if (gap > -5 && gap < 75) yieldK = 1;
        }
        const kerbward = l.c === -AV.fast ? -1.4 : l.c === -AV.kerb ? -0.45 : 0;
        const goal = v.latGoal + yieldK * kerbward;

        // gap to whatever is ahead
        let gap = Infinity;
        let lead = v.v0;
        const ahead = l.list[i + 1];
        if (ahead) {
          gap = (ahead.s - v.s) * l.dir - (ahead.m.len + v.m.len) / 2;
          lead = ahead.v;
        }
        if (onEastAvenue && l.axis === "x" && l.dir === 1 && Math.abs(amb!.z - (l.c + v.lat)) < 2.2 && amb!.x > v.s) {
          const g = amb!.x - v.s - (5.3 + v.m.len) / 2;
          if (g < gap) {
            gap = g;
            lead = 0;
          }
        }
        for (const st of l.stops) {
          const d = (st.s - v.s) * l.dir - v.m.len / 2;
          if (d < -1) continue;
          const light = lightOf(st.j, st.group, this.t);
          if (light !== "g" && !(light === "a" && d < (v.v * v.v) / 6)) {
            if (d < gap) {
              gap = Math.max(0, d);
              lead = 0;
            }
          }
          break;
        }

        const v0 = yieldK ? Math.min(v.v0, 3) : v.v0;
        const A = v.kind === "bus" ? 1.0 : 1.7;
        const B = 2.6;
        const sStar = 2 + v.v * 1.1 + (v.v * (v.v - lead)) / (2 * Math.sqrt(A * B));
        let acc = A * (1 - Math.pow(v.v / Math.max(0.5, v0), 4) - Math.pow(Math.max(0, sStar) / Math.max(0.1, gap), 2));
        acc = Math.max(-8, acc);
        v.a = acc;
        v.v = Math.max(0, v.v + acc * dt);
        v.s += v.v * dt * l.dir;
        v.lat += Math.max(-1.5 * dt, Math.min(1.5 * dt, goal - v.lat));

        // merge out of the kerb lane before the broken-down car
        if (this.incidentCar && l === this.eastKerb && v.s < INCIDENT_X && INCIDENT_X - v.s < 48 && this.rnd() < dt * 2) {
          const to = this.eastFast;
          const clear = to.list.every((o) => o.s - v.s > 9 || v.s - o.s > 11);
          if (clear) {
            v.lane = to;
            v.lat += l.c - to.c;
          }
        }

        // off the end: come back in at the start once there is room
        if ((l.dir === 1 && v.s > l.max) || (l.dir === -1 && v.s < l.min)) this.respawn(v, l);
      }
    for (const v of this.vehicles) if (v.hidden && this.rnd() < dt * 0.8) this.respawn(v, v.lane);
  }

  private respawn(v: Vehicle, l: Lane) {
    const start = l.dir === 1 ? l.min : l.max;
    const first = l.list.find((o) => o !== v && Math.abs(o.s - start) < 14);
    if (first) {
      v.hidden = true;
      return;
    }
    v.hidden = false;
    v.s = start;
    v.lat = 0;
    v.latGoal = 0;
    v.v = v.v0 * 0.8;
  }

  // ---------------------------------------------------------- instance sync

  private syncInstances() {
    let wi = 0;
    let bi = 0;
    const touched = new Set<THREE.InstancedMesh>();
    const hidden = this.tmpM.makeScale(0, 0, 0).clone();
    for (const v of this.vehicles) {
      const k = this.kinds.get(v.kind)!;
      if (v.hidden) {
        for (const im of Object.values(k.meshes)) if (im) im.setMatrixAt(v.slot, hidden);
        continue;
      }
      const l = v.lane;
      const c = l.c + v.lat;
      v.x = l.axis === "x" ? v.s : c;
      v.z = l.axis === "x" ? c : v.s;
      // heading, with a small steer while changing lateral position
      const steer = Math.max(-0.25, Math.min(0.25, (v.latGoal - v.lat) * 0.08));
      v.yaw = l.axis === "x" ? (l.dir === 1 ? 0 : Math.PI) : l.dir === 1 ? -Math.PI / 2 : Math.PI / 2;
      v.yaw += steer * -l.dir;
      this.tmpQ.setFromAxisAngle(this.yAxis, v.yaw);
      const bob = v.v > 0.5 ? Math.sin(this.t * 9 + v.id) * 0.008 : 0;
      this.tmpM.compose(this.tmpV.set(v.x, bob, v.z), this.tmpQ, this.tmpS.set(1, 1, 1));
      for (const im of Object.values(k.meshes)) {
        if (!im) continue;
        im.setMatrixAt(v.slot, this.tmpM);
        touched.add(im);
      }
      // brake lights brighten when slowing or stopped
      const braking = v.a < -0.8 || v.v < 0.3;
      if (k.meshes.tail) {
        k.meshes.tail.setColorAt(v.slot, braking ? this.tmpC.setRGB(1.8, 0.1, 0.05) : this.tmpC.setRGB(0.45, 0.03, 0.02));
        k.meshes.tail.instanceColor!.needsUpdate = true;
      }
      const base = this.tmpM.clone();
      for (const [wx, wz] of v.m.wheels) {
        const wm = new THREE.Matrix4().compose(this.tmpV.set(wx, v.m.wheelR, wz), this.tmpQ.identity(), this.tmpS.set(v.m.wheelR, v.m.wheelR, v.m.wheelW));
        this.wheels.setMatrixAt(wi++, base.clone().multiply(wm));
      }
      if (!v.fixed) {
        const bm = new THREE.Matrix4().compose(
          this.tmpV.set(v.m.len / 2 + 0.2, 0.04, 0),
          this.tmpQ.identity(),
          this.tmpS.set(v.kind === "bike" ? 7 : 11, 1, v.kind === "bike" ? 2.4 : v.m.wid * 2.6),
        );
        this.beams.setMatrixAt(bi++, base.multiply(bm));
      }
    }
    for (const im of touched) im.instanceMatrix.needsUpdate = true;
    for (const [, k] of this.kinds) for (const im of Object.values(k.meshes)) if (im) im.instanceMatrix.needsUpdate = true;
    this.wheels.count = wi;
    this.wheels.instanceMatrix.needsUpdate = true;
    this.beams.count = bi;
    this.beams.instanceMatrix.needsUpdate = true;

    if (this.hazard && this.incidentCar) {
      const car = this.incidentCar;
      this.hazard.group.position.set(car.x, 0, car.z);
      // hazards pulse rather than snap, like the incandescent bulbs they imitate
      const on = 0.5 + 0.5 * Math.cos(this.t * Math.PI * 1.6);
      const k = 0.15 + 0.85 * Math.pow(on, 0.6);
      this.hazard.mats.forEach((m) => m.color.setRGB(3.2 * k, 1.7 * k, 0.12 * k));
      this.hazard.light.intensity = 22 * k;
    }
    if (this.amb?.on) {
      // a calm alternation between red and blue, not a strobe
      const w = 0.5 + 0.5 * Math.sin(this.t * 6);
      const [r, b] = this.amb.beacons;
      r!.color.copy(r!.userData.base as THREE.Color).multiplyScalar(0.25 + 0.75 * w);
      b!.color.copy(b!.userData.base as THREE.Color).multiplyScalar(0.25 + 0.75 * (1 - w));
      this.amb.lights[0]!.intensity = 9 * w;
      this.amb.lights[1]!.intensity = 12 * (1 - w);
    }
    this.updateSignals();
  }

  /** Vehicles waiting at a junction's approaches, by group. */
  queued(j: Junction) {
    const n: [number, number] = [0, 0];
    for (const l of this.lanes)
      for (const st of l.stops) {
        if (st.j !== j) continue;
        for (const v of l.list) {
          const d = (st.s - v.s) * l.dir;
          if (!v.fixed && v.v < 1.2 && d > -1 && d < 80) n[st.group]++;
        }
      }
    return n;
  }
}

export { clamp01 };
