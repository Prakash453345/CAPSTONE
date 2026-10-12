import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { MotionConfig } from "framer-motion";
import { router } from "@/app/routes";
import "@/index.css";
import "@/product.css";
import "@/store/themeStore";

// Note: React.StrictMode is intentionally omitted. Its dev-only double-invoke of
// effects races the imperative MapLibre source/layer lifecycle (add → remove →
// add within one commit), which manifests as missing overlays and churned WebGL
// contexts. Revisit in Phase 10 with a StrictMode-safe map wrapper.

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("TRAFFIX: #root element not found");

createRoot(rootEl).render(
  <MotionConfig reducedMotion="user"><RouterProvider router={router} future={{ v7_startTransition: true }} /></MotionConfig>,
);
