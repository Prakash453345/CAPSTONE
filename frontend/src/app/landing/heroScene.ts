import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { AmbulanceModel } from "./ambulanceModel";

/**
 * The landing hero: a night avenue seen from just behind an ambulance on a
 * call. Every signal gantry ahead of it turns green as it closes in (the
 * product's green corridor, told without words), while oncoming headlights
 * streak past and the traffic it overtakes glows as red tail-lights.
 *
 * Everything is procedural — light streaks, glows, window grids and the road
 * are shaders, not textures — so it stays sharp at any resolution, and the
 * scene renders through a multisampled target so edges stay clean under the
 * bloom. The camera is fixed to the ambulance and the world scrolls under
 * it: static scenery lives in three identical tiles that leapfrog each other,
 * and only the cars and lamp colours are rewritten per frame.
 *
 * `setProgress` (0..1, from the hero's scroll) lifts the camera from street
 * level to an aerial shot that shows the whole wave of green ahead.
 */

const TILE = 440; // length of one scenery tile along z
const GANTRY_EVERY = 55;
const AMB_Z = -15; // ambulance, relative to the camera rig origin
const AMB_X = 1.8;
const GREEN_LEAD = 105; // how far ahead of the ambulance signals turn green
const FOG = new THREE.Color("#0a0c14");

const COL = {
  red: new THREE.Color(3.2, 0.18, 0.12),
  amber: new THREE.Color(3.0, 1.35, 0.12),
  green: new THREE.Color(0.25, 3.0, 1.1),
  head: new THREE.Color(2.2, 2.1, 1.9),
  tail: new THREE.Color(2.4, 0.12, 0.08),
  sodium: new THREE.Color(2.0, 0.98, 0.34),
  siRed: new THREE.Color(2.6, 0.1, 0.16),
  siBlue: new THREE.Color(0.18, 0.45, 2.8),
};

// ---------------------------------------------------------------- shaders

const FOG_GLSL = /* glsl */ `
  uniform vec3 uFog; uniform float uFogDensity;
  float fogAmt(float d){ return 1.0 - exp(-pow(d * uFogDensity, 1.35)); }
`;

/** Camera-facing glow quads (lamps, lens flares). Fades out right in front
 * of the lens so nearby lights never balloon into blobs. */
const GLOW_VS = /* glsl */ `
  attribute vec3 iPos; attribute vec3 iColor; attribute float iSize; attribute float iAlpha;
  varying vec2 vUv; varying vec3 vColor; varying float vAlpha; varying float vDist;
  void main(){
    vec4 mv = modelViewMatrix * vec4(iPos, 1.0);
    vDist = -mv.z;
    mv.xy += position.xy * iSize;
    vUv = position.xy; vColor = iColor; vAlpha = iAlpha;
    gl_Position = projectionMatrix * mv;
  }`;
const GLOW_FS = /* glsl */ `
  ${FOG_GLSL}
  varying vec2 vUv; varying vec3 vColor; varying float vAlpha; varying float vDist;
  void main(){
    float r = length(vUv);
    if (r > 1.0) discard;
    float core = exp(-r * r * 46.0);
    float halo = exp(-r * r * 7.0) * 0.22;
    float a = (core + halo) * vAlpha * (1.0 - fogAmt(vDist)) * smoothstep(3.0, 18.0, vDist);
    gl_FragColor = vec4(vColor * a, 1.0);
  }`;

/** Ribbons along +/-z, billboarded around their own axis (light trails and
 * their wet-road reflections). */
const STREAK_VS = /* glsl */ `
  attribute vec3 iPos; attribute vec3 iColor; attribute float iLen; attribute float iWidth; attribute float iAlpha;
  uniform float uDir;
  varying float vAlong; varying float vSide; varying vec3 vColor; varying float vAlpha; varying float vDist;
  void main(){
    vec3 dir = vec3(0.0, 0.0, uDir);
    float t = position.y;
    vec3 p = iPos + dir * (iLen * max(t, 0.0) + iWidth * min(t, 0.0) * 3.0);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    vec3 dv = normalize((modelViewMatrix * vec4(dir, 0.0)).xyz);
    vec3 side = normalize(cross(dv, normalize(-mv.xyz)));
    mv.xyz += side * iWidth * position.x;
    vAlong = t; vSide = position.x; vColor = iColor; vAlpha = iAlpha; vDist = -mv.z;
    gl_Position = projectionMatrix * mv;
  }`;
