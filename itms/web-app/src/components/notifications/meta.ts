import { AlertCircle, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import type { NotificationTone } from "@/types";

/** Shared tone -> icon/class mapping for the toaster and the bell dropdown,
 *  matching the `border-status-X/30` + `bg-status-X-muted` convention used
 *  elsewhere (e.g. `RouteError`, `Badge`). */
export const TONE_META: Record<
  NotificationTone,
  { icon: typeof Info; border: string; bg: string; text: string }
> = {
  critical: {
    icon: AlertTriangle,
    border: "border-status-critical/30",
    bg: "bg-status-critical-muted",
    text: "text-status-critical",
  },
  warn: {
    icon: AlertCircle,
    border: "border-status-warn/30",
    bg: "bg-status-warn-muted",
    text: "text-status-warn",
  },
  info: {
    icon: Info,
    border: "border-status-info/30",
    bg: "bg-status-info-muted",
    text: "text-status-info",
  },
  ok: {
    icon: CheckCircle2,
    border: "border-status-ok/30",
    bg: "bg-status-ok-muted",
    text: "text-status-ok",
  },
};
