/**
 * Presentation-only demo mode.
 *
 * This intentionally lives in the frontend: it changes what is rendered in
 * the browser, but it is not a security boundary. The API and encrypted
 * storage continue to contain the real values.
 */
export const DEMO_MODE_STORAGE_KEY = "finsight.demo-mode";
export const DEMO_MODE_CHANGE_EVENT = "finsight:demo-mode-change";

// One stable factor keeps totals, charts and transaction amounts internally
// consistent while making the real amounts impossible to read at a glance.
export const DEMO_MONEY_FACTOR = 0.67;

// Keep a same-tab fallback as well. Some browsers block localStorage in
// private contexts; the toggle must still immediately mask values there.
let runtimeDemoMode: boolean | null = null;

export function isDemoModeEnabled(): boolean {
  if (runtimeDemoMode !== null) return runtimeDemoMode;
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(DEMO_MODE_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function setDemoModeEnabled(enabled: boolean): void {
  runtimeDemoMode = enabled;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(DEMO_MODE_STORAGE_KEY, String(enabled));
  } catch {
    // Private browsing or a disabled storage backend should not break the UI.
  }
  window.dispatchEvent(new CustomEvent(DEMO_MODE_CHANGE_EVENT, { detail: enabled }));
}

export function scaleDemoMoney(value: number | string | null | undefined): number | null {
  if (value == null || value === "") return null;
  const numeric = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(numeric)) return null;
  const scaled = numeric * DEMO_MONEY_FACTOR;
  // Avoid displaying a confusing negative zero after scaling small values.
  return Math.abs(scaled) < 0.005 ? 0 : scaled;
}