const STREAK_FS = /* glsl */ `
  ${FOG_GLSL}
  varying float vAlong; varying float vSide; varying vec3 vColor; varying float vAlpha; varying float vDist;
  void main(){
    float s = abs(vSide);
    float body = exp(-s * s * 9.0);
    float tail = vAlong < 0.0 ? exp(-vAlong * vAlong * 60.0) : pow(1.0 - clamp(vAlong, 0.0, 1.0), 1.7);
    float a = body * tail * vAlpha * (1.0 - fogAmt(vDist)) * smoothstep(2.0, 14.0, vDist);
    gl_FragColor = vec4(vColor * a, 1.0);
  }`;

/** Flat radial pools of light on the road. */
const POOL_VS = /* glsl */ `
  attribute vec3 iPos; attribute vec3 iColor; attribute vec2 iSize; attribute float iAlpha;
  varying vec2 vUv; varying vec3 vColor; varying float vAlpha; varying float vDist;
  void main(){
    vec3 p = iPos + vec3(position.x * iSize.x, 0.0, position.y * iSize.y);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    vDist = -mv.z; vUv = position.xy; vColor = iColor; vAlpha = iAlpha;
    gl_Position = projectionMatrix * mv;
  }`;
const POOL_FS = /* glsl */ `
  ${FOG_GLSL}
  varying vec2 vUv; varying vec3 vColor; varying float vAlpha; varying float vDist;
  void main(){
    float r = length(vUv);
    float a = smoothstep(1.0, 0.0, r); a *= a;
    a *= vAlpha * (1.0 - fogAmt(vDist));
    gl_FragColor = vec4(vColor * a, 1.0);
  }`;

/** Buildings: dark facades with a procedural window grid (no textures). */
const BLDG_VS = /* glsl */ `
  varying vec3 vLocal; varying vec3 vN; varying float vDist; varying float vSeed;
  void main(){
    vec4 local = instanceMatrix * vec4(position, 1.0);
    vLocal = local.xyz;
    vN = normalize(mat3(instanceMatrix) * normal);
    vSeed = float(gl_InstanceID);
    vec4 mv = modelViewMatrix * local;
    vDist = -mv.z;
    gl_Position = projectionMatrix * mv;
  }`;
const BLDG_FS = /* glsl */ `
  ${FOG_GLSL}
  uniform float uTime;
  varying vec3 vLocal; varying vec3 vN; varying float vDist; varying float vSeed;
  float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  void main(){
    // facades pick up a faint sky tint toward the top so the skyline reads
    vec3 base = mix(vec3(0.016, 0.019, 0.028), vec3(0.034, 0.038, 0.056), smoothstep(0.0, 90.0, vLocal.y));
    vec3 col = base;
    if (abs(vN.y) < 0.5) {
      vec2 f = abs(vN.x) > 0.5 ? vec2(vLocal.z, vLocal.y) : vec2(vLocal.x, vLocal.y);
      vec2 cell = vec2(1.25, 1.75);
      vec2 id = floor(f / cell);
      vec2 g = fract(f / cell);
      // anti-aliased window edges so distant facades don't shimmer
      vec2 fw = fwidth(f / cell) * 1.2;
      float win = smoothstep(0.24 - fw.x, 0.24 + fw.x, g.x) * smoothstep(0.76 + fw.x, 0.76 - fw.x, g.x)
                * smoothstep(0.3 - fw.y, 0.3 + fw.y, g.y) * smoothstep(0.78 + fw.y, 0.78 - fw.y, g.y);
      float r = h(id + vSeed * 7.13);
      float floorOn = step(0.35, h(vec2(id.y, vSeed)));
      float lit = step(0.8, r) * step(1.2, vLocal.y) * floorOn;
      float warm = h(id * 1.7 + vSeed);
      vec3 wc = mix(vec3(1.0, 0.64, 0.32), vec3(0.6, 0.78, 1.0), step(0.7, warm));
      float flick = 0.9 + 0.1 * sin(uTime * (0.4 + r * 1.5) + r * 40.0);
      col += win * lit * wc * (0.12 + 0.4 * h(id + 3.1)) * flick;
      col += win * (1.0 - lit) * vec3(0.01, 0.014, 0.022);
      // a slab line every floor-group gives the boxes some architecture
      float slab = 1.0 - smoothstep(0.0, fw.y * 2.0 + 0.02, abs(fract(f.y / (cell.y * 4.0)) - 0.02));
      col += slab * vec3(0.012, 0.014, 0.02);
    } else {
      col = vec3(0.012, 0.014, 0.02);
    }
    col = mix(col, uFog, fogAmt(vDist));
    gl_FragColor = vec4(col, 1.0);
  }`;

/** Road: asphalt with a faint sheen that brightens toward the horizon glow. */
const ROAD_VS = /* glsl */ `
  varying vec3 vW; varying float vDist;
  void main(){
    vec4 w = modelMatrix * vec4(position, 1.0);
    vW = w.xyz;
    vec4 mv = viewMatrix * w; vDist = -mv.z;
    gl_Position = projectionMatrix * mv;
  }`;
