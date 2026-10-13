import * as THREE from "three";

/**
 * A lit box-body ambulance for the hero scene, modelled for the view the
 * hero actually shows: from just behind and above, then from the air.
 *
 * The rear doors, livery and lamps are painted onto canvas textures (colour
 * plus an emissive map for the tail lights), so the model stays a handful of
 * boxes while reading as a real vehicle. It is the only lit object in the
 * scene: the street lamps it passes, the car behind it and its own beacons
 * light it, which is what makes it sit in the night instead of on top of it.
 */

const W = 2.2; // body width
const BOX_H = 2.24; // rear module height
const FLOOR = 0.64; // underside of the rear module
const BOX_LEN = 3.9;
const CAB_LEN = 1.9;
const HOOD_LEN = 0.7;

const RED = "#d3122a";
const BLUE = "#1c4fd6";

function canvas(w: number, h: number) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return [c, c.getContext("2d")!] as const;
}

function texture(c: HTMLCanvasElement, srgb = true) {
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

function roundRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  g.beginPath();
  g.roundRect(x, y, w, h, r);
}

/** Painted white panel with soft edge shading and road grime at the bottom. */
function paintPanel(g: CanvasRenderingContext2D, w: number, h: number) {
  const base = g.createLinearGradient(0, 0, 0, h);
  base.addColorStop(0, "#f4f6f8");
  base.addColorStop(0.75, "#e3e7eb");
  base.addColorStop(1, "#b9bdc2");
  g.fillStyle = base;
  g.fillRect(0, 0, w, h);
  const edge = 16;
  const shade = (x0: number, y0: number, x1: number, y1: number, rx: number, ry: number, rw: number, rh: number) => {
    const gr = g.createLinearGradient(x0, y0, x1, y1);
    gr.addColorStop(0, "rgba(40,46,56,.45)");
    gr.addColorStop(1, "rgba(40,46,56,0)");
    g.fillStyle = gr;
    g.fillRect(rx, ry, rw, rh);
  };
  shade(0, 0, edge, 0, 0, 0, edge, h);
  shade(w, 0, w - edge, 0, w - edge, 0, edge, h);
  shade(0, 0, 0, edge, 0, 0, w, edge);
  shade(0, h, 0, h - edge, 0, h - edge, w, edge);
}

/** The Star of Life: three crossed bars with a white rim, and the staff. */
function starOfLife(g: CanvasRenderingContext2D, cx: number, cy: number, r: number) {
  g.save();
  g.translate(cx, cy);
  const arm = (fill: string, grow: number) => {
    g.fillStyle = fill;
    for (let i = 0; i < 3; i++) {
      g.save();
      g.rotate((i * Math.PI) / 3);
      roundRect(g, -r * 0.24 - grow, -r - grow, r * 0.48 + grow * 2, r * 2 + grow * 2, r * 0.06);
      g.fill();
      g.restore();
    }
  };
  arm("#ffffff", r * 0.08);
  arm(BLUE, 0);
  g.strokeStyle = "#ffffff";
  g.lineWidth = r * 0.07;
  g.beginPath();
  g.moveTo(0, -r * 0.7);
  g.lineTo(0, r * 0.7);
  g.stroke();
  g.beginPath();
  for (let k = 0; k <= 16; k++) {
    const y = -r * 0.5 + (k / 16) * r * 1.1;
    const x = Math.sin(k * 0.9) * r * 0.16;
    if (k === 0) g.moveTo(x, y);
    else g.lineTo(x, y);
  }
  g.stroke();
  g.restore();
}

