import { lazy, Suspense } from "react";
import { createBrowserRouter } from "react-router-dom";
import { RootLayout } from "@/app/RootLayout";
import { AppShell } from "@/components/layout/AppShell";
import { RequireAuth } from "@/components/auth/RequireAuth";
import { RouteError } from "@/app/RouteError";
import { ConsoleFallback } from "@/app/ConsoleFallback";

const LandingPage = lazy(() =>
  import("@/app/landing/LandingPage").then((m) => ({ default: m.LandingPage })),
);
const LoginPage = lazy(() =>
  import("@/app/login/LoginPage").then((m) => ({ default: m.LoginPage })),
);
const DrivePage = lazy(() =>
  import("@/app/drive/DrivePage").then((m) => ({ default: m.DrivePage })),
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
const MapPage = lazy(() =>
  import("@/app/map/MapPage").then((m) => ({ default: m.MapPage })),
);
const SettingsPage = lazy(() =>
  import("@/app/settings/SettingsPage").then((m) => ({ default: m.SettingsPage })),
);

/**
 * "/" is the landing page (branding, product pitch, "Log in");
 * the actual operator workspace — sidebar/topbar shell + every workspace
 * page — lives under "/console" so the two are cleanly separated: launching
 * the app always lands you on the landing page first, never straight into
 * live traffic data. "/login" sits between them, and "/console" is gated by
 * RequireAuth, which sends signed-out visitors there. "/drive" is the same
 * data for the crew driving an emergency vehicle, gated the same way. All sit under
 * RootLayout, which stays mounted across that navigation so the cinematic
 * globe transition it hosts isn't torn down mid-flight.
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
          path: "login",
          element: (
            <Suspense fallback={null}>
              <LoginPage />
            </Suspense>
          ),
        },
        {
          path: "drive",
          element: (
            <RequireAuth>
              <Suspense fallback={<ConsoleFallback />}>
                <DrivePage />
              </Suspense>
            </RequireAuth>
          ),
        },
        {
          path: "console",
          element: (
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          ),
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
              path: "map",
              element: (
                <Suspense fallback={<ConsoleFallback />}>
                  <MapPage />
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