const ROAD_FS = /* glsl */ `
  ${FOG_GLSL}
  varying vec3 vW; varying float vDist;
  void main(){
    float edge = smoothstep(12.6, 13.2, abs(vW.x));
    vec3 asphalt = vec3(0.02, 0.023, 0.03);
    vec3 kerb = vec3(0.036, 0.038, 0.046);
    vec3 col = mix(asphalt, kerb, edge);
    float sheen = smoothstep(20.0, 260.0, vDist) * 0.045;
    col += vec3(0.5, 0.4, 0.55) * sheen;
    col = mix(col, uFog, fogAmt(vDist));
    gl_FragColor = vec4(col, 1.0);
  }`;

const SKY_VS = /* glsl */ `
  varying vec3 vDir;
  void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const SKY_FS = /* glsl */ `
  varying vec3 vDir;
  void main(){
    float y = vDir.y;
    vec3 top = vec3(0.008, 0.011, 0.022);
    vec3 mid = vec3(0.035, 0.038, 0.07);
    vec3 glow = vec3(0.15, 0.08, 0.07);
    vec3 col = mix(mid, top, smoothstep(0.02, 0.5, y));
    col += glow * exp(-abs(y) * 16.0) * (0.75 + 0.25 * smoothstep(-0.6, 0.0, vDir.z * -1.0));
    col = mix(col, vec3(0.039, 0.047, 0.078), smoothstep(0.0, -0.08, y));
    gl_FragColor = vec4(col, 1.0);
  }`;

// ---------------------------------------------------------------- helpers

/** A dynamic instanced field whose per-instance attributes are rewritten each frame. */
class Field {
  mesh: THREE.Mesh;
  count = 0;
  private attrs: Record<string, THREE.InstancedBufferAttribute> = {};
  private geo: THREE.InstancedBufferGeometry;

  constructor(
    base: THREE.BufferGeometry,
    material: THREE.ShaderMaterial,
    layout: Record<string, number>,
    readonly capacity: number,
  ) {
    const geo = new THREE.InstancedBufferGeometry();
    geo.index = base.index;
    geo.setAttribute("position", base.getAttribute("position"));
    for (const [name, size] of Object.entries(layout)) {
      const a = new THREE.InstancedBufferAttribute(new Float32Array(capacity * size), size);
      a.setUsage(THREE.DynamicDrawUsage);
      geo.setAttribute(name, a);
      this.attrs[name] = a;
    }
    geo.instanceCount = 0;
    this.geo = geo;
    this.mesh = new THREE.Mesh(geo, material);
    this.mesh.frustumCulled = false;
  }

  begin() {
    this.count = 0;
  }
  push(values: Record<string, number[] | number>) {
    if (this.count >= this.capacity) return;
    const i = this.count++;
    for (const [name, v] of Object.entries(values)) {
      const a = this.attrs[name]!;
      const arr = a.array as Float32Array;
      if (typeof v === "number") arr[i * a.itemSize] = v;
      else for (let k = 0; k < v.length; k++) arr[i * a.itemSize + k] = v[k]!;
    }
  }
  end() {
    this.geo.instanceCount = this.count;
    for (const a of Object.values(this.attrs)) {
      a.clearUpdateRanges();
      a.addUpdateRange(0, this.count * a.itemSize);
      a.needsUpdate = true;
    }
  }
  dispose() {
    this.geo.dispose();
  }
}

function additive(vs: string, fs: string, uniforms: Record<string, THREE.IUniform> = {}) {
  return new THREE.ShaderMaterial({
    vertexShader: vs,
    fragmentShader: fs,
    uniforms,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
}

const rand = (() => {
  let s = 1337;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
})();

const smooth = (t: number) => t * t * (3 - 2 * t);
const clamp01 = (t: number) => Math.min(1, Math.max(0, t));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

interface Car {
  x: number;
  z: number; // camera-relative
  v: number; // ground speed (m/s), sign = travel direction (-: away)
  oncoming: boolean;
}

// ---------------------------------------------------------------- scene

export class HeroScene {
  private renderer: THREE.WebGLRenderer;
  private composer: EffectComposer;
  private bloom: UnrealBloomPass;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private tiles: THREE.Group[] = [];
  private glow: Field;
  private streak: Field;
  private reflect: Field;
  private pool: Field;
  private uniforms = {
    uFog: { value: FOG },
    uFogDensity: { value: 1 / 260 },
    uTime: { value: 0 },
  };
  private cars: Car[] = [];
  private gantryZ: number[] = []; // tile-local
  private roofs: [number, number, number][] = []; // tile-local aviation lights
  private lampLevel: number[] = []; // per gantry, 0 red .. 1 green (smoothed)
  private travel = 0;
  private speed = 24;
  private progress = 0;
  private progressS = 0;
  private pointer = { x: 0, y: 0, sx: 0, sy: 0 };
  private raf = 0;
  private last = 0;
  private time = 0;
  private running = false;
  private ambulance: AmbulanceModel;
  private disposed = false;
  private ro: ResizeObserver;

  constructor(
    private host: HTMLElement,
    private opts: { reducedMotion: boolean; mobile: boolean },
  ) {
    this.renderer = new THREE.WebGLRenderer({
      antialias: false,
      powerPreference: "high-performance",
      alpha: false,
      // On software rendering the scene runs at ~1 fps and freezes every
      // click on the page; refusing it falls back to the static hero.
      failIfMajorPerformanceCaveat: true,
    });
    this.renderer.setClearColor(FOG, 1);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(this.renderer.domElement);
    this.renderer.domElement.style.cssText = "display:block;width:100%;height:100%;";

    this.camera = new THREE.PerspectiveCamera(52, 1, 0.1, 1400);

    this.buildSky();
    this.buildTiles();

    const quad = new THREE.PlaneGeometry(2, 2);
    const strip = new THREE.PlaneGeometry(2, 1.15, 1, 1);
    strip.translate(0, 0.425, 0); // y in [-0.15, 1]
    this.glow = new Field(quad, additive(GLOW_VS, GLOW_FS, this.uniforms), { iPos: 3, iColor: 3, iSize: 1, iAlpha: 1 }, 900);
    this.streak = new Field(
      strip,
      additive(STREAK_VS, STREAK_FS, { ...this.uniforms, uDir: { value: -1 } }),
      { iPos: 3, iColor: 3, iLen: 1, iWidth: 1, iAlpha: 1 },
      700,
    );
    this.reflect = new Field(
      strip,
      additive(STREAK_VS, STREAK_FS, { ...this.uniforms, uDir: { value: 1 } }),
      { iPos: 3, iColor: 3, iLen: 1, iWidth: 1, iAlpha: 1 },
      900,
    );
    const flat = new THREE.PlaneGeometry(2, 2);
    this.pool = new Field(flat, additive(POOL_VS, POOL_FS, this.uniforms), { iPos: 3, iColor: 3, iSize: 2, iAlpha: 1 }, 200);
    this.pool.mesh.renderOrder = 1;
    this.reflect.mesh.renderOrder = 2;
    this.streak.mesh.renderOrder = 3;
    this.glow.mesh.renderOrder = 4;
    this.scene.add(this.pool.mesh, this.reflect.mesh, this.streak.mesh, this.glow.mesh);

    this.spawnCars();

    this.ambulance = new AmbulanceModel(this.scene);
    this.ambulance.group.position.set(AMB_X, 0, AMB_Z + 0.7);
    // only the ambulance uses scene lighting and fog; everything else is shaded by hand
    this.scene.fog = new THREE.FogExp2(FOG, 0.0026);

    // Render into a multisampled HDR target: the composer's default target
    // has no MSAA, which is what made every edge look soft and stair-stepped.
    const target = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 });
    this.composer = new EffectComposer(this.renderer, target);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    // tight, restrained bloom: lights glow, the rest of the frame stays crisp
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.62, 0.32, 0.42);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    window.addEventListener("pointermove", this.onPointer, { passive: true });
  }

  // -------------------------------------------------------------- build

  private buildSky() {
    const sky = new THREE.Mesh(
      new THREE.SphereGeometry(1000, 32, 16),
      new THREE.ShaderMaterial({ vertexShader: SKY_VS, fragmentShader: SKY_FS, side: THREE.BackSide, depthWrite: false }),
    );
    sky.renderOrder = -1;
    this.scene.add(sky);
  }

  private buildTiles() {
    for (let z = 0; z < TILE; z += GANTRY_EVERY) this.gantryZ.push(-z - 30);
    this.lampLevel = new Array(this.gantryZ.length * 3).fill(0);

    const roadMat = new THREE.ShaderMaterial({ vertexShader: ROAD_VS, fragmentShader: ROAD_FS, uniforms: this.uniforms });
    const bldgMat = new THREE.ShaderMaterial({ vertexShader: BLDG_VS, fragmentShader: BLDG_FS, uniforms: this.uniforms });
    const dark = new THREE.ShaderMaterial({
      vertexShader: ROAD_VS,
      fragmentShader: /* glsl */ `${FOG_GLSL} varying vec3 vW; varying float vDist;
        void main(){ gl_FragColor = vec4(mix(vec3(0.03,0.034,0.042), uFog, fogAmt(vDist)), 1.0); }`,
      uniforms: this.uniforms,
    });
    const markMat = new THREE.ShaderMaterial({
      vertexShader: ROAD_VS,
      fragmentShader: /* glsl */ `${FOG_GLSL} uniform vec3 uCol; varying vec3 vW; varying float vDist;
        void main(){ gl_FragColor = vec4(mix(uCol, uFog, fogAmt(vDist)), 1.0); }`,
      uniforms: { ...this.uniforms, uCol: { value: new THREE.Color(0.16, 0.17, 0.19) } },
    });
    const medianMat = markMat.clone();
    medianMat.uniforms = { ...this.uniforms, uCol: { value: new THREE.Color(0.3, 0.2, 0.06) } };

    // Buildings are generated once and shared by all tiles.
    const bldgs: THREE.Matrix4[] = [];
    for (const side of [-1, 1]) {
      let z = 0;
      while (z < TILE) {
        const depth = 10 + rand() * 18;
        const w = 12 + rand() * 18;
        const h = 8 + Math.pow(rand(), 1.8) * 42;
        const setback = 19 + rand() * 7;
        const m = new THREE.Matrix4().compose(
          new THREE.Vector3(side * (setback + w / 2), h / 2, -z - depth / 2),
          new THREE.Quaternion(),
          new THREE.Vector3(w, h, depth),
        );
        bldgs.push(m);
        if (h > 30) this.roofs.push([side * (setback + w / 2), h + 0.6, -z - depth / 2]);
        // a second, taller row behind for skyline depth
        if (rand() > 0.35) {
          const h2 = 24 + Math.pow(rand(), 1.4) * 64;
          const w2 = 14 + rand() * 20;
          bldgs.push(
            new THREE.Matrix4().compose(
              new THREE.Vector3(side * (setback + w + 12 + rand() * 30), h2 / 2, -z - depth / 2 - rand() * 8),
              new THREE.Quaternion(),
              new THREE.Vector3(w2, h2, 14 + rand() * 14),
            ),
          );
          if (h2 > 50) {
            const e = bldgs[bldgs.length - 1]!.elements;
            this.roofs.push([e[12]!, h2 + 0.6, e[14]!]);
          }
        }
        z += depth + 2 + rand() * 6;
        // leave cross streets clear at each gantry
        for (const gz of this.gantryZ) if (-z < gz + 12 && -z > gz - 12) z = -gz + 12;
      }
    }

    const box = new THREE.BoxGeometry(1, 1, 1);
    const unit = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);

    for (let t = 0; t < 3; t++) {
      const g = new THREE.Group();

      const road = new THREE.Mesh(new THREE.PlaneGeometry(1600, TILE).rotateX(-Math.PI / 2), roadMat);
      road.position.set(0, 0, -TILE / 2);
      g.add(road);

      const b = new THREE.InstancedMesh(box, bldgMat, bldgs.length);
      bldgs.forEach((m, i) => b.setMatrixAt(i, m));
      b.frustumCulled = false;
      g.add(b);

      // lane dashes and the median
      const dashes: THREE.Matrix4[] = [];
      for (let z = 0; z < TILE; z += 9)
        for (const x of [-7.2, -3.6, 3.6, 7.2])
          dashes.push(new THREE.Matrix4().compose(new THREE.Vector3(x, 0.01, -z), new THREE.Quaternion(), new THREE.Vector3(0.14, 1, 3.2)));
      const dm = new THREE.InstancedMesh(unit, markMat, dashes.length);
      dashes.forEach((m, i) => dm.setMatrixAt(i, m));
      dm.frustumCulled = false;
      g.add(dm);
      for (const x of [-0.18, 0.18]) {
        const med = new THREE.Mesh(unit, medianMat);
        med.scale.set(0.12, 1, TILE);
        med.position.set(x, 0.012, -TILE / 2);
        g.add(med);
      }

      // gantries: two poles, an arm, and signal housings over each carriageway
      for (const gz of this.gantryZ) {
        for (const side of [-1, 1]) {
          const pole = new THREE.Mesh(box, dark);
          pole.scale.set(0.35, 7.4, 0.35);
          pole.position.set(side * 12.8, 3.7, gz);
          g.add(pole);
          const arm = new THREE.Mesh(box, dark);
          arm.scale.set(11.4, 0.28, 0.28);
          arm.position.set(side * 7.2, 7.1, gz);
          g.add(arm);
          for (const hx of [2.4, 6.0, 9.6]) {
            const housing = new THREE.Mesh(box, dark);
            housing.scale.set(0.62, 1.9, 0.5);
            housing.position.set(side * hx, 6.05, gz + 0.1);
            g.add(housing);
          }
        }
        // stop line
        const stop = new THREE.Mesh(unit, markMat);
        stop.scale.set(12, 1, 0.45);
        stop.position.set(6.4, 0.011, gz + 5);
        g.add(stop);
      }

      // street-lamp posts
      for (let z = 12; z < TILE; z += 36)
        for (const side of [-1, 1]) {
          const post = new THREE.Mesh(box, dark);
          post.scale.set(0.2, 9, 0.2);
          post.position.set(side * 13.6, 4.5, -z);
          g.add(post);
        }

      this.tiles.push(g);
      this.scene.add(g);
    }
  }

  private spawnCars() {
    const lanes = [
      { x: 5.4, oncoming: false, n: this.opts.mobile ? 7 : 11 },
      { x: 9.0, oncoming: false, n: this.opts.mobile ? 7 : 11 },
      { x: -1.8, oncoming: true, n: this.opts.mobile ? 5 : 8 },
      { x: -5.4, oncoming: true, n: this.opts.mobile ? 6 : 10 },
      { x: -9.0, oncoming: true, n: this.opts.mobile ? 5 : 8 },
    ];
    for (const lane of lanes)
      for (let i = 0; i < lane.n; i++)
        this.cars.push({
          x: lane.x + (rand() - 0.5) * 0.4,
          z: 20 - rand() * 420,
          v: lane.oncoming ? 14 + rand() * 10 : -(9 + rand() * 7),
          oncoming: lane.oncoming,
        });
  }

  // -------------------------------------------------------------- runtime

  private onPointer = (e: PointerEvent) => {
    this.pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
    this.pointer.y = (e.clientY / window.innerHeight) * 2 - 1;
  };

  setProgress(p: number) {
    this.progress = clamp01(p);
  }

  setRunning(on: boolean) {
    if (this.disposed || on === this.running) return;
    this.running = on;
    if (on) {
      this.last = performance.now();
      this.raf = requestAnimationFrame(this.frame);
    } else cancelAnimationFrame(this.raf);
  }

  /** Draw one frame immediately (used for reduced motion and the first paint). */
  renderOnce() {
    this.step(0);
    this.composer.render();
  }

  private resize() {
    const w = Math.max(1, this.host.clientWidth);
    const h = Math.max(1, this.host.clientHeight);
    const cap = this.opts.mobile ? 1.5 : 2;
    let pr = Math.min(window.devicePixelRatio || 1, cap);
    // keep the backbuffer under ~5.5 MP so bloom stays affordable on 4K screens
    while (w * h * pr * pr > 5.5e6 && pr > 1) pr -= 0.25;
    this.renderer.setPixelRatio(pr);
    this.renderer.setSize(w, h, false);
    this.composer.setPixelRatio(pr);
    this.composer.setSize(w, h);
    this.bloom.resolution.set(w * pr * 0.5, h * pr * 0.5);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    if (!this.running) this.renderOnce();
  }

  private frame = (now: number) => {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this.frame);
    const dt = Math.min(0.05, (now - this.last) / 1000);
    this.last = now;
    this.step(dt);
    this.composer.render();
  };

  private step(dt: number) {
    const rm = this.opts.reducedMotion;
    if (rm) dt = 0;
    this.time += dt;
    this.uniforms.uTime.value = this.time;

    this.progressS += (this.progress - this.progressS) * (rm ? 1 : 1 - Math.pow(0.02, dt || 1));
    const p = smooth(clamp01(this.progressS));

    const targetSpeed = 24 + p * 16;
    this.speed += (targetSpeed - this.speed) * Math.min(1, dt * 1.5);
    this.travel += this.speed * dt;

    // tiles leapfrog along +z as we "drive" toward -z
    this.tileZ().forEach((z, i) => (this.tiles[i]!.position.z = z));

    // camera: street level behind the ambulance -> aerial over the corridor
    const ps = this.pointer;
    ps.sx += (ps.x - ps.sx) * Math.min(1, dt * 2.5);
    ps.sy += (ps.y - ps.sy) * Math.min(1, dt * 2.5);
    const sway = rm ? 0 : Math.sin(this.time * 0.7) * 0.05;
    const cam = this.camera;
    const px = lerp(0.9 + ps.sx * 0.8, 0.0 + ps.sx * 4, p);
    const py = lerp(2.4 - ps.sy * 0.35 + sway, 118, p);
    const pz = lerp(6, 70, p);
    cam.position.set(px, py, pz);
    cam.fov = lerp(52, 46, p);
    cam.updateProjectionMatrix();
    cam.lookAt(lerp(0.6, 0, p), lerp(2.2, 0, p), lerp(-60, -150, p));
    cam.rotateZ(lerp(-0.012, 0, p) + ps.sx * 0.008 * (1 - p));
    this.uniforms.uFogDensity.value = lerp(1 / 260, 1 / 340, p);

    this.glow.begin();
    this.streak.begin();
    this.reflect.begin();
    this.pool.begin();

    this.drawLamps();
    this.drawRoofs();
    this.drawSignals(dt);
    this.drawCars(dt);
    this.drawAmbulance(dt);

    this.glow.end();
    this.streak.end();
    this.reflect.end();
    this.pool.end();
  }

  /** World z of each tile's origin. Three tiles cover from behind the
   * aerial camera to well past the fog line. */
  private tileZ(): number[] {
    const off = (this.travel % TILE) + 90;
    return [off, off - TILE, off - 2 * TILE];
  }

  private worldZ(localZ: number): number[] {
    return this.tileZ().map((t) => t + localZ);
  }

  private drawLamps() {
    for (let z = 12; z < TILE; z += 36)
      for (const wz of this.worldZ(-z)) {
        if (wz > 30 || wz < -700) continue;
        for (const side of [-1, 1]) {
          const x = side * 12.9;
          this.glow.push({ iPos: [x, 9.1, wz], iColor: [COL.sodium.r, COL.sodium.g, COL.sodium.b], iSize: 1.5, iAlpha: 0.85 });
          this.pool.push({ iPos: [side * 10, 0.02, wz], iColor: [0.46, 0.24, 0.08], iSize: [7, 9], iAlpha: 0.5 });
          this.reflect.push({
            iPos: [x, 0.03, wz],
            iColor: [COL.sodium.r, COL.sodium.g, COL.sodium.b],
            iLen: 10,
            iWidth: 0.45,
            iAlpha: 0.12,
          });
        }
      }
  }

  private drawRoofs() {
    // aviation lights: a slow, soft breathe rather than a blink
    const breathe = 0.35 + 0.35 * (0.5 + 0.5 * Math.sin(this.time * 1.4));
    for (const [x, y, z] of this.roofs)
      for (const wz of this.worldZ(z)) {
        if (wz > 60 || wz < -700) continue;
        this.glow.push({ iPos: [x, y, wz], iColor: [2.4, 0.12, 0.08], iSize: 1.1, iAlpha: breathe });
      }
  }

  private drawSignals(dt: number) {
    const k = Math.min(1, dt * 5);
    this.gantryZ.forEach((gz, gi) => {
      this.worldZ(gz).forEach((wz, ti) => {
        const li = gi * 3 + ti;
        const ahead = AMB_Z - wz; // >0: gantry is ahead of the ambulance
        let target = 0; // 0 red, 0.5 red+amber, 1 green
        if (ahead < GREEN_LEAD && ahead > -40) target = 1;
        else if (ahead < GREEN_LEAD + 14 && ahead > -40) target = 0.5;
        const cur = this.lampLevel[li]!;
        this.lampLevel[li] = this.opts.reducedMotion ? target : cur + (target - cur) * k;
        if (wz > 30 || wz < -700) return;
        const lvl = this.lampLevel[li]!;
        const red = clamp01(1 - lvl * 1.6);
        const amb = clamp01(1 - Math.abs(lvl - 0.5) * 3.2);
        const grn = clamp01((lvl - 0.55) * 2.4);
        // only our carriageway's heads face the camera
        for (const hx of [2.4, 6.0, 9.6]) {
          const z = wz + 0.4;
          const lamps: [number, THREE.Color, number][] = [
            [6.65, COL.red, red],
            [6.05, COL.amber, amb],
            [5.45, COL.green, grn],
          ];
          for (const [y, c, on] of lamps) {
            const lit = 0.07 + on * 0.93;
            this.glow.push({ iPos: [hx, y, z], iColor: [c.r, c.g, c.b], iSize: 0.4 + on * 0.9, iAlpha: lit });
            if (on > 0.05) this.reflect.push({ iPos: [hx, 0.03, z], iColor: [c.r, c.g, c.b], iLen: 9, iWidth: 0.35, iAlpha: on * 0.16 });
          }
        }
      });
    });
  }

  private drawCars(dt: number) {
    for (const car of this.cars) {
      // relative motion: the camera travels at -speed along z
      car.z += (this.speed + car.v) * dt;
      if (car.z > 24) car.z -= 460;
      if (car.z < -436) car.z += 460;
      const rel = Math.abs(this.speed + car.v);
      if (car.oncoming) {
        const len = 0.8 + rel * 0.11;
        for (const dx of [-0.75, 0.75]) {
          this.streak.push({ iPos: [car.x + dx, 0.65, car.z], iColor: [COL.head.r, COL.head.g, COL.head.b], iLen: len, iWidth: 0.12, iAlpha: 0.9 });
          this.glow.push({ iPos: [car.x + dx, 0.65, car.z], iColor: [COL.head.r, COL.head.g, COL.head.b], iSize: 0.6, iAlpha: 0.5 });
          this.reflect.push({ iPos: [car.x + dx, 0.03, car.z], iColor: [COL.head.r, COL.head.g, COL.head.b], iLen: 7, iWidth: 0.28, iAlpha: 0.13 });
        }
        this.pool.push({ iPos: [car.x, 0.02, car.z + 7], iColor: [0.45, 0.45, 0.43], iSize: [2.2, 7], iAlpha: 0.35 });
      } else {
        const len = 0.25 + rel * 0.05;
        for (const dx of [-0.8, 0.8]) {
          this.streak.push({ iPos: [car.x + dx, 0.85, car.z], iColor: [COL.tail.r, COL.tail.g, COL.tail.b], iLen: len, iWidth: 0.1, iAlpha: 0.85 });
          this.glow.push({ iPos: [car.x + dx, 0.85, car.z], iColor: [COL.tail.r, COL.tail.g, COL.tail.b], iSize: 0.5, iAlpha: 0.6 });
          this.reflect.push({ iPos: [car.x + dx, 0.03, car.z], iColor: [COL.tail.r, COL.tail.g, COL.tail.b], iLen: 6, iWidth: 0.24, iAlpha: 0.16 });
        }
      }
    }
  }

  private drawAmbulance(dt: number) {
    const t = this.time;
    const amb = this.ambulance;
    const o = amb.group.position;
    // A calm alternating fade between red and blue — no strobing flashes.
    const wave = this.opts.reducedMotion ? 0.5 : 0.5 + 0.5 * Math.sin(t * 5.2);
    // the two street lamps either side of the vehicle light it as it passes
    const lamps: number[] = [];
    for (let z = 12; z < TILE; z += 36) for (const wz of this.worldZ(-z)) lamps.push(wz);
    lamps.sort((a, b) => Math.abs(a - o.z) - Math.abs(b - o.z));
    amb.update(t, wave, this.speed * dt, lamps.slice(0, 2), 12.9, 9.1);

    // grows with altitude so the unit stays readable from the aerial shot
    const lift = 1 + smooth(clamp01(this.progressS)) * 3.5;
    const at = (v: THREE.Vector3) => [o.x + v.x, v.y, o.z + v.z];
    const { beaconRear, beaconFront, tail } = amb.anchors;
    [beaconRear, beaconFront].forEach((pair, k) =>
      pair.forEach((v, i) => {
        const c = i === 0 ? COL.siRed : COL.siBlue;
        const on = i === 0 ? wave : 1 - wave;
        const size = (k === 0 ? 0.16 + on * 0.26 : 0.4 + on * 0.6) * lift;
        this.glow.push({ iPos: at(v), iColor: [c.r, c.g, c.b], iSize: size, iAlpha: 0.25 + on * 0.6 });
        if (k === 0) this.reflect.push({ iPos: [o.x + v.x, 0.03, o.z + v.z], iColor: [c.r, c.g, c.b], iLen: 10, iWidth: 0.5, iAlpha: on * 0.08 });
      }),
    );
    for (const v of tail) {
      this.glow.push({ iPos: at(v), iColor: [COL.tail.r, COL.tail.g, COL.tail.b], iSize: 0.3, iAlpha: 0.4 });
      this.reflect.push({ iPos: [o.x + v.x, 0.03, o.z + v.z], iColor: [COL.tail.r, COL.tail.g, COL.tail.b], iLen: 5, iWidth: 0.28, iAlpha: 0.14 });
    }
    // headlight wash on the road ahead
    this.pool.push({ iPos: [o.x, 0.02, o.z - 18], iColor: [0.5, 0.5, 0.48], iSize: [4.5, 14], iAlpha: 0.5 });
  }

  dispose() {
    this.disposed = true;
    this.setRunning(false);
    this.ro.disconnect();
    window.removeEventListener("pointermove", this.onPointer);
    this.ambulance.dispose();
    this.scene.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.geometry) m.geometry.dispose();
      const mat = m.material as THREE.Material | THREE.Material[] | undefined;
      if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
      else mat?.dispose();
    });
    [this.glow, this.streak, this.reflect, this.pool].forEach((f) => f.dispose());
    this.composer.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.renderer.domElement.remove();
  }
}
