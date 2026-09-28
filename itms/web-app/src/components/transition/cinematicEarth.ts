import * as THREE from "three";

/**
 * A photoreal Earth for the landing → console cinematic, written directly
 * against three.js rather than through react-globe.gl so every part of the
 * look is ours to shade:
 *
 * - day/night surface: NASA Blue Marble on the lit side, city lights on the
 *   dark side, blended across a soft terminator with a warm sunset band;
 * - terrain relief from a height map, ocean-only sun glint from a water mask,
 *   cloud shadows cast onto the surface;
 * - a drifting cloud shell lit by the same sun;
 * - an atmosphere computed per pixel from the camera ray's closest approach to
 *   the planet, so the halo stays correct from orbit down to the horizon glow
 *   seen during the final descent (a plain fresnel rim breaks up close);
 * - a procedural star field (crisp at any zoom, unlike a sky texture).
 *
 * The camera moves for real — position, field of view, roll — so the dive is
 * true perspective instead of a CSS-scaled canvas going soft.
 *
 * Textures are local (public/globe) and cached at module scope, so the
 * landing page can warm them up before the visitor ever clicks through.
 */

const TEXTURE_URLS = {
  day: "/globe/earth-day.jpg",
  // City lights only — extracted from NASA Black Marble with its moonlit
  // land base removed, so the night side stays dark instead of teal.
  lights: "/globe/earth-lights.jpg",
  water: "/globe/earth-water.jpg",
  topo: "/globe/earth-topology.jpg",
  clouds: "/globe/earth-clouds.jpg",
} as const;

type TextureKey = keyof typeof TEXTURE_URLS;
export type EarthTextures = Record<TextureKey, THREE.Texture>;

let texturePromise: Promise<EarthTextures> | null = null;

/** Starts (once) and returns the texture load. Safe to call repeatedly. */
export function preloadEarthTextures(): Promise<EarthTextures> {
  if (texturePromise) return texturePromise;
  // ImageBitmaps are decoded off the main thread; a plain <img> would be
  // decoded synchronously at GPU-upload time — over a second of frozen page
  // for these 4K maps, right as the cinematic starts.
  const loader = new THREE.ImageBitmapLoader();
  loader.setOptions({ imageOrientation: "flipY" });
  const keys = Object.keys(TEXTURE_URLS) as TextureKey[];
  texturePromise = Promise.all(
    keys.map(
      (k) =>
        new Promise<THREE.Texture>((resolve, reject) => {
          loader.load(
            TEXTURE_URLS[k],
            (bitmap) => {
              const tex = new THREE.Texture(bitmap);
              tex.flipY = false; // already flipped during decode
              // Shaders below do their own gamma handling, so the raw bytes
              // are what we want.
              tex.colorSpace = THREE.NoColorSpace;
              tex.anisotropy = 8;
              tex.wrapS = THREE.RepeatWrapping;
              tex.needsUpdate = true;
              resolve(tex);
            },
            undefined,
            reject,
          );
        }),
    ),
  ).then((list) => Object.fromEntries(keys.map((k, i) => [k, list[i]])) as EarthTextures);
  // A failed load must not poison later attempts.
  texturePromise.catch(() => {
    texturePromise = null;
  });
  return texturePromise;
}

/** Unit-sphere position of a lon/lat, matching SphereGeometry's UV layout. */
export function lonLatToVec3(lonDeg: number, latDeg: number, out = new THREE.Vector3()) {
  const lon = THREE.MathUtils.degToRad(lonDeg);
  const lat = THREE.MathUtils.degToRad(latDeg);
  return out.set(Math.cos(lat) * Math.cos(lon), Math.sin(lat), -Math.cos(lat) * Math.sin(lon));
}

const EARTH_VERT = /* glsl */ `
  varying vec2 vUv;
  varying vec3 vNormal;
  varying vec3 vPos;
  void main() {
    vUv = uv;
    vNormal = normalize(mat3(modelMatrix) * normal);
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vPos = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

const COMMON = /* glsl */ `
  vec3 toLinear(vec3 c) { return pow(c, vec3(2.2)); }
  vec3 aces(vec3 x) {
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
  }
