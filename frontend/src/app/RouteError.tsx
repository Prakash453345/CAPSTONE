import { useRouteError, isRouteErrorResponse, useNavigate } from "react-router-dom";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Router-level error / 404 boundary. */
export function RouteError() {
  const error = useRouteError();
  const navigate = useNavigate();

  const { heading, detail } = isRouteErrorResponse(error)
    ? {
        heading: error.status === 404 ? "Screen not found" : `Error ${error.status}`,
        detail:
          error.status === 404
            ? "That workspace doesn't exist. It may have moved or not been built yet."
            : error.statusText,
      }
    : {
        heading: "Something went wrong",
        detail:
          error instanceof Error ? error.message : "An unexpected error occurred.",
      };

  return (
    <div className="grid h-full place-items-center bg-background p-6 text-foreground">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-4 grid size-12 place-items-center rounded-xl border border-status-critical/30 bg-status-critical-muted">
          <TriangleAlert className="size-6 text-status-critical" />
        </div>
        <h2 className="text-base font-semibold tracking-tight">{heading}</h2>
        <p className="mx-auto mt-1.5 text-sm text-muted-foreground">{detail}</p>
        <div className="mt-4 flex justify-center gap-2">
          <Button variant="default" onClick={() => navigate("/console")}>
            Back to Command Center
          </Button>
          <Button variant="subtle" onClick={() => navigate(0)}>
            Reload
          </Button>
        </div>
      </div>
    </div>
  );
}
