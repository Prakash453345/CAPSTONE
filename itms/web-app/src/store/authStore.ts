import { create } from "zustand";
import { fetchSession, login, logout, type SessionUser } from "@/services/auth/authApi";

/**
 * Who is signed in. The session itself is an HttpOnly cookie the browser
 * holds; this store only mirrors what the server says about it, so a page
 * reload, another tab signing out, or an expired session all converge on the
 * server's answer.
 *
 *  - checking: the first /me call hasn't answered yet (gate renders a spinner)
 *  - authed:   the server confirmed a session
 *  - anon:     no session, or the sign-in service can't be reached
 */
export type AuthStatus = "checking" | "authed" | "anon";

interface AuthState {
  status: AuthStatus;
  user: SessionUser | null;
  /** The last session check couldn't reach a working sign-in service. */
  serviceDown: boolean;
  /** Re-ask the server who is signed in. Safe to call often. */
  check: () => Promise<void>;
  signIn: (username: string, password: string, signal?: AbortSignal) => Promise<void>;
  signOut: () => Promise<void>;
}

let inflight: Promise<void> | null = null;
/** Bumped by every sign-in/out so a /me call already on the wire when the
 *  session changed can't land afterwards and overwrite the newer answer. */
let epoch = 0;

export const useAuthStore = create<AuthState>((set, get) => ({
  status: "checking",
  user: null,
  serviceDown: false,

  check: () => {
    // Several callers (app start, tab focus, route guards) can ask at once.
    inflight ??= (async () => {
      const started = epoch;
      try {
        const user = await fetchSession();
        if (started !== epoch) return;
        set(
          user
            ? { status: "authed", user, serviceDown: false }
            : { status: "anon", user: null, serviceDown: false },
        );
      } catch {
        // A blip must not sign out someone mid-task: an already-confirmed
        // session stays until the server says 401.
        if (started === epoch && get().status !== "authed") {
          set({ status: "anon", user: null, serviceDown: true });
        }
      } finally {
        inflight = null;
      }
    })();
    return inflight;
  },

  signIn: async (username, password, signal) => {
    const user = await login(username, password, signal);
    epoch++;
    set({ status: "authed", user, serviceDown: false });
  },

  signOut: async () => {
    await logout();
    epoch++;
    set({ status: "anon", user: null, serviceDown: false });
  },
}));
