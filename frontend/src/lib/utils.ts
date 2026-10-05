import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

import { localeForLanguage } from "@/i18n";
import { isDemoModeEnabled, scaleDemoMoney } from "@/lib/demo";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatMoney(
  value: number | string,
  currency = "EUR",
  language?: string
) {
  const raw = typeof value === "string" ? Number(value) : value;
  const n = isDemoModeEnabled() ? (scaleDemoMoney(raw) ?? 0) : raw;
  return new Intl.NumberFormat(localeForLanguage(language), {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(n);
}

export function monthRange(year: number, month: number) {
  const from = new Date(Date.UTC(year, month - 1, 1));
  const to = new Date(Date.UTC(year, month, 0));
  return {
    from: from.toISOString().slice(0, 10),
    to: to.toISOString().slice(0, 10),
  };
}

export function yearRange(year: number) {
  return { from: `${year}-01-01`, to: `${year}-12-31` };
}

/** ISO week range (Mon–Sun) for the week containing `anchor`. */
export function weekRange(anchor: Date = new Date()) {
  const d = new Date(Date.UTC(anchor.getFullYear(), anchor.getMonth(), anchor.getDate()));
  const day = d.getUTCDay() || 7;
  if (day !== 1) d.setUTCDate(d.getUTCDate() - (day - 1));
  const from = d.toISOString().slice(0, 10);
  d.setUTCDate(d.getUTCDate() + 6);
  const to = d.toISOString().slice(0, 10);
  return { from, to };
}

export function shiftPeriod(
  grain: "week" | "month" | "year",
  anchor: Date,
  delta: number
): Date {
  const d = new Date(anchor);
  if (grain === "week") d.setDate(d.getDate() + delta * 7);
  else if (grain === "month") d.setMonth(d.getMonth() + delta);
  else d.setFullYear(d.getFullYear() + delta);
  return d;
}

export function periodRange(grain: "week" | "month" | "year", anchor: Date) {
  if (grain === "week") return weekRange(anchor);
  if (grain === "month") return monthRange(anchor.getFullYear(), anchor.getMonth() + 1);
  return yearRange(anchor.getFullYear());
}
