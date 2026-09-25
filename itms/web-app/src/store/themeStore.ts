import { create } from "zustand";

/**
 * Light / dark appearance. `system` follows the OS (like Google Maps and
 * Apple Maps do); the operator can pin either one. The pre-paint script in
 * index.html applies the same rule before React mounts, so the first frame is
 * already the right theme.
 */
export type ThemeMode = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "traffix.theme";
const media =
  typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;

function readMode(): ThemeMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "light" || v === "dark" || v === "system") return v;
  } catch {
    // storage blocked: fall through to the system default
  }
  return "system";
}

function resolve(mode: ThemeMode): ResolvedTheme {
  if (mode !== "system") return mode;
  return media?.matches ? "dark" : "light";
}

function apply(theme: ResolvedTheme, animate: boolean) {
  const root = document.documentElement;
  if (animate) {
    root.classList.add("theme-switching");
    window.setTimeout(() => root.classList.remove("theme-switching"), 320);
  }
  root.classList.toggle("dark", theme === "dark");
  root.style.colorScheme = theme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "dark" ? "#202124" : "#ffffff");
}

interface ThemeState {
  mode: ThemeMode;
  resolved: ResolvedTheme;
  setMode: (mode: ThemeMode) => void;
}

const initialMode = readMode();

export const useThemeStore = create<ThemeState>((set) => ({
  mode: initialMode,
  resolved: resolve(initialMode),
  setMode: (mode) => {
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // not persisted; still applies for this visit
    }
    const resolved = resolve(mode);
    apply(resolved, true);
    set({ mode, resolved });
  },
}));

apply(useThemeStore.getState().resolved, false);

media?.addEventListener("change", () => {
  const { mode } = useThemeStore.getState();
  if (mode !== "system") return;
  const resolved = resolve(mode);
  apply(resolved, true);
  useThemeStore.setState({ resolved });
});
