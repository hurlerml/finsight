import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ChevronRight, Landmark, Settings2, Tags } from "lucide-react";

import { Card } from "@/components/ui";

const settings = [
  {
    to: "/accounts",
    titleKey: "profile.accountsTitle",
    icon: Landmark,
  },
  {
    to: "/categories",
    titleKey: "profile.categoriesTitle",
    icon: Tags,
  },
  {
    to: "/profile/data",
    titleKey: "profile.dataTitle",
    icon: Settings2,
  },
] as const;

export function ProfilePage() {
  const { t } = useTranslation();

  return (
    <section className="w-full space-y-5">
      <div className="px-1"><h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">{t("profile.title")}</h2></div>

      <Card className="space-y-1 p-2">
        {settings.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.to}
              to={item.to}
              className="group flex items-center gap-3 rounded-[1.25rem] px-3 py-3.5 outline-none transition hover:bg-card/55 focus-visible:ring-2 focus-visible:ring-ring/50 sm:px-4"
            >
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-muted/55 text-foreground">
                <Icon className="h-5 w-5" aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-foreground sm:text-base">
                  {t(item.titleKey)}
                </span>
              </span>
              <ChevronRight
                className="h-4 w-4 shrink-0 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-foreground"
                aria-hidden
              />
            </Link>
          );
        })}
      </Card>
    </section>
  );
}
