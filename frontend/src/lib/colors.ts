/** Read theme colors from CSS variables — never hardcode hues in components. */

import de from "../i18n/locales/de.json";
import en from "../i18n/locales/en.json";

function readVar(name: string): string {
  if (typeof window === "undefined") return "";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** `hsl(var(--token))` for inline SVG / canvas / recharts fills */
export function themeHsl(token: string): string {
  const name = token.startsWith("--") ? token : `--${token}`;
  const value = readVar(name);
  return value ? `hsl(${value})` : `hsl(var(${name}))`;
}

const EXPENSE_CHART = [
  "chart-expense-1",
  "chart-expense-2",
  "chart-expense-3",
  "chart-expense-4",
  "chart-expense-5",
  "chart-expense-6",
  "chart-expense-7",
  "chart-expense-8",
] as const;

const INCOME_CHART = [
  "chart-income-1",
  "chart-income-2",
  "chart-income-3",
  "chart-income-4",
  "chart-income-5",
] as const;

/** Series key like `e:Groceries` / `i:Salary` → theme color */
export function seriesColor(key: string, index: number): string {
  const isIncome = key.startsWith("i:");
  const label = key.slice(2);
  const semanticSlug = categorySlugForLabel(label);
  if (semanticSlug) return categoryColor(semanticSlug);
  const palette = isIncome ? INCOME_CHART : EXPENSE_CHART;
  return themeHsl(palette[index % palette.length]);
}

// Match saved category names in either supported language, independent of the UI language.
const CATEGORY_LABELS: Record<string, string[]> = Object.fromEntries(
  Object.entries(en.categoryAliases).map(([slug, labels]) => [
    slug,
    [...labels, ...(de.categoryAliases[slug as keyof typeof de.categoryAliases] || [])],
  ])
);

export function categorySlugForLabel(label: string): string | null {
  const normalized = label.trim().toLocaleLowerCase();
  if (!normalized) return null;
  for (const [slug, labels] of Object.entries(CATEGORY_LABELS)) {
    if (labels.some((candidate) => normalized === candidate || normalized.startsWith(`${candidate} `))) {
      return slug;
    }
  }
  return null;
}

const CAT_TOKENS: Record<string, string> = {
  housing: "cat-housing",
  groceries: "cat-groceries",
  mobility: "cat-mobility",
  subscriptions: "cat-subscriptions",
  dining: "cat-dining",
  shopping: "cat-shopping",
  health: "cat-health",
  leisure: "cat-leisure",
  travel: "cat-travel",
  family: "cat-family",
  education: "cat-education",
  savings: "cat-savings",
  finance: "cat-finance",
  income: "cat-income",
  uncategorized: "cat-fallback",
  other: "cat-other",
  transfer: "cat-transfer",
  salary: "cat-salary",
};

export function categoryColor(slug: string, colorKey?: string, fallbackColor?: string): string {
  const token = CAT_TOKENS[colorKey || slug];
  return token ? themeHsl(token) : fallbackColor || themeHsl("cat-fallback");
}
