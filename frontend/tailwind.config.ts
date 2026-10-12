import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

/**
 * TRAFFIX design tokens.
 * Google Maps-style Material palette, light and dark. Every colour is an HSL triple exposed as a
 * CSS variable in src/index.css, so components reference semantic roles
 * (surface, border, primary, status-*) and never raw hex.
 */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
    },
    extend: {
      fontFamily: {
        sans: [
          "Google Sans Flex",
          "Google Sans",
          "Roboto",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "Google Sans Code",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "monospace",
        ],
      },
      colors: {
        // core surfaces
        background: "hsl(var(--background))",
        surface: {
          DEFAULT: "hsl(var(--surface))",
          raised: "hsl(var(--surface-raised))",
          sunken: "hsl(var(--surface-sunken))",
        },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        foreground: "hsl(var(--foreground))",
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        // interactive accent
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
          muted: "hsl(var(--primary-muted))",
        },
        // semantic status
        status: {
          ok: "hsl(var(--status-ok))",
          "ok-muted": "hsl(var(--status-ok-muted))",
          warn: "hsl(var(--status-warn))",
          "warn-muted": "hsl(var(--status-warn-muted))",
          critical: "hsl(var(--status-critical))",
          "critical-muted": "hsl(var(--status-critical-muted))",
          info: "hsl(var(--status-info))",
          "info-muted": "hsl(var(--status-info-muted))",
        },
        // shadcn-compatible aliases
        card: {
          DEFAULT: "hsl(var(--surface))",
          foreground: "hsl(var(--foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--surface-raised))",
          foreground: "hsl(var(--foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--surface-raised))",
          foreground: "hsl(var(--foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--status-critical))",
          foreground: "hsl(var(--foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--surface-raised))",
          foreground: "hsl(var(--foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 3px)",
        sm: "calc(var(--radius) - 6px)",
      },
      boxShadow: {
        panel: "var(--elevation-1)",
        "panel-lg": "var(--elevation-3)",
        "elevation-1": "var(--elevation-1)",
        "elevation-2": "var(--elevation-2)",
        "elevation-3": "var(--elevation-3)",
        glow: "0 0 0 1px hsl(var(--primary) / 0.35), 0 0 24px -4px hsl(var(--primary) / 0.35)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "ping-ring": {
          "0%": { transform: "scale(0.9)", opacity: "0.7" },
          "80%, 100%": { transform: "scale(2.2)", opacity: "0" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "sheet-in": {
          from: { opacity: "0", transform: "translateY(8px) scale(0.98)" },
          to: { opacity: "1", transform: "none" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "ping-ring": "ping-ring 1.8s cubic-bezier(0, 0, 0.2, 1) infinite",
        "fade-in": "fade-in 0.2s ease-out",
        // Material 3 "emphasized decelerate": how Google Maps' panels land.
        "sheet-in": "sheet-in 0.4s cubic-bezier(0.05, 0.7, 0.1, 1)",
      },
    },
  },
  plugins: [animate],
} satisfies Config;
