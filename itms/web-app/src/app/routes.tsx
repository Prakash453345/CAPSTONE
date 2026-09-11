import { createBrowserRouter } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { RouteError } from "@/app/RouteError";
import { DashboardPage } from "@/app/dashboard/DashboardPage";
import { AnomaliesPage } from "@/app/anomalies/AnomaliesPage";
import { TrafficPage } from "@/app/traffic/TrafficPage";
import { EmergencyPage } from "@/app/emergency/EmergencyPage";
import { AnalyticsPage } from "@/app/analytics/AnalyticsPage";
import { SettingsPage } from "@/app/settings/SettingsPage";

export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <AppShell />,
      errorElement: <RouteError />,
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
  ],
  {
    future: {
      v7_relativeSplatPath: true,
    },
  },
);