function rearTextures() {
  const S = 512;
  const [c, g] = canvas(S, S);
  const [ec, eg] = canvas(S, S);
  eg.fillStyle = "#000";
  eg.fillRect(0, 0, S, S);

  paintPanel(g, S, S);

  // door shut lines and the centre seam
  g.strokeStyle = "rgba(70,76,86,.75)";
  g.lineWidth = 3;
  roundRect(g, 44, 30, S - 88, S - 50, 10);
  g.stroke();
  g.beginPath();
  g.moveTo(S / 2, 30);
  g.lineTo(S / 2, S - 20);
  g.stroke();
  g.strokeStyle = "rgba(255,255,255,.6)";
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(S / 2 + 2.5, 30);
  g.lineTo(S / 2 + 2.5, S - 20);
  g.stroke();

  // tinted rear windows with a frosted Star of Life decal
  for (const x of [70, S / 2 + 20]) {
    const ww = S / 2 - 90;
    roundRect(g, x - 4, 58, ww + 8, 142, 16);
    g.fillStyle = "#2a2f36";
    g.fill();
    const glass = g.createLinearGradient(x, 62, x + ww, 196);
    glass.addColorStop(0, "#1b2430");
    glass.addColorStop(0.55, "#0b1017");
    glass.addColorStop(1, "#141b25");
    roundRect(g, x, 62, ww, 134, 13);
    g.fillStyle = glass;
    g.fill();
    g.save();
    g.clip();
    g.fillStyle = "rgba(255,255,255,.07)";
    g.beginPath();
    g.moveTo(x + 20, 62);
    g.lineTo(x + 70, 62);
    g.lineTo(x + 10, 196);
    g.lineTo(x - 40, 196);
    g.fill();
    g.restore();
    starOfLife(g, x + ww / 2, 129, 44);
  }

  // livery: the word, a red band with a blue pinstripe, then chevrons
  g.fillStyle = RED;
  g.font = "900 58px 'Arial Black', 'Google Sans Flex', Arial, sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText("AMBULANCE", S / 2, 250, S - 110);
  g.fillStyle = RED;
  g.fillRect(0, 292, S, 30);
  g.fillStyle = BLUE;
  g.fillRect(0, 326, S, 9);

  g.save();
  g.beginPath();
  g.rect(44, 356, S - 88, 110);
  g.clip();
  for (let i = -12; i < 14; i++) {
    const x = S / 2 + i * 44;
    const dir = i < 0 ? -1 : 1;
    g.fillStyle = i % 2 === 0 ? RED : "#f5f6f7";
    g.beginPath();
    g.moveTo(x, 356);
    g.lineTo(x + 44, 356);
    g.lineTo(x + 44 + dir * 110, 466);
    g.lineTo(x + dir * 110, 466);
    g.fill();
  }
  g.restore();
  g.strokeStyle = "rgba(60,66,76,.5)";
  g.lineWidth = 2;
  g.strokeRect(44, 356, S - 88, 110);

  // door handles
  g.fillStyle = "#3a3f47";
  roundRect(g, S / 2 - 30, 268, 20, 12, 3);
  g.fill();
  roundRect(g, S / 2 + 10, 268, 20, 12, 3);
  g.fill();

  // vertical tail-light clusters on each rear pillar: reverse, indicator, tail
  for (const x of [8, S - 36]) {
    g.fillStyle = "#15181d";
    roundRect(g, x - 3, 232, 34, 244, 8);
    g.fill();
    const seg = (y: number, h: number, col: string, glow: string | null) => {
      roundRect(g, x, y, 28, h, 5);
      g.fillStyle = col;
      g.fill();
      if (glow) {
        roundRect(eg, x, y, 28, h, 5);
        eg.fillStyle = glow;
        eg.fill();
      }
    };
    seg(236, 46, "#d9dde2", null);
    seg(286, 50, "#c97a18", null);
    seg(340, 132, "#b3101c", "#ff2414");
  }

  // amber roof marker lamps and the high-level brake light
  for (const x of [22, S - 62]) {
    roundRect(g, x, 8, 40, 12, 5);
    g.fillStyle = "#e08a1c";
    g.fill();
    roundRect(eg, x, 8, 40, 12, 5);
    eg.fillStyle = "#ff8c14";
    eg.fill();
  }
  roundRect(g, S / 2 - 50, 8, 100, 10, 4);
  g.fillStyle = "#7a0c12";
  g.fill();
  roundRect(eg, S / 2 - 50, 8, 100, 10, 4);
  eg.fillStyle = "#5a0806";
  eg.fill();

  return { map: texture(c), emissive: texture(ec) };
}

function sideTexture() {
  const [c, g] = canvas(1024, 512);
  paintPanel(g, 1024, 512);
  g.fillStyle = RED;
  g.fillRect(0, 292, 1024, 30);
  g.fillStyle = BLUE;
  g.fillRect(0, 326, 1024, 9);
  starOfLife(g, 512, 150, 70);
  return texture(c);
}

