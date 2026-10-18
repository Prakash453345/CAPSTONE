import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { homeFor, type Role } from "@/services/auth/roles";

/**
 * Gate for the signed-in areas (/console, /crew). `roles` limits which accounts
 * may open one; others are sent to their own home. Signed-out visitors are sent to /login
 * with the page they wanted in `?next=`, so signing in lands them back there.
 * While the first session check is still on the wire the gate shows a spinner
 * rather than flashing the sign-in page at someone who is already signed in.
 */
export function RequireAuth({ children, roles }: { children: ReactNode; roles?: readonly Role[] }) {
  const status = useAuthStore((s) => s.status);
  const role = useAuthStore((s) => s.user?.role);
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
  // Signed in, but this account is not for this page (a crew account opening
  // the console): send it to its own home rather than a dead end.
  if (roles && role && !roles.includes(role)) return <Navigate to={homeFor(role)} replace />;
  return <>{children}</>;
}
