import type { ExpressionSpecification, Map as MapLibreMap } from "maplibre-gl";
import type { ResolvedTheme } from "@/store/themeStore";

/**
 * Apple Maps' point-of-interest badges: a disc in the category's colour with
 * a white glyph, and the place name beside it in a tint of the same colour.
 * Drawn to canvas once per map (WebGL can't sample SVG images), keyed by the
 * OpenMapTiles `class` of each POI.
 */

type Category =
  | "food"
  | "shop"
  | "lodging"
  | "health"
  | "park"
  | "fun"
  | "worship"
  | "education"
  | "transit"
  | "other";

interface Spec {
  classes: string[];
  /** The badge's disc. */
  disc: string;
  /** Label colour on each theme's land. */
  text: Record<ResolvedTheme, string>;
  /** Lucide glyph paths on a 24-unit grid (ISC licence). */
  glyph: string[];
  fill?: boolean;
  weight?: number;
}

const CATEGORIES: Record<Category, Spec> = {
  food: {
    classes: ["restaurant", "fast_food", "cafe", "bar", "beer", "ice_cream", "bakery", "food_court"],
    disc: "#ff9500",
    text: { dark: "#ffb44d", light: "#b85f00" },
    glyph: ["M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2", "M7 2v20", "M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"],
  },
  shop: {
    classes: [
      "shop", "grocery", "clothing_store", "alcohol_shop", "jewelry", "department_store", "furniture",
      "florist", "books", "electronics", "hairdresser", "laundry", "mobile_phone", "shoes", "gift", "mall",
    ],
    disc: "#f2b200",
    text: { dark: "#ffd25e", light: "#8f6a00" },
    glyph: ["M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z", "M3 6h18", "M16 10a4 4 0 0 1-8 0"],
  },
  lodging: {
    classes: ["lodging"],
    disc: "#9f7aff",
    text: { dark: "#c4abff", light: "#6f47d6" },
    glyph: ["M2 4v16", "M2 8h18a2 2 0 0 1 2 2v10", "M2 17h20", "M6 8v9"],
  },
  health: {
    classes: ["hospital", "doctors", "dentist", "pharmacy", "veterinary", "clinic"],
    disc: "#ff3b30",
    text: { dark: "#ff7b72", light: "#cc2219" },
    glyph: ["M12 4v16", "M4 12h16"],
    weight: 4.2,
  },
  park: {
    classes: ["park", "garden", "golf", "zoo", "campsite", "pitch", "stadium", "swimming", "playground"],
    disc: "#2fbf5b",
    text: { dark: "#62db88", light: "#1c7f39" },
    glyph: [
      "M8 19a4 4 0 0 1-2.24-7.32A3.5 3.5 0 0 1 9 6.03V6a3 3 0 1 1 6 0v.04a3.5 3.5 0 0 1 3.24 5.65A4 4 0 0 1 16 19Z",
      "M12 19v3",
    ],
  },
  fun: {
    classes: ["cinema", "theatre", "music", "art_gallery", "museum", "attraction", "entertainment", "castle", "monument"],
    disc: "#ff4f8b",
    text: { dark: "#ff8db3", light: "#c42862" },
    glyph: [
      "M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z",
    ],
    fill: true,
  },
  worship: {
    classes: ["place_of_worship"],
    disc: "#7476f2",
    text: { dark: "#a9abff", light: "#4c4fd0" },
    glyph: ["M3 22h18", "M6 18v-7", "M10 18v-7", "M14 18v-7", "M18 18v-7", "M12 2 20 7H4z"],
  },
  education: {
    classes: ["school", "college", "library", "kindergarten", "university"],
    disc: "#b07d4f",
    text: { dark: "#dcb08a", light: "#83552d" },
    glyph: [
      "M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z",
      "M22 10v6",
      "M6 12.5V16a6 3 0 0 0 12 0v-3.5",
    ],
  },
  transit: {
    classes: ["bus", "railway", "airport", "ferry_terminal", "aerialway", "fuel", "parking", "car"],
    disc: "#1f87ff",
    text: { dark: "#7ab8ff", light: "#1462c2" },
    glyph: [
      "M8 3.1V7a4 4 0 0 0 8 0V3.1",
      "m9 15-1-1",
      "m15 15 1-1",
      "M9 19c-2.8 0-5-2.2-5-5v-4a8 8 0 0 1 16 0v4c0 2.8-2.2 5-5 5Z",
      "m8 19-2 3",
      "m16 19 2 3",
    ],
  },
  other: {
    classes: [],
    disc: "#8592a8",
    text: { dark: "#bac6d8", light: "#5b6577" },
    glyph: ["M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8z"],
    fill: true,
  },
};

const ORDER = Object.keys(CATEGORIES) as Category[];
const iconId = (c: Category) => `poi-badge-${c}`;

/** `class` → category, as a MapLibre match over the POI's class. */
function byCategory(pick: (c: Category) => string): ExpressionSpecification {
  const arms: unknown[] = [];
  for (const c of ORDER) {
    if (c === "other") continue;
    arms.push(CATEGORIES[c].classes, pick(c));
  }
  return ["match", ["get", "class"], ...arms, pick("other")] as unknown as ExpressionSpecification;
}

export const POI_ICON = byCategory(iconId);
export const poiTextColor = (theme: ResolvedTheme) => byCategory((c) => CATEGORIES[c].text[theme]);

const SIZE = 20; // logical px, Apple's badge at city zooms
const RATIO = 2;

function drawBadge(spec: Spec): ImageData {
  const px = (SIZE + 4) * RATIO;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = px;
  const ctx = canvas.getContext("2d")!;
  ctx.scale(RATIO, RATIO);
  const c = (SIZE + 4) / 2;

  ctx.shadowColor = "rgba(0, 0, 0, 0.35)";
  ctx.shadowBlur = 2;
  ctx.shadowOffsetY = 0.5;
  ctx.beginPath();
  ctx.arc(c, c, SIZE / 2, 0, Math.PI * 2);
  ctx.fillStyle = spec.disc;
  ctx.fill();
  ctx.shadowColor = "transparent";
  // a hairline of white keeps the disc crisp against dark land
  ctx.lineWidth = 1;
  ctx.strokeStyle = "rgba(255, 255, 255, 0.35)";
  ctx.stroke();

  const glyph = 11.5;
  ctx.translate(c - glyph / 2, c - glyph / 2);
  ctx.scale(glyph / 24, glyph / 24);
  ctx.strokeStyle = ctx.fillStyle = "#ffffff";
  ctx.lineWidth = spec.weight ?? 2.8;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  for (const d of spec.glyph) {
    const path = new Path2D(d);
    if (spec.fill) ctx.fill(path);
    else ctx.stroke(path);
  }
  return ctx.getImageData(0, 0, px, px);
}

let drawn: Map<Category, ImageData> | null = null;

/** Registers every badge on `map` (idempotent), before the POI layers ask for them. */
export function addPoiBadges(map: MapLibreMap) {
  drawn ??= new Map(ORDER.map((c) => [c, drawBadge(CATEGORIES[c])]));
  for (const [c, img] of drawn) {
    const id = iconId(c);
    if (map.hasImage(id)) map.removeImage(id);
    map.addImage(id, img, { pixelRatio: RATIO });
  }
}
