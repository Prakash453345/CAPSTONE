/**
 * Minimal stand-in for the `framer` package, which only exists inside the
 * Framer editor/canvas runtime. TacticalGlobe3D.js (a vendored Framer code
 * component, see that file's header) imports `addPropertyControls`,
 * `ControlType` and `RenderTarget` purely to register its editor property
 * panel and to detect the Framer canvas — none of that applies when the
 * component runs standalone in this app, so every export here is inert.
 * Aliased in vite.config.ts so `import ... from "framer"` resolves to this
 * file instead of hitting the real (unavailable) package.
 */

export function addPropertyControls(..._args: unknown[]): void {
  // no-op — property panels only exist inside the Framer editor
}

export const ControlType = {
  Object: "object",
  Number: "number",
  Boolean: "boolean",
  Color: "color",
  Array: "array",
  Enum: "enum",
  String: "string",
  Link: "link",
} as const;

export const RenderTarget = {
  canvas: "CANVAS",
  export: "EXPORT",
  preview: "PREVIEW",
  thumbnail: "THUMBNAIL",
  current: () => RenderTarget.export,
} as const;

export { motion } from "framer-motion";
