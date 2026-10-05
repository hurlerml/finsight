import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Landmark, MessageCircle } from "lucide-react";
import { Link, useOutletContext } from "react-router-dom";

import { useAppSetup } from "@/auth/AppSetupContext";
import { AgentPanel } from "@/components/AgentPanel";
import type { LayoutOutletContext } from "@/components/Layout";
import { Card } from "@/components/ui";

export function ChatPage() {
  const { t } = useTranslation();
  const { hasAccounts } = useAppSetup();
  const { assistant, setChatPresence, demoMode } = useOutletContext<LayoutOutletContext>();

  useEffect(() => () => setChatPresence("idle"), [setChatPresence]);

  if (!hasAccounts) {
    return (
      <div className="grid h-full min-h-[24rem] place-items-center px-1">
        <Card className="w-full max-w-lg px-6 py-10 text-center">
          <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-muted/55 text-muted-foreground">
            <MessageCircle className="h-6 w-6" aria-hidden />
          </span>
          <h2 className="mt-4 text-xl font-semibold">{t("agent.noAccountsTitle")}</h2>
          <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
            {t("agent.noAccountsHint")}
          </p>
          <Link
            to="/accounts"
            className="mt-5 inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition hover:-translate-y-px hover:shadow-md"
          >
            <Landmark className="h-4 w-4" aria-hidden />
            {t("agent.addAccount")}
          </Link>
        </Card>
      </div>
    );
  }

  return <AgentPanel status={assistant} onPresenceChange={setChatPresence} demoMode={demoMode} />;
}
