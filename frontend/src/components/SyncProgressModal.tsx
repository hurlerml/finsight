import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type SyncProgress } from "@/api/client";
import { ACCOUNT_SETUP_LONG_RUNNING_MS } from "@/lib/accountSetup";
import { Button, Card } from "@/components/ui";

export function SyncProgressModal() {
  const { t } = useTranslation();
  const [progress, setProgress] = useState<SyncProgress | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [timedOut, setTimedOut] = useState(false);
  const awaitingSince = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = () => {
      api
        .syncProgress()
        .then((st) => {
          if (cancelled) return;
          setProgress(st);
          if (st.awaiting_user_action) {
            if (awaitingSince.current == null) {
              awaitingSince.current = Date.now();
            } else if (
              Date.now() - awaitingSince.current > ACCOUNT_SETUP_LONG_RUNNING_MS
            ) {
              setTimedOut(true);
            }
          } else {
            awaitingSince.current = null;
            setTimedOut(false);
            setDismissed(false);
          }
          const active =
            st.awaiting_user_action || st.phase === "running" || st.phase === "awaiting_user_action";
          timer = window.setTimeout(tick, active ? 1500 : 8000);
        })
        .catch(() => {
          if (cancelled) return;
          timer = window.setTimeout(tick, 8000);
        });
    };

    tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  if (!progress?.awaiting_user_action || dismissed) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/70 p-4 backdrop-blur-sm"
      onClick={() => setDismissed(true)}
    >
      <Card className="max-w-md space-y-4" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-2xl font-semibold tracking-tight">
          {timedOut ? t("syncModal.timeoutTitle") : t("syncModal.title")}
        </h2>
        <p className="text-sm text-muted-foreground">
          {timedOut ? t("syncModal.timeoutBody") : t("syncModal.body")}
        </p>
        {progress.message && !timedOut && (
          <p className="rounded-xl bg-muted px-3 py-2 text-sm text-foreground">{progress.message}</p>
        )}
        <p className="text-xs text-muted-foreground">
          {timedOut ? t("syncModal.timeoutHint") : t("syncModal.waiting")}
        </p>
        <Button
          variant="outline"
          onClick={() => setDismissed(true)}
        >
          {timedOut ? t("syncModal.close") : t("syncModal.waiting")}
        </Button>
      </Card>
    </div>
  );
}
