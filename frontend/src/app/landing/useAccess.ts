import { useAuthStore } from "@/store/authStore";

/** What the landing page's "way in" buttons should say: the console needs a
 *  session, so signed-out visitors are asked to log in, not to "try a demo". */
export function useAccessLabel(): string {
  return useAuthStore((s) => (s.status === "authed" ? "Open the console" : "Log in"));
}
