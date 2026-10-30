const FALLBACK = "/console";
const AREAS = ["/console", "/crew"];

/**
 * Where to go after signing in. `?next=` is attacker-controllable (anyone can
 * send a link to /login?next=...), so only paths inside the console or the crew
 * page are honoured. Anything else -- another site, a protocol-relative `//host`,
 * a backslash trick, control characters -- becomes `fallback`.
 */
export function safeNext(raw: string | null | undefined, fallback: string = FALLBACK): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return fallback;
  // eslint-disable-next-line no-control-regex
  if (raw.includes("\\") || /[\u0000-\u001f\u007f]/.test(raw)) return fallback;
  let url: URL;
  try {
    url = new URL(raw, "http://placeholder.invalid");
  } catch {
    return fallback;
  }
  if (url.origin !== "http://placeholder.invalid") return fallback;
  if (!AREAS.some((a) => url.pathname === a || url.pathname.startsWith(`${a}/`))) return fallback;
  return url.pathname + url.search + url.hash;
}
