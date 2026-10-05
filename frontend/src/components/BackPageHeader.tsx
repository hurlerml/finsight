import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

export function BackPageHeader({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  const { t } = useTranslation();

  return (
    <div className="flex min-h-10 items-center gap-2 px-1">
      <Link
        to="/profile"
        className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-muted-foreground outline-none transition hover:bg-card/45 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50"
        aria-label={t("common.back")}
      >
        <ArrowLeft className="h-5 w-5" aria-hidden />
      </Link>
      <h2 className="min-w-0 flex-1 truncate text-2xl font-semibold tracking-tight sm:text-3xl">
        {title}
      </h2>
      {children}
    </div>
  );
}
