let cached: boolean | undefined;

/**
 * Whether this browser can draw WebGL on a GPU. Without one (a VM, a locked-
 * down office PC, the GPU blocklisted) Chrome falls back to software
 * rendering, where the landing page's 3D scenes run at about 1 fps and stall
 * every click. The 3D renderers also pass `failIfMajorPerformanceCaveat`;
 * asking here first means three.js never tries, so it logs nothing.
 */
export function hasFastWebGL(): boolean {
  if (cached !== undefined) return cached;
  try {
    const canvas = document.createElement("canvas");
    const opts: WebGLContextAttributes = { failIfMajorPerformanceCaveat: true };
    const gl = canvas.getContext("webgl2", opts) ?? canvas.getContext("webgl", opts);
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
    cached = gl !== null;
  } catch {
    cached = false;
  }
  return cached;
}