`;

const EARTH_FRAG = /* glsl */ `
  uniform sampler2D uDay;
  uniform sampler2D uLights;
  uniform sampler2D uWater;
  uniform sampler2D uTopo;
  uniform sampler2D uClouds;
  uniform vec3 uSun;
  uniform vec3 uCam;
  uniform vec2 uTexel;
  uniform float uCloudOffset;
  uniform float uExposure;
  uniform float uCloudAmount;
  varying vec2 vUv;
  varying vec3 vNormal;
  varying vec3 vPos;
  ${COMMON}

  void main() {
    vec3 N = normalize(vNormal);
    vec3 V = normalize(uCam - vPos);

    float water = texture2D(uWater, vUv).r;

    // Terrain relief: perturb the normal along east/north by the height slope.
    vec3 up = abs(N.y) > 0.999 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 1.0, 0.0);
    vec3 east = normalize(cross(up, N));
    vec3 north = cross(N, east);
    float h  = texture2D(uTopo, vUv).r;
    float hx = texture2D(uTopo, vUv + vec2(uTexel.x, 0.0)).r;
    float hy = texture2D(uTopo, vUv + vec2(0.0, uTexel.y)).r;
    vec3 Nb = normalize(N - 2.6 * (1.0 - water) * ((hx - h) * east + (hy - h) * north));

    float ndl = dot(N, uSun);
    float ndlB = dot(Nb, uSun);
    float dayMix = smoothstep(-0.12, 0.22, ndl);

    vec3 day = toLinear(texture2D(uDay, vUv).rgb);
    float lights = pow(texture2D(uLights, vUv).r, 1.6);
    float cloud = texture2D(uClouds, vUv + vec2(uCloudOffset, 0.0)).r * uCloudAmount;
    // Shadow sampled slightly toward the sun so it sits beside, not under, the cloud.
    float cloudShadow = texture2D(uClouds, vUv + vec2(uCloudOffset + 0.0015, 0.001)).r * uCloudAmount;

    // Lit surface — oceans pulled a touch deeper so the land reads.
    day *= mix(vec3(1.0), vec3(0.62, 0.78, 1.0), water * 0.55);
    // Ambient only survives into twilight; true night falls to near-black.
    vec3 col = day * (max(ndlB, 0.0) * 1.35 + 0.006 * smoothstep(-0.3, 0.05, ndl));
    col += vec3(0.0006, 0.0009, 0.0016) * (1.0 - dayMix);
    col *= 1.0 - cloudShadow * 0.45 * dayMix;

    // Sun glint on water only, broadened toward the limb.
    vec3 H = normalize(uSun + V);
    float nh = max(dot(N, H), 0.0);
    float glint = pow(nh, 220.0) * 0.8 + pow(nh, 40.0) * 0.025;
    col += vec3(1.0, 0.9, 0.74) * glint * water * smoothstep(0.0, 0.25, ndl) * (1.0 - cloud);

    // City lights on the night side, warm sodium tint, dimmed under clouds.
    float nightMix = 1.0 - smoothstep(-0.22, 0.08, ndl);
    col += lights * vec3(1.0, 0.66, 0.34) * 1.6 * nightMix * (1.0 - cloud * 0.75);

    // Warm band along the terminator.
    col += vec3(1.0, 0.38, 0.12) * 0.045 * exp(-pow(ndl * 7.0, 2.0)) * (1.0 - water * 0.4);

    // Aerial perspective: surface blues out toward the limb on the day side.
    float fres = pow(1.0 - max(dot(N, V), 0.0), 2.6);
    vec3 sky = vec3(0.22, 0.48, 1.0);
    col = mix(col, sky * (0.08 + 0.9 * max(ndl, 0.0)), fres * 0.72 * smoothstep(-0.25, 0.35, ndl));

    col = aces(col * uExposure);
    gl_FragColor = vec4(pow(col, vec3(1.0 / 2.2)), 1.0);
  }
`;

const CLOUD_FRAG = /* glsl */ `
  uniform sampler2D uClouds;
  uniform vec3 uSun;
  uniform vec3 uCam;
  uniform float uCloudOffset;
  uniform float uOpacity;
  varying vec2 vUv;
  varying vec3 vNormal;
  varying vec3 vPos;

  void main() {
    vec3 N = normalize(vNormal);
    vec3 V = normalize(uCam - vPos);
    float c = texture2D(uClouds, vUv + vec2(uCloudOffset, 0.0)).r;
    float ndl = dot(N, uSun);
    float lit = smoothstep(-0.12, 0.45, ndl);
    // Sunset-tinted edge of the lit side, near-black on the night side.
    vec3 tint = mix(vec3(1.0, 0.62, 0.4), vec3(1.0), smoothstep(0.0, 0.3, ndl));
    vec3 col = mix(vec3(0.015, 0.02, 0.035), tint * 0.96, lit);
    // Clouds thin out toward the limb so the edge of the planet stays crisp.
    float limb = smoothstep(0.0, 0.3, dot(N, V));
    float a = smoothstep(0.08, 0.9, c) * 0.92 * limb * uOpacity;
    gl_FragColor = vec4(col, a);
  }
