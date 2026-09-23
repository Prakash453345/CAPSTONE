const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

/** How long to wait for /health before deciding there is no backend. Short:
 *  this only decides whether to upgrade a working demo, so a slow answer is
 *  worth less than a fast render. */
export const PROBE_TIMEOUT_MS = 2_000;

/**
 * Is an api-service reachable? Used once at startup to upgrade the default
 * simulation session to a live one. Any failure -- refused, 5xx, proxy error,
 * timeout, or no `fetch` at all -- answers "no" and leaves the demo running.
 */
export async function isBackendReachable(
  timeoutMs = PROBE_TIMEOUT_MS,
): Promise<boolean> {
  if (typeof fetch !== "function") return false;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}/health`, {
      signal: controller.signal,
      cache: "no-store",
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
