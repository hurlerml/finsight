export type BankBrand = {
  id: string;
  label: string;
  asset?: string;
  fallback: string;
  patterns: RegExp[];
};

// Keep more specific brands before their parent groups (for example comdirect
// before Commerzbank). Assets are added only after their provenance has been
// documented in public/brands/README.md and THIRD_PARTY_NOTICES.md.
export const BANK_BRANDS: BankBrand[] = [
  { id: "comdirect", label: "Comdirect", fallback: "cd", patterns: [/\bcomdirect\b/i] },
  { id: "consorsbank", label: "Consorsbank", fallback: "CB", patterns: [/\bconsorsbank\b/i, /\bconsors\b/i] },
  { id: "deutsche-bank", label: "Deutsche Bank", asset: "/brands/deutsche-bank.svg", fallback: "DB", patterns: [/\bdeutsche bank\b/i] },
  { id: "commerzbank", label: "Commerzbank", asset: "/brands/commerzbank.svg", fallback: "CB", patterns: [/\bcommerzbank\b/i] },
  { id: "postbank", label: "Postbank", fallback: "PB", patterns: [/\bpostbank\b/i] },
  { id: "dkb", label: "DKB", fallback: "DKB", patterns: [/\bdkb\b/i, /deutsche kreditbank/i] },
  { id: "ing", label: "ING", fallback: "ING", patterns: [/\bing(?:-diba)?\b/i] },
  { id: "n26", label: "N26", asset: "/brands/n26.svg", fallback: "N26", patterns: [/\bn26\b/i] },
  { id: "santander", label: "Santander", fallback: "S", patterns: [/\bsantander\b/i] },
  { id: "targobank", label: "Targobank", fallback: "T", patterns: [/\btargobank\b/i] },
  { id: "gls", label: "GLS Bank", fallback: "GLS", patterns: [/\bgls bank\b/i, /gemeinschaftsbank/i] },
  { id: "tomorrow", label: "Tomorrow", fallback: "T", patterns: [/\btomorrow\b/i] },
  { id: "sparkasse", label: "Sparkasse", asset: "/brands/sparkasse.svg", fallback: "S", patterns: [/sparkasse/i] },
  { id: "volksbank", label: "Volksbanken Raiffeisenbanken", asset: "/brands/volksbank.svg", fallback: "VR", patterns: [/volksbank/i, /raiffeisenbank/i, /vr[- ]bank/i] },
];

export function resolveBankBrand(input: {
  brand?: string | null;
  name?: string | null;
  bic?: string | null;
}): BankBrand | null {
  const explicit = input.brand?.trim().toLowerCase();
  if (explicit) {
    const exact = BANK_BRANDS.find((brand) => brand.id === explicit);
    if (exact) return exact;
  }
  const haystack = `${input.name || ""} ${input.bic || ""}`.trim();
  if (!haystack) return null;
  return BANK_BRANDS.find((brand) => brand.patterns.some((pattern) => pattern.test(haystack))) || null;
}

export function bankInitials(name?: string | null): string {
  const words = (name || "Bank")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (words.length === 0) return "B";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[1][0]}`.toUpperCase();
}
