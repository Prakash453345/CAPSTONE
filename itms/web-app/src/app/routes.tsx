import { lazy, Suspense } from "react";
import { createBrowserRouter } from "react-router-dom";
import { RootLayout } from "@/app/RootLayout";
import { AppShell } from "@/components/layout/AppShell";
import { RouteError } from "@/app/RouteError";
import { ConsoleFallback } from "@/app/ConsoleFallback";

const LandingPage = lazy(() =>
  import("@/app/landing/LandingPage").then((m) => ({ default: m.LandingPage })),
);
const DashboardPage = lazy(() =>
  import("@/app/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })),
);
const AnomaliesPage = lazy(() =>
  import("@/app/anomalies/AnomaliesPage").then((m) => ({ default: m.AnomaliesPage })),
);
const TrafficPage = lazy(() =>
  import("@/app/traffic/TrafficPage").then((m) => ({ default: m.TrafficPage })),
);
const EmergencyPage = lazy(() =>
  import("@/app/emergency/EmergencyPage").then((m) => ({ default: m.EmergencyPage })),
);
const AnalyticsPage = lazy(() =>
  import("@/app/analytics/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage })),
);
const SettingsPage = lazy(() =>
  import("@/app/settings/SettingsPage").then((m) => ({ default: m.SettingsPage })),
);

/**
 * "/" is the landing page (branding, product pitch, "Try the live demo");
 * the actual operator workspace — sidebar/topbar shell + every workspace
 * page — lives under "/console" so the two are cleanly separated: launching
 * the app always lands you on the landing page first, never straight into
 * live traffic data. Both sit under RootLayout, which stays mounted across
 * that navigation so the cinematic globe transition it hosts isn't torn
 * down mid-flight.
 */
export const router = createBrowserRouter(
  [
    {
      element: <RootLayout />,
      errorElement: <RouteError />,
      children: [
        {
          index: true,
          element: (
            <Suspense fallback={null}>
              <LandingPage />
            </Suspense>
          ),
        },
        {
          path: "console",
          element: <AppShell />,
          children: [
            {
              index: true,
              element: (
                <Suspense fallback={<ConsoleFallback />}>
                  <DashboardPage />
                </Suspense>
              ),
            },
            {
              path: "anomalies",
              element: (
                <Suspense fallback={<ConsoleFallback />}>
                  <AnomaliesPage />
                </Suspense>
              ),
            },
            {
              path: "traffic",
              element: (
                <Suspense fallback={<ConsoleFallback />}>
                  <TrafficPage />
                </Suspense>
              ),
            },
            {
              path: "emergency",
              element: (
                <Suspense fallback={<ConsoleFallback />}>
                  <EmergencyPage />
                </Suspense>
              ),
            },
            {
              path: "analytics",
              element: (
                <Suspense fallback={<ConsoleFallback />}>
                  <AnalyticsPage />
                </Suspense>
              ),
            },
            {
              path: "settings",
              element: (
                <Suspense fallback={<ConsoleFallback />}>
                  <SettingsPage />
                </Suspense>
              ),
            },
            { path: "*", element: <RouteError /> },
          ],
        },
        { path: "*", element: <RouteError /> },
      ],
    },
  ],
  {
    future: {
      v7_relativeSplatPath: true,
    },
  },
);