`;

const ATMO_VERT = /* glsl */ `
  varying vec3 vPos;
  void main() {
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vPos = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

const ATMO_FRAG = /* glsl */ `
  uniform vec3 uSun;
  uniform vec3 uCam;
  uniform float uIntensity;
  varying vec3 vPos;

  void main() {
    // Closest approach of this pixel's view ray to the planet's centre.
    vec3 rd = normalize(vPos - uCam);
    float tca = max(-dot(uCam, rd), 0.0);
    vec3 p = uCam + rd * tca;
    float d = length(p);
    float alt = max(d - 1.0, 0.0);

    float density = exp(-alt / 0.022) * 0.9 + exp(-alt / 0.0055) * 0.55;
    float sd = dot(normalize(p), uSun);
    float sunSide = smoothstep(-0.32, 0.35, sd);
    vec3 dayBlue = vec3(0.28, 0.56, 1.0);
    vec3 dusk = vec3(1.0, 0.45, 0.18);
    vec3 col = mix(dusk, dayBlue, smoothstep(-0.05, 0.3, sd));
    // Forward scattering: brighter when looking toward the sun.
    float mie = pow(max(dot(rd, uSun), 0.0), 8.0) * 0.6;
    col = col * density * sunSide * (1.0 + mie) * uIntensity;
    gl_FragColor = vec4(col, 1.0);
  }
`;

const STAR_VERT = /* glsl */ `
  attribute float aSize;
  attribute vec3 aColor;
  varying vec3 vColor;
  uniform float uPixelRatio;
  void main() {
    vColor = aColor;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = aSize * uPixelRatio;
    gl_Position = projectionMatrix * mv;
  }
`;

const STAR_FRAG = /* glsl */ `
  varying vec3 vColor;
  uniform float uOpacity;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float r = length(c);
    float a = smoothstep(0.5, 0.0, r);
    a = a * a;
    gl_FragColor = vec4(vColor * a * uOpacity, 1.0);
  }
`;

export interface EarthCamera {
  lon: number;
  lat: number;
  /** Altitude above the surface in Earth radii. */
  alt: number;
  fov: number;
  /** Roll in degrees about the view axis. */
  roll: number;
}

/** Morning sun over the western Pacific: India in full daylight with its
 * glint well out to sea, dawn breaking over the Middle East, and Europe and
 * Africa still showing city lights on the opening shot. */
const SUN_DIR = lonLatToVec3(138, -4).normalize();

export class CinematicEarth {
  readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(32, 1, 0.001, 3000);
  private readonly earthMat: THREE.ShaderMaterial;
  private readonly cloudMat: THREE.ShaderMaterial;
  private readonly atmoMat: THREE.ShaderMaterial;
  private readonly starMat: THREE.ShaderMaterial;
  private readonly disposables: { dispose(): void }[] = [];
  private readonly camPos = new THREE.Vector3();
  private readonly scratch = new THREE.Vector3();

  constructor(canvas: HTMLCanvasElement, tex: EarthTextures) {
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      powerPreference: "high-performance",
    });
    // Capped at 1.5: on 2x/2.25x laptop panels the full ratio more than
    // doubles the pixels shaded for no visible gain in a moving shot.
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.setClearColor(0x010204, 1);
    tex.day.anisotropy = tex.lights.anisotropy = tex.clouds.anisotropy = Math.min(
      8,
      this.renderer.capabilities.getMaxAnisotropy(),
    );

    const earthGeo = new THREE.SphereGeometry(1, 192, 128);
    const cloudGeo = new THREE.SphereGeometry(1.007, 160, 96);
    const atmoGeo = new THREE.SphereGeometry(1.12, 96, 64);
    this.disposables.push(earthGeo, cloudGeo, atmoGeo);

    const shared = {
      uSun: { value: SUN_DIR },
      uCam: { value: this.camPos },
      uCloudOffset: { value: 0 },
    };

    this.earthMat = new THREE.ShaderMaterial({
      vertexShader: EARTH_VERT,
      fragmentShader: EARTH_FRAG,
      uniforms: {
        ...shared,
        uDay: { value: tex.day },
        uLights: { value: tex.lights },
        uWater: { value: tex.water },
        uTopo: { value: tex.topo },
        uClouds: { value: tex.clouds },
        uTexel: { value: new THREE.Vector2(1 / 2048, 1 / 1024) },
        uExposure: { value: 1.05 },
        uCloudAmount: { value: 1 },
      },
    });
    this.cloudMat = new THREE.ShaderMaterial({
      vertexShader: EARTH_VERT,
      fragmentShader: CLOUD_FRAG,
      uniforms: { ...shared, uClouds: { value: tex.clouds }, uOpacity: { value: 1 } },
      transparent: true,
      depthWrite: false,
    });
    this.atmoMat = new THREE.ShaderMaterial({
      vertexShader: ATMO_VERT,
      fragmentShader: ATMO_FRAG,
      uniforms: { uSun: shared.uSun, uCam: shared.uCam, uIntensity: { value: 1.25 } },
      side: THREE.BackSide,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    this.disposables.push(this.earthMat, this.cloudMat, this.atmoMat);

    const earth = new THREE.Mesh(earthGeo, this.earthMat);
    const clouds = new THREE.Mesh(cloudGeo, this.cloudMat);
    clouds.renderOrder = 1;
    const atmo = new THREE.Mesh(atmoGeo, this.atmoMat);
    atmo.renderOrder = 2;

    // Crisp foreground stars on top of the backdrop.
    const STAR_COUNT = 2600;
    const pos = new Float32Array(STAR_COUNT * 3);
    const size = new Float32Array(STAR_COUNT);
    const color = new Float32Array(STAR_COUNT * 3);
    const rand = mulberry32(7);
    for (let i = 0; i < STAR_COUNT; i++) {
      const u = rand() * 2 - 1;
      const th = rand() * Math.PI * 2;
      const r = Math.sqrt(1 - u * u);
      pos.set([r * Math.cos(th) * 1200, u * 1200, r * Math.sin(th) * 1200], i * 3);
      const m = Math.pow(rand(), 5);
      size[i] = 0.8 + m * 3.2;
      const temp = rand();
      const c =
        temp < 0.15 ? [1.0, 0.82, 0.66] : temp > 0.8 ? [0.72, 0.82, 1.0] : [0.95, 0.96, 1.0];
      const b = 0.35 + m * 0.9;
      color.set([c[0] * b, c[1] * b, c[2] * b], i * 3);
    }
    const starGeo = new THREE.BufferGeometry();
    starGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    starGeo.setAttribute("aSize", new THREE.BufferAttribute(size, 1));
    starGeo.setAttribute("aColor", new THREE.BufferAttribute(color, 3));
    this.starMat = new THREE.ShaderMaterial({
      vertexShader: STAR_VERT,
      fragmentShader: STAR_FRAG,
      uniforms: {
        uPixelRatio: { value: this.renderer.getPixelRatio() },
        uOpacity: { value: 1 },
      },
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const stars = new THREE.Points(starGeo, this.starMat);
    stars.renderOrder = -1;
    this.disposables.push(starGeo, this.starMat);

    this.scene.add(stars, earth, clouds, atmo);
  }

  setSize(width: number, height: number) {
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / Math.max(height, 1);
    this.camera.updateProjectionMatrix();
  }

  /** Positions the camera above lon/lat, looking at the planet's centre. */
  setCamera({ lon, lat, alt, fov, roll }: EarthCamera) {
    lonLatToVec3(lon, lat, this.camPos).multiplyScalar(1 + alt);
    this.camera.position.copy(this.camPos);
    this.camera.up.set(0, 1, 0);
    this.camera.lookAt(0, 0, 0);
    if (roll) this.camera.rotateZ(THREE.MathUtils.degToRad(roll));
    if (this.camera.fov !== fov) {
      this.camera.fov = fov;
      this.camera.updateProjectionMatrix();
    }
    // Close to the ground the stars give way to the atmosphere.
    this.starMat.uniforms.uOpacity.value = THREE.MathUtils.smoothstep(alt, 0.08, 0.6);
    // Cloud imagery is ~10 km/texel: lovely from orbit, smeary blobs up
    // close. Thin it out on the way down so the ground stays readable.
    const clouds = THREE.MathUtils.smoothstep(alt, 0.3, 1.4);
    this.cloudMat.uniforms.uOpacity.value = clouds;
    this.earthMat.uniforms.uCloudAmount.value = clouds;
  }

  /** Screen position (CSS px) of a lon/lat, or null when it faces away. */
  project(lon: number, lat: number, width: number, height: number) {
    const p = lonLatToVec3(lon, lat, this.scratch);
    const facing = p.dot(this.scratch.clone().copy(this.camPos).sub(p).normalize());
    if (facing < 0.08) return null;
    p.project(this.camera);
    return { x: (p.x * 0.5 + 0.5) * width, y: (-p.y * 0.5 + 0.5) * height, facing };
  }

  render(timeSec: number) {
    // Clouds drift slowly eastward relative to the ground.
    const offset = -timeSec * 0.0018;
    this.earthMat.uniforms.uCloudOffset.value = offset;
    this.cloudMat.uniforms.uCloudOffset.value = offset;
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    for (const d of this.disposables) d.dispose();
    this.renderer.dispose();
    // Free the GL context right away rather than waiting for GC — a second
    // run of the cinematic would otherwise stack contexts.
    this.renderer.forceContextLoss();
  }
}

function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
