import { useEffect } from "react";
import { useRouteError, isRouteErrorResponse, useLocation, useNavigate } from "react-router-dom";
import { MapPinOff, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Router-level error boundary, and the 404 page: the router's catch-all
 *  routes render it as a plain element, where there is no error to read. */
export function RouteError() {
  const error = useRouteError();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const notFound = error === undefined || (isRouteErrorResponse(error) && error.status === 404);
  const inConsole = pathname.startsWith("/console");
  const home = inConsole
    ? { label: "Back to overview", to: "/console" }
    : { label: "Go to the home page", to: "/" };

  useEffect(() => {
    if (notFound) document.title = "Page not found · Traffix";
  }, [notFound]);

  const { heading, detail } = notFound
    ? {
        heading: "Page not found",
        detail: `There\u2019s nothing at this address. Check the link, or ${inConsole ? "go back to the overview" : "start from the home page"}.`,
      }
    : isRouteErrorResponse(error)
    ? { heading: `Error ${error.status}`, detail: error.statusText }
    : {
        heading: "Something went wrong",
        detail:
          error instanceof Error ? error.message : "An unexpected error occurred.",
      };

  return (
    <div className="grid h-full place-items-center bg-background p-6 text-foreground">
      <div className="max-w-md text-center">
        {notFound ? (
          <div className="mx-auto mb-4 grid size-12 place-items-center rounded-xl bg-muted">
            <MapPinOff className="size-6 text-muted-foreground" />
          </div>
        ) : (
          <div className="mx-auto mb-4 grid size-12 place-items-center rounded-xl border border-status-critical/30 bg-status-critical-muted">
            <TriangleAlert className="size-6 text-status-critical" />
          </div>
        )}
        <h2 className="text-base font-semibold tracking-tight">{heading}</h2>
        <p className="mx-auto mt-1.5 text-sm text-muted-foreground">{detail}</p>
        <div className="mt-4 flex justify-center gap-2">
          <Button variant="default" onClick={() => navigate(home.to)}>
            {home.label}
          </Button>
          {/* reloading a missing page only shows it again */}
          {!notFound && (
            <Button variant="subtle" onClick={() => navigate(0)}>
              Reload
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
