import { createBrowserRouter } from "react-router-dom";
import { RootLayout } from "@/app/RootLayout";
import { AppShell } from "@/components/layout/AppShell";
import { RouteError } from "@/app/RouteError";
import { LandingPage } from "@/app/landing/LandingPage";
import { DashboardPage } from "@/app/dashboard/DashboardPage";
import { AnomaliesPage } from "@/app/anomalies/AnomaliesPage";
import { TrafficPage } from "@/app/traffic/TrafficPage";
import { EmergencyPage } from "@/app/emergency/EmergencyPage";
import { AnalyticsPage } from "@/app/analytics/AnalyticsPage";
import { SettingsPage } from "@/app/settings/SettingsPage";

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
        { index: true, element: <LandingPage /> },
        {
          path: "console",
          element: <AppShell />,
          children: [
            { index: true, element: <DashboardPage /> },
            { path: "anomalies", element: <AnomaliesPage /> },
            { path: "traffic", element: <TrafficPage /> },
            { path: "emergency", element: <EmergencyPage /> },
            { path: "analytics", element: <AnalyticsPage /> },
            { path: "settings", element: <SettingsPage /> },
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