function cabSideTexture() {
  const [c, g] = canvas(512, 512);
  paintPanel(g, 512, 512);
  const glass = g.createLinearGradient(0, 40, 0, 230);
  glass.addColorStop(0, "#1d2631");
  glass.addColorStop(1, "#0a0e14");
  roundRect(g, 40, 40, 432, 200, 22);
  g.fillStyle = glass;
  g.fill();
  g.fillStyle = RED;
  g.fillRect(0, 330, 512, 30);
  g.fillStyle = BLUE;
  g.fillRect(0, 364, 512, 9);
  return texture(c);
}

function roofTexture() {
  const [c, g] = canvas(256, 512);
  paintPanel(g, 256, 512);
  g.fillStyle = "rgba(90,96,106,.25)";
  for (let y = 40; y < 512; y += 46) g.fillRect(20, y, 216, 3);
  return texture(c);
}

function plateTexture() {
  const [c, g] = canvas(256, 64);
  g.fillStyle = "#f2f2ee";
  g.fillRect(0, 0, 256, 64);
  g.strokeStyle = "#111";
  g.lineWidth = 4;
  g.strokeRect(3, 3, 250, 58);
  g.fillStyle = "#111";
  g.font = "700 34px 'Arial Narrow', Arial, sans-serif";
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.fillText("AP 16 EM 108", 128, 34, 236);
  return texture(c);
}

function shadowTexture() {
  const [c, g] = canvas(128, 256);
  const gr = g.createRadialGradient(64, 128, 10, 64, 128, 128);
  gr.addColorStop(0, "rgba(0,0,0,.85)");
  gr.addColorStop(0.55, "rgba(0,0,0,.55)");
  gr.addColorStop(1, "rgba(0,0,0,0)");
  g.fillStyle = gr;
  g.fillRect(0, 0, 128, 256);
  return texture(c, false);
}

export class AmbulanceModel {
  readonly group = new THREE.Group();
  /** World positions (relative to the group) of the lamps other effects anchor to. */
  readonly anchors = {
    tail: [
      new THREE.Vector3(-W / 2 + 0.07, FLOOR + BOX_H * (1 - 406 / 512), BOX_LEN / 2 + 0.03),
      new THREE.Vector3(W / 2 - 0.07, FLOOR + BOX_H * (1 - 406 / 512), BOX_LEN / 2 + 0.03),
    ],
    beaconRear: [
      new THREE.Vector3(-W / 2 + 0.2, FLOOR + BOX_H + 0.1, BOX_LEN / 2 - 0.12),
      new THREE.Vector3(W / 2 - 0.2, FLOOR + BOX_H + 0.1, BOX_LEN / 2 - 0.12),
    ],
    beaconFront: [
      new THREE.Vector3(-0.5, FLOOR + BOX_H + 0.12, -BOX_LEN / 2 + 0.2),
      new THREE.Vector3(0.5, FLOOR + BOX_H + 0.12, -BOX_LEN / 2 + 0.2),
    ],
  };
  private body = new THREE.Group();
  private wheels: THREE.Mesh[] = [];
  private textures: THREE.Texture[] = [];
  private beaconMats: THREE.MeshStandardMaterial[] = [];
  private beaconLights: THREE.PointLight[] = [];
  private lampLights: THREE.PointLight[] = [];
  private follow: THREE.SpotLight;

