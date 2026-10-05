import { useTranslation } from "react-i18next";
import { Globe2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function LanguageSwitch({ className }: { className?: string }) {
  const { i18n, t } = useTranslation();
  const value = i18n.language.startsWith("en") ? "en" : "de";

  return (
    <button
      type="button"
      className={cn("inline-flex h-10 items-center gap-1.5 rounded-full border border-white/40 bg-card/30 px-3 text-xs font-semibold uppercase text-muted-foreground backdrop-blur-xl transition hover:text-foreground active:scale-[0.97]", className)}
      aria-label={t("language.label")}
      title={t("language.label")}
      onClick={() => void i18n.changeLanguage(value === "de" ? "en" : "de")}
    >
      <Globe2 className="h-4 w-4" aria-hidden />
      {value}
    </button>
  );
}
