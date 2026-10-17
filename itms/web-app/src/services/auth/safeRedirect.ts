const FALLBACK = "/console";

/**
 * Where to go after signing in. `?next=` is attacker-controllable (anyone can
 * send a link to /login?next=...), so only paths inside the console are
 * honoured. Anything else -- another site, a protocol-relative `//host`, a
 * backslash trick, control characters -- becomes the console home.
 */
export function safeNext(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return FALLBACK;
  // eslint-disable-next-line no-control-regex
  if (raw.includes("\\") || /[\u0000-\u001f\u007f]/.test(raw)) return FALLBACK;
  let url: URL;
  try {
    url = new URL(raw, "http://placeholder.invalid");
  } catch {
    return FALLBACK;
  }
  if (url.origin !== "http://placeholder.invalid") return FALLBACK;
  if (url.pathname !== "/console" && !url.pathname.startsWith("/console/")) return FALLBACK;
  return url.pathname + url.search + url.hash;
}
