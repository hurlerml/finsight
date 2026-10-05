const THEME_KEY = "finsight.theme";
export const THEME_CHANGE_EVENT = "finsight:theme-change";

export type ThemeMode = "light" | "dark";

export function getStoredTheme(): ThemeMode {
  const raw = localStorage.getItem(THEME_KEY);
  if (raw === "dark" || raw === "light") return raw;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(mode: ThemeMode) {
  const root = document.documentElement;
  const changed = root.classList.contains("dark") !== (mode === "dark");
  root.classList.toggle("dark", mode === "dark");
  root.style.colorScheme = mode;
  localStorage.setItem(THEME_KEY, mode);
  if (changed) {
    window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: { mode } }));
  }
}

export function toggleTheme(): ThemeMode {
  const next: ThemeMode = getStoredTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  return next;
}
