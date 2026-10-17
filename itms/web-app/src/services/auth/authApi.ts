const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

/** How long to wait on the sign-in service before telling the operator it is unreachable. */
export const AUTH_TIMEOUT_MS = 10_000;

export interface SessionUser {
  username: string;
  displayName: string;
}

/**
 * Why a sign-in call failed, in terms the UI can act on:
 *  - invalid:     wrong username or password (the server never says which)
 *  - locked:      too many failed attempts; `retryAfterSec` says how long
 *  - unavailable: the service answered but can't sign anyone in right now
 *                 (database down, or no api-service behind /api at all)
 *  - network:     the request never got an answer (offline, timeout)
 *  - badcode:     the password-reset code is wrong, expired or used up
 *  - weak:        the new password was rejected; `detail` says why
 *  - unknown:     no such username (forgot password)
 *  - noemail:     the account has no email address to send a code to
 */
export type AuthFailure = "invalid" | "locked" | "unavailable" | "network" | "badcode" | "weak" | "unknown" | "noemail";

export class AuthError extends Error {
  constructor(
    readonly kind: AuthFailure,
    readonly retryAfterSec?: number,
    readonly detail?: string,
  ) {
    super(kind);
    this.name = "AuthError";
  }
}

async function call(path: string, init: RequestInit & { timeoutMs?: number } = {}): Promise<Response> {
  const { timeoutMs = AUTH_TIMEOUT_MS, signal, ...rest } = init;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  // Honour the caller's signal too (unmounting the login page cancels the request).
  signal?.addEventListener("abort", () => controller.abort(), { once: true });
  try {
    return await fetch(`${API_BASE}${path}`, {
      ...rest,
      signal: controller.signal,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new AuthError("network");
  } finally {
    clearTimeout(timer);
  }
}

/** A real api-service answers JSON. A static host with no backend answers
 *  index.html (200) for every path, which must read as "unavailable", not as a
 *  signed-in user. */
async function readUser(res: Response): Promise<SessionUser> {
  if (!(res.headers.get("content-type") ?? "").includes("application/json")) {
    throw new AuthError("unavailable");
  }
  const body: unknown = await res.json().catch(() => null);
  const b = body as { username?: unknown; display_name?: unknown } | null;
  if (!b || typeof b.username !== "string" || !b.username) throw new AuthError("unavailable");
  return {
    username: b.username,
    displayName: typeof b.display_name === "string" && b.display_name ? b.display_name : b.username,
  };
}

/** The current session's user, or null when nobody is signed in. */
export async function fetchSession(signal?: AbortSignal): Promise<SessionUser | null> {
  const res = await call("/v1/auth/me", { signal });
  if (res.status === 401) return null;
  if (!res.ok) throw new AuthError("unavailable");
  return readUser(res);
}

export async function login(username: string, password: string, signal?: AbortSignal): Promise<SessionUser> {
  const res = await call("/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    signal,
  });
  if (res.status === 401) throw new AuthError("invalid");
  if (res.status === 429) {
    const seconds = Number(res.headers.get("retry-after"));
    throw new AuthError("locked", Number.isFinite(seconds) && seconds > 0 ? seconds : undefined);
  }
  // 400/404/405 from a host that isn't api-service, and 5xx, both land here.
  if (!res.ok) throw new AuthError("unavailable");
  return readUser(res);
}

export async function logout(): Promise<void> {
  const res = await call("/v1/auth/logout", { method: "POST" });
  if (!res.ok) throw new AuthError("unavailable");
}

// ------------------------------------------------------------ forgot password

const JSON_POST = { method: "POST", headers: { "Content-Type": "application/json" } } as const;

/** Ask for a reset code by email. Resolves with a masked address ("k***@x.org")
 *  so the operator can see where it went. */
export async function requestResetCode(username: string, signal?: AbortSignal): Promise<string> {
  const res = await call("/v1/auth/forgot", { ...JSON_POST, body: JSON.stringify({ username }), signal });
  if (res.status === 404) throw new AuthError("unknown");
  if (res.status === 409) throw new AuthError("noemail");
  if (res.status === 503) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
    throw new AuthError("unavailable", undefined, typeof body?.detail === "string" ? body.detail : undefined);
  }
  if (res.status !== 202) throw new AuthError("unavailable");
  const body = (await res.json().catch(() => null)) as { email_hint?: unknown } | null;
  return typeof body?.email_hint === "string" ? body.email_hint : "your email";
}

/** Check a code without using it. Throws "badcode" when it is wrong or expired. */
export async function verifyResetCode(username: string, code: string, signal?: AbortSignal): Promise<void> {
  const res = await call("/v1/auth/forgot/verify", {
    ...JSON_POST,
    body: JSON.stringify({ username, code }),
    signal,
  });
  if (res.status === 400) throw new AuthError("badcode");
  if (res.status !== 204) throw new AuthError("unavailable");
}

export async function resetPassword(
  username: string,
  code: string,
  newPassword: string,
  signal?: AbortSignal,
): Promise<void> {
  const res = await call("/v1/auth/forgot/reset", {
    ...JSON_POST,
    body: JSON.stringify({ username, code, new_password: newPassword }),
    signal,
  });
  if (res.status === 400) throw new AuthError("badcode");
  if (res.status === 422) {
    const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
    throw new AuthError("weak", undefined, typeof body?.detail === "string" ? body.detail : undefined);
  }
  if (res.status !== 204) throw new AuthError("unavailable");
}
