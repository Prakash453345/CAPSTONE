import { createHash } from "node:crypto";
import type { Plugin } from "vite";

/**
 * Content Security Policy for the built site, as a <meta> tag in index.html.
 *
 * It limits what the page may load or run to this site plus the services it
 * really uses, so an injected script or tag (say, HTML in a tile provider's
 * attribution, which MapLibre renders) cannot run or phone home:
 *
 *   tiles.openfreemap.org   basemap style, tiles, glyphs and sprites
 *   tile.googleapis.com     optional Google 3D tiles (VITE_GOOGLE_MAPS_API_KEY)
 *   api.open-meteo.com      weather
 *   fonts.googleapis.com / fonts.gstatic.com   Google Sans
 *   VITE_API_BASE / VITE_WS_URL                the backend, when not same-origin
 *
 * The one inline script (the theme pre-paint in index.html) is allowed by its
 * hash, computed here, so editing it can't silently break the policy.
 * MapLibre 4 starts its worker from a blob: URL. Styles allow 'unsafe-inline'
 * for the map's <style> block and inline style attributes; style injection
 * can't run code.
 *
 * Build only: the dev server injects its own inline scripts and HMR socket.
 * `frame-ancestors` (clickjacking) cannot be set from a meta tag; the host
 * should send `Content-Security-Policy: frame-ancestors 'none'` as a header.
 */
export function cspPlugin(): Plugin {
  const backend: string[] = [];
  return {
    name: "traffix-csp",
    apply: "build",
    configResolved(config) {
      for (const key of ["VITE_API_BASE", "VITE_WS_URL"]) {
        const value = config.env[key] as string | undefined;
        if (!value) continue;
        try {
          backend.push(new URL(value).origin); // relative ("/api") is already 'self'
        } catch {
          /* a path, not a URL */
        }
      }
    },
    transformIndexHtml(html) {
      const hashes = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(
        ([, body]) => `'sha256-${createHash("sha256").update(body!).digest("base64")}'`,
      );
      const policy = [
        "default-src 'self'",
        `script-src 'self' ${hashes.join(" ")}`,
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: blob: https://tiles.openfreemap.org https://tile.googleapis.com",
        [
          "connect-src 'self'",
          "https://tiles.openfreemap.org",
          "https://tile.googleapis.com",
          "https://api.open-meteo.com",
          ...backend,
          ...backend.map((o) => o.replace(/^http/, "ws")),
        ].join(" "),
        "worker-src 'self' blob:",
        "child-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        // no upgrade-insecure-requests: it would turn the console's ws:// live
        // link into wss:// and break plain-HTTP deployments (the team's local
        // setup). HTTPS is the host's job (redirect + HSTS header).
      ].join("; ");
      return [
        { tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: policy }, injectTo: "head-prepend" },
        { tag: "meta", attrs: { name: "referrer", content: "strict-origin-when-cross-origin" }, injectTo: "head-prepend" },
      ];
    },
  };
}