  constructor(scene: THREE.Scene) {
    const rear = rearTextures();
    const side = sideTexture();
    const cabSide = cabSideTexture();
    const roof = roofTexture();
    const plate = plateTexture();
    const shadow = shadowTexture();
    this.textures.push(rear.map, rear.emissive, side, cabSide, roof, plate, shadow);

    const paint = (map: THREE.Texture | null, extra: Partial<THREE.MeshPhysicalMaterialParameters> = {}) =>
      new THREE.MeshPhysicalMaterial({
        color: 0xffffff,
        map,
        roughness: 0.42,
        metalness: 0,
        clearcoat: 0.45,
        clearcoatRoughness: 0.18,
        ...extra,
      });
    const plain = paint(null, { color: 0xe6e9ec });
    const underside = new THREE.MeshStandardMaterial({ color: 0x0b0c0e, roughness: 0.9 });
    const glass = new THREE.MeshPhysicalMaterial({ color: 0x0a0f15, roughness: 0.08, metalness: 0, clearcoat: 1 });
    const trim = new THREE.MeshStandardMaterial({ color: 0x1b1e23, roughness: 0.55, metalness: 0.2 });

    // rear module (box faces: +x, -x, +y, -y, +z rear, -z front)
    const rearMat = paint(rear.map, { emissiveMap: rear.emissive, emissive: 0xffffff, emissiveIntensity: 1.7 });
    const sideMat = paint(side);
    const roofMat = paint(roof);
    const box = new THREE.Mesh(new THREE.BoxGeometry(W, BOX_H, BOX_LEN), [sideMat, sideMat, roofMat, underside, rearMat, plain]);
    box.position.set(0, FLOOR + BOX_H / 2, 0);
    this.body.add(box);

    // cab and bonnet, a little narrower and lower than the box
    const cabH = 1.72;
    const cabSideMat = paint(cabSide);
    const cab = new THREE.Mesh(new THREE.BoxGeometry(W - 0.12, cabH, CAB_LEN), [
      cabSideMat,
      cabSideMat,
      roofMat,
      underside,
      plain,
      glass,
    ]);
    cab.position.set(0, FLOOR - 0.06 + cabH / 2, -BOX_LEN / 2 - CAB_LEN / 2);
    this.body.add(cab);
    const hood = new THREE.Mesh(new THREE.BoxGeometry(W - 0.16, 0.8, HOOD_LEN), plain);
    hood.position.set(0, FLOOR - 0.06 + 0.4, -BOX_LEN / 2 - CAB_LEN - HOOD_LEN / 2 + 0.02);
    this.body.add(hood);

    // wing mirrors: they poke out past the box, so you see them from behind
    for (const s of [-1, 1]) {
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.04, 0.04), trim);
      arm.position.set(s * (W / 2 + 0.02), 1.72, -BOX_LEN / 2 - 0.35);
      const head = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.34, 0.2), trim);
      head.position.set(s * (W / 2 + 0.14), 1.72, -BOX_LEN / 2 - 0.35);
      this.body.add(arm, head);
    }

    // rear bumper, step and number plate
    const bumper = new THREE.Mesh(new THREE.BoxGeometry(W + 0.04, 0.24, 0.34), trim);
    bumper.position.set(0, FLOOR - 0.12, BOX_LEN / 2 + 0.08);
    const step = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.05, 0.3), new THREE.MeshStandardMaterial({ color: 0x2b2f35, roughness: 0.4, metalness: 0.6 }));
    step.position.set(0, FLOOR - 0.005, BOX_LEN / 2 + 0.12);
    const plateMesh = new THREE.Mesh(
      new THREE.PlaneGeometry(0.52, 0.13),
      new THREE.MeshStandardMaterial({ map: plate, roughness: 0.5, emissive: 0xffffff, emissiveMap: plate, emissiveIntensity: 0.18 }),
    );
    plateMesh.position.set(0, FLOOR - 0.12, BOX_LEN / 2 + 0.252);
    this.body.add(bumper, step, plateMesh);

    // chassis shadow between the wheels, a roof air-con pod and the beacons
    const chassis = new THREE.Mesh(new THREE.BoxGeometry(1.7, 0.36, BOX_LEN + CAB_LEN), underside);
    chassis.position.set(0, FLOOR - 0.2, -CAB_LEN / 2);
    const pod = new THREE.Mesh(new THREE.BoxGeometry(0.95, 0.2, 0.8), paint(null, { color: 0xd4d8dc }));
    pod.position.set(0, FLOOR + BOX_H + 0.1, 0.4);
    this.body.add(chassis, pod);

    const beacon = (pos: THREE.Vector3, color: number, size: [number, number, number]) => {
      const mat = new THREE.MeshStandardMaterial({ color: 0x1a0a0a, emissive: color, emissiveIntensity: 1, roughness: 0.2 });
      const m = new THREE.Mesh(new THREE.BoxGeometry(...size), mat);
      m.position.copy(pos);
      this.body.add(m);
      this.beaconMats.push(mat);
    };
    const [rl, rr] = this.anchors.beaconRear;
    const [fl, fr] = this.anchors.beaconFront;
    beacon(rl!, 0xff1a24, [0.24, 0.14, 0.14]);
    beacon(rr!, 0x2a5cff, [0.24, 0.14, 0.14]);
    beacon(fl!, 0xff1a24, [0.8, 0.14, 0.3]);
    beacon(fr!, 0x2a5cff, [0.8, 0.14, 0.3]);
    const bar = new THREE.Mesh(new THREE.BoxGeometry(1.75, 0.08, 0.34), trim);
    bar.position.set(0, FLOOR + BOX_H + 0.03, -BOX_LEN / 2 + 0.2);
    this.body.add(bar);

    // the beacons light the bodywork around them
    for (const [pos, color] of [
      [rl!, 0xff2a2a],
      [rr!, 0x3a66ff],
    ] as const) {
      const l = new THREE.PointLight(color, 0, 7, 2);
      l.position.copy(pos).add(new THREE.Vector3(0, 0.25, 0.35));
      this.beaconLights.push(l);
      this.body.add(l);
    }

    this.group.add(this.body);

    // wheels (they do not bob with the body)
    const tyre = new THREE.MeshStandardMaterial({ color: 0x101114, roughness: 0.92 });
    const rim = new THREE.MeshStandardMaterial({ color: 0x8d949e, roughness: 0.3, metalness: 0.85 });
    const tyreGeo = new THREE.CylinderGeometry(0.39, 0.39, 0.28, 28).rotateZ(Math.PI / 2);
    const rimGeo = new THREE.CylinderGeometry(0.22, 0.22, 0.29, 18).rotateZ(Math.PI / 2);
    for (const z of [BOX_LEN / 2 - 0.9, -BOX_LEN / 2 - CAB_LEN + 0.45])
      for (const s of [-1, 1]) {
        const w = new THREE.Mesh(tyreGeo, tyre);
        w.add(new THREE.Mesh(rimGeo, rim));
        w.position.set(s * (W / 2 - 0.2), 0.39, z);
        this.wheels.push(w);
        this.group.add(w);
      }

    // soft contact shadow under the vehicle
    const shade = new THREE.Mesh(
      new THREE.PlaneGeometry(W + 1.1, BOX_LEN + CAB_LEN + HOOD_LEN + 1.6).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ map: shadow, transparent: true, depthWrite: false, color: 0x000000, opacity: 0.9 }),
    );
    shade.position.set(0, 0.025, -CAB_LEN / 2);
    shade.renderOrder = 0.5;
    this.group.add(shade);

    // sodium light from the street lamps it passes, repositioned every frame
    for (let i = 0; i < 4; i++) {
      const l = new THREE.PointLight(0xffa04a, 0, 48, 2);
      this.lampLights.push(l);
      scene.add(l);
    }
    // headlights of the car we're riding behind in
    this.follow = new THREE.SpotLight(0xffeedd, 95, 60, 0.3, 0.7, 2);
    scene.add(this.follow, this.follow.target);
    scene.add(new THREE.HemisphereLight(0x51607f, 0x1a130c, 0.4));

    scene.add(this.group);
  }

  /**
   * @param wave 0..1, red↔blue beacon phase
   * @param roll distance travelled this frame (m), turns the wheels
   * @param lampZ world z of the street lamps nearest the vehicle
   */
  update(t: number, wave: number, roll: number, lampZ: number[], lampX: number, lampY: number) {
    // a light, irregular suspension settle
    this.body.position.y = 0.012 * Math.sin(t * 7.1) + 0.006 * Math.sin(t * 13.7 + 1);
    this.body.rotation.z = 0.004 * Math.sin(t * 3.3);
    this.body.rotation.x = 0.002 * Math.sin(t * 5.1 + 0.4);
    for (const w of this.wheels) w.rotation.x -= roll / 0.39;

    const red = 0.2 + 0.8 * wave;
    const blue = 0.2 + 0.8 * (1 - wave);
    this.beaconMats.forEach((m, i) => (m.emissiveIntensity = (i % 2 === 0 ? red : blue) * 6));
    this.beaconLights[0]!.intensity = red * 2.5;
    this.beaconLights[1]!.intensity = blue * 4;

    const g = this.group.position;
    this.lampLights.forEach((l, i) => {
      const z = lampZ[i >> 1];
      if (z === undefined) {
        l.intensity = 0;
        return;
      }
      l.position.set((i % 2 === 0 ? -1 : 1) * lampX, lampY, z);
      l.intensity = 110;
    });
    this.follow.position.set(g.x - 1.1, 1.0, g.z + 22);
    this.follow.target.position.set(g.x, 1.3, g.z);
  }

  dispose() {
    this.textures.forEach((t) => t.dispose());
  }
}
