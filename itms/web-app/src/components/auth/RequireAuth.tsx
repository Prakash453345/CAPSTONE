import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";

/**
 * Gate for everything under /console. Signed-out visitors are sent to /login
 * with the page they wanted in `?next=`, so signing in lands them back there.
 * While the first session check is still on the wire the gate shows a spinner
 * rather than flashing the sign-in page at someone who is already signed in.
 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const status = useAuthStore((s) => s.status);
  const { pathname, search, hash } = useLocation();

  if (status === "checking") {
    return (
      <div className="grid h-full place-items-center bg-background" role="status" aria-label="Checking your session">
        <div className="size-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }
  if (status === "anon") {
    const next = encodeURIComponent(pathname + search + hash);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <>{children}</>;
}
