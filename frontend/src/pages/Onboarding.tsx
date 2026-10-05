import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Globe2,
  Landmark,
  Loader2,
  Moon,
  Sun,
  Tags,
} from "lucide-react";

import {
  ACCOUNT_SETUP_LONG_RUNNING_MS,
  AccountSetupFailedError,
  connectionHasActiveSync,
  connectionSetupFailed,
  connectionSyncStatusFor,
  isConnectionInitialSyncPending,
  waitForConnectionInitialSync,
} from "@/lib/accountSetup";
import { api, type OllamaModels } from "@/api/client";
import { useAppSetup } from "@/auth/AppSetupContext";
import { AssistantAvatar } from "@/components/AssistantAvatar";
import { ConnectionForm } from "@/components/ConnectionForm";
import { LanguageSwitch } from "@/components/LanguageSwitch";
import { Button, Card, Input, Select } from "@/components/ui";
import { applyTheme, getStoredTheme, toggleTheme, type ThemeMode } from "@/lib/theme";

function formatSetupError(
  err: unknown,
  translate: (key: string) => string,
) {
  if (err instanceof Error) {
    if (err.message === "account_setup_failed") {
      return translate("onboarding.accountSetupFailed");
    }
    return err.message;
  }
  return translate("common.error");
}

const STEP_COUNT = 3;

export function OnboardingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const {
    completeOnboarding,
    refreshSetup,
    connections,
    connectionSyncStatuses,
  } = useAppSetup();
  const [step, setStep] = useState(0);
  const [ollama, setOllama] = useState<OllamaModels | null>(null);
  const [chatModel, setChatModel] = useState("");
  const [customModel, setCustomModel] = useState(false);
  const [customModelName, setCustomModelName] = useState("");
  const [modelSetupRequested, setModelSetupRequested] = useState(false);
  const [webSearch, setWebSearch] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accountCreated, setAccountCreated] = useState(false);
  const [accountSyncQueued, setAccountSyncQueued] = useState(false);
  const [connectionId, setConnectionId] = useState<number | null>(null);
  const [initialSyncDone, setInitialSyncDone] = useState(false);
  const [setupFailed, setSetupFailed] = useState(false);
  const [syncTakingLonger, setSyncTakingLonger] = useState(false);
  const [syncStartedAt, setSyncStartedAt] = useState<number | null>(null);
  const [theme, setTheme] = useState<ThemeMode>(() => getStoredTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([api.ollamaModels(), api.llmPreferences()])
      .then(([modelResult, preferenceResult]) => {
        if (cancelled) return;
        if (modelResult.status === "fulfilled") {
          setOllama(modelResult.value);
          setChatModel(modelResult.value.active);
          setModelSetupRequested(
            modelResult.value.auto_install.phase !== "pending" &&
              modelResult.value.auto_install.phase !== "disabled",
          );
        }
        if (preferenceResult.status === "fulfilled") {
          setWebSearch(
            preferenceResult.value.categorization_web_search_enabled,
          );
        }
      })
      .finally(() => {
        if (!cancelled) setSettingsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const phase = ollama?.auto_install.phase;
    if (
      !modelSetupRequested ||
      (phase !== "pending" && phase !== "waiting" && phase !== "checking" && phase !== "downloading")
    ) {
      return;
    }
    const timer = window.setTimeout(() => {
      void api.ollamaModels().then(setOllama).catch(() => undefined);
    }, phase === "downloading" ? 1500 : 5000);
    return () => window.clearTimeout(timer);
  }, [modelSetupRequested, ollama?.auto_install.phase, ollama?.auto_install.completed]);

  const modelOptions = useMemo(() => {
    const options = [...(ollama?.models || [])];
    if (ollama?.active && !options.includes(ollama.active)) {
      options.unshift(ollama.active);
    }
    return options;
  }, [ollama]);

  const ensureInitialSyncComplete = async () => {
    if (
      !accountSyncQueued ||
      connectionId == null ||
      initialSyncDone ||
      syncTakingLonger
    ) {
      return false;
    }
    const result = await waitForConnectionInitialSync(connectionId, refreshSetup);
    if (result === "complete") {
      setInitialSyncDone(true);
      return true;
    }
    setSyncTakingLonger(true);
    return false;
  };

  const finish = async (destination: string) => {
    setBusy(true);
    setError(null);
    try {
      await ensureInitialSyncComplete();
      await completeOnboarding();
      navigate(destination, { replace: true });
    } catch (err) {
      if (err instanceof AccountSetupFailedError) {
        setSetupFailed(true);
      }
      setError(formatSetupError(err, t));
    } finally {
      setBusy(false);
    }
  };

  const resetFailedConnection = async () => {
    if (connectionId == null) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const statuses = await api.connectionSyncStatus();
      const currentStatus = connectionSyncStatusFor(statuses, connectionId);
      if (connectionHasActiveSync(currentStatus)) {
        setSetupFailed(false);
        setSyncTakingLonger(true);
        setError(t("onboarding.accountSyncTakingLonger"));
        return;
      }
      await api.deleteConnection(connectionId);
      setAccountCreated(false);
      setAccountSyncQueued(false);
      setConnectionId(null);
      setInitialSyncDone(false);
      setSetupFailed(false);
      setSyncTakingLonger(false);
      setSyncStartedAt(null);
      await refreshSetup();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.error"));
    } finally {
      setBusy(false);
    }
  };

  const continueFromAccountStep = async () => {
    if (accountCreated && accountSyncQueued && !initialSyncDone) {
      setBusy(true);
      setError(null);
      try {
        await ensureInitialSyncComplete();
        setStep(2);
      } catch (err) {
        if (err instanceof AccountSetupFailedError) {
          setSetupFailed(true);
        }
        setError(formatSetupError(err, t));
      } finally {
        setBusy(false);
      }
      return;
    }
    setStep(2);
  };

  const connection = connections.find((item) => item.id === connectionId);
  const connectionSync = connectionId != null
    ? connectionSyncStatusFor(connectionSyncStatuses, connectionId)
    : undefined;
  const setupFailedState = setupFailed || (
    accountCreated &&
    connectionSetupFailed(connection, connectionSync)
  );

  const initialSyncPending =
    accountCreated && accountSyncQueued && !initialSyncDone && !setupFailedState;

  useEffect(() => {
    if (!initialSyncPending || connectionId == null) {
      return;
    }
    let cancelled = false;
    const poll = async () => {
      if (
        syncStartedAt != null &&
        Date.now() - syncStartedAt > ACCOUNT_SETUP_LONG_RUNNING_MS
      ) {
        setSyncTakingLonger(true);
      }
      const [accounts, loadedConnections, syncStatuses, connectionSync] =
        await Promise.all([
          api.accounts(),
          api.connections(),
          api.syncStatus(),
          api.connectionSyncStatus(),
        ]);
      await refreshSetup();
      if (cancelled) {
        return;
      }
      const conn = loadedConnections.find((item) => item.id === connectionId);
      const connSync = connectionSyncStatusFor(connectionSync, connectionId);
      if (!isConnectionInitialSyncPending(
        connectionId,
        accounts,
        loadedConnections,
        syncStatuses,
        connectionSync,
      )) {
        if (connectionSetupFailed(conn, connSync)) {
          setSetupFailed(true);
          setError(
            conn?.last_error ||
              connSync?.latest_job_error ||
              t("onboarding.accountSetupFailed"),
          );
        } else {
          setInitialSyncDone(true);
          setSyncTakingLonger(false);
        }
      }
    };
    const id = window.setInterval(() => {
      poll().catch(() => undefined);
    }, 2500);
    poll().catch(() => undefined);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [initialSyncPending, connectionId, refreshSetup, syncStartedAt, t]);

  const saveAiSettings = async () => {
    setBusy(true);
    setError(null);
    try {
      const selectedModel = (customModel ? customModelName : chatModel).trim();
      if (!selectedModel) {
        throw new Error(t("onboarding.modelRequired"));
      }
      await api.configureInitialOllamaModels(selectedModel);
      setModelSetupRequested(true);
      setOllama(await api.ollamaModels());
      await api.setCategorizationWebSearch(webSearch);
      setStep(1);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.error"));
    } finally {
      setBusy(false);
    }
  };

  const autoInstallPercent = ollama?.auto_install.total
    ? Math.min(100, Math.round(
        (ollama.auto_install.completed / ollama.auto_install.total) * 100,
      ))
    : null;

  const modelStatus = ollama?.auto_install.phase === "downloading"
    ? t("onboarding.modelDownloading", {
        model: ollama.auto_install.model,
        percent: autoInstallPercent ?? 0,
      })
    : ollama?.auto_install.phase === "checking"
      ? t("onboarding.modelChecking")
      : ollama?.auto_install.phase === "waiting"
        ? t("onboarding.modelWaiting")
        : ollama?.auto_install.phase === "error"
          ? t("onboarding.modelInstallFailed")
          : ollama?.reachable
            ? t("onboarding.modelReady")
            : t("onboarding.modelUnavailable");

  return (
    <div className="min-h-dvh px-3 py-3 text-foreground sm:px-5 sm:py-5">
      <div className="mx-auto flex min-h-[calc(100dvh-1.5rem)] max-w-6xl flex-col sm:min-h-[calc(100dvh-2.5rem)]">
        <header className="glass-header flex items-center justify-between gap-3 rounded-[1.35rem] px-3 py-2.5 sm:rounded-[1.6rem] sm:px-4 sm:py-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <AssistantAvatar status={null} className="h-9 w-9" />
            <span className="brand-wordmark truncate text-[1.7rem] font-bold tracking-[-0.025em] text-foreground sm:text-[2rem]">
              {t("layout.brand")}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <LanguageSwitch className="h-9 px-2.5" />
            <Button
              type="button"
              variant="outline"
              className="h-9 w-9 rounded-full p-0"
              onClick={() => setTheme(toggleTheme())}
              aria-label={t("theme.toggle")}
              title={theme === "dark" ? t("theme.light") : t("theme.dark")}
            >
              {theme === "dark" ? (
                <Sun className="h-4 w-4" aria-hidden />
              ) : (
                <Moon className="h-4 w-4" aria-hidden />
              )}
            </Button>
          </div>
        </header>

        <main className="flex flex-1 justify-center py-8 sm:py-12">
          <section className="w-full max-w-2xl">
            <div className="mb-5 px-1">
              <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                {t("onboarding.title")}
              </h1>
            </div>

            <Card
              className="flex w-full flex-col rounded-[1.5rem] p-4 sm:rounded-[1.75rem] sm:p-6"
            >
              <div className="flex items-center gap-2" aria-label={t("onboarding.progress", { current: step + 1, total: STEP_COUNT })}>
          {Array.from({ length: STEP_COUNT }, (_, index) => (
            <span
              key={index}
              className={`h-1.5 flex-1 rounded-full transition-colors ${
                index <= step ? "bg-primary" : "bg-muted"
              }`}
            />
          ))}
              </div>

              {modelSetupRequested && ollama?.auto_install.phase !== "ready" && ollama?.auto_install.phase !== "disabled" && (
                <div
                  className={`mt-4 flex items-center gap-2 rounded-xl px-3 py-2 text-xs ${
                    ollama?.auto_install.phase === "error"
                      ? "bg-danger/10 text-danger"
                      : "bg-primary/10 text-muted-foreground"
                  }`}
                  role="status"
                  aria-live="polite"
                >
                  {ollama?.auto_install.phase !== "error" && (
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" aria-hidden />
                  )}
                  <span>{modelStatus}</span>
                </div>
              )}

              <div className="flex-1 py-5">
          {step === 0 && (
            <div className="space-y-5">
              <div className="flex items-start gap-3">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-muted/55">
                  <Cpu className="h-5 w-5" aria-hidden />
                </span>
                <div>
                  <h2 className="text-lg font-semibold">{t("onboarding.aiTitle")}</h2>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    {t("onboarding.aiDescription")}
                  </p>
                </div>
              </div>

              <section className="space-y-3 rounded-2xl bg-muted/20 p-4">
                {customModel ? (
                  <label className="block space-y-1.5 text-sm font-medium">
                    <span>{t("onboarding.customModelName")}</span>
                    <Input
                      value={customModelName}
                      disabled={settingsLoading}
                      onChange={(event) => setCustomModelName(event.target.value)}
                      placeholder="qwen3:8b"
                      autoComplete="off"
                      spellCheck={false}
                    />
                  </label>
                ) : (
                  <label className="block space-y-1.5 text-sm font-medium">
                    <span>{t("onboarding.chatModel")}</span>
                    <Select
                      value={chatModel}
                      disabled={settingsLoading || modelOptions.length === 0}
                      onChange={(event) => setChatModel(event.target.value)}
                    >
                      {modelOptions.length === 0 && (
                        <option value="">{t("onboarding.noModels")}</option>
                      )}
                      {modelOptions.map((model) => (
                        <option key={model} value={model}>{model}</option>
                      ))}
                    </Select>
                  </label>
                )}
                <button
                  type="button"
                  className="text-left text-xs font-medium text-primary underline decoration-primary/35 underline-offset-4 hover:decoration-primary"
                  onClick={() => {
                    setCustomModel((current) => !current);
                    if (!customModelName) setCustomModelName(chatModel);
                  }}
                >
                  {customModel
                    ? t("onboarding.chooseInstalledModel")
                    : t("onboarding.useCustomModel")}
                </button>
                {customModel && (
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {t("onboarding.customModelHint")}
                  </p>
                )}
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {settingsLoading ? t("common.loading") : modelStatus}
                </p>
              </section>

              <section className="flex items-start gap-3 rounded-2xl bg-muted/20 p-4">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-muted/55">
                  <Globe2 className="h-5 w-5" aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="text-sm font-semibold">{t("onboarding.webSearchTitle")}</h3>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    {t("onboarding.webSearchDescription")}
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={webSearch}
                  aria-label={t("onboarding.webSearchTitle")}
                  disabled={settingsLoading}
                  onClick={() => setWebSearch((current) => !current)}
                  className={`relative mt-1 h-6 w-11 shrink-0 overflow-hidden rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50 ${
                    webSearch ? "bg-primary" : "bg-muted-foreground/30"
                  }`}
                >
                  <span className={`absolute left-0 top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${webSearch ? "translate-x-6" : "translate-x-1"}`} />
                </button>
              </section>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-5">
              <div className="flex items-start gap-3">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-muted/55">
                  <Landmark className="h-5 w-5" aria-hidden />
                </span>
                <div>
                  <h2 className="text-lg font-semibold">{t("onboarding.accountTitle")}</h2>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    {t("onboarding.accountDescription")}
                  </p>
                </div>
              </div>

              {accountCreated ? (
                <div className="space-y-4">
                  <div className="rounded-2xl bg-accent/10 p-5 text-center">
                    {initialSyncPending ? (
                      <Loader2 className="mx-auto h-7 w-7 animate-spin text-accent" aria-hidden />
                    ) : setupFailedState ? (
                      <span className="text-2xl" aria-hidden>⚠</span>
                    ) : (
                      <Check className="mx-auto h-7 w-7 text-accent" aria-hidden />
                    )}
                    <p className="mt-2 font-semibold">{t("onboarding.accountConnected")}</p>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {t(
                        setupFailedState
                          ? "onboarding.accountSetupFailedHint"
                          : initialSyncPending
                            ? syncTakingLonger
                              ? "onboarding.accountSyncTakingLonger"
                              : "onboarding.accountSyncInProgress"
                            : accountSyncQueued
                              ? "onboarding.accountSyncStarted"
                              : "onboarding.accountSyncPending",
                      )}
                    </p>
                  </div>
                  {setupFailedState && (
                    <Button
                      type="button"
                      variant="outline"
                      className="w-full"
                      disabled={busy}
                      onClick={() => void resetFailedConnection()}
                    >
                      {t("onboarding.accountSetupRetry")}
                    </Button>
                  )}
                </div>
              ) : (
                <ConnectionForm
                  onCreated={async (connection, syncQueued) => {
                    setAccountCreated(true);
                    setAccountSyncQueued(syncQueued);
                    setConnectionId(connection.id);
                    setInitialSyncDone(!syncQueued);
                    setSetupFailed(false);
                    setSyncStartedAt(syncQueued ? Date.now() : null);
                    await refreshSetup();
                  }}
                />
              )}
            </div>
          )}

          {step === 2 && (
            <div className="space-y-5">
              <div className="flex items-start gap-3">
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-muted/55">
                  <Tags className="h-5 w-5" aria-hidden />
                </span>
                <div>
                  <h2 className="text-lg font-semibold">{t("onboarding.categoriesTitle")}</h2>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                    {t("onboarding.categoriesDescription")}
                  </p>
                </div>
              </div>
              <div className="rounded-2xl bg-muted/20 p-5">
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {t("onboarding.categoriesOptional")}
                </p>
              </div>
            </div>
          )}

          {error && <p className="mt-4 text-sm text-danger">{error}</p>}
              </div>

              <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border/35 pt-4">
          <div>
            {step > 0 ? (
              <Button
                type="button"
                variant="ghost"
                className="min-h-11 gap-1.5"
                disabled={busy}
                onClick={() => setStep((current) => current - 1)}
              >
                <ChevronLeft className="h-4 w-4" aria-hidden />
                {t("common.back")}
              </Button>
            ) : (
              <Button
                type="button"
                variant="ghost"
                className="min-h-11"
                disabled={busy}
                onClick={() => void finish("/")}
              >
                {t("onboarding.setUpLater")}
              </Button>
            )}
          </div>

          <div className="ml-auto flex flex-wrap justify-end gap-2">
            {step === 0 && (
              <Button
                type="button"
                className="min-h-11 gap-1.5"
                disabled={busy || settingsLoading}
                onClick={() => void saveAiSettings()}
              >
                {t("common.continue")}
                <ChevronRight className="h-4 w-4" aria-hidden />
              </Button>
            )}
            {step === 1 && (
              <Button
                type="button"
                className="min-h-11 gap-1.5"
                disabled={busy || (initialSyncPending && !syncTakingLonger)}
                onClick={() => void continueFromAccountStep()}
              >
                {accountCreated
                  ? t("common.continue")
                  : t("onboarding.skipAccount")}
                <ChevronRight className="h-4 w-4" aria-hidden />
              </Button>
            )}
            {step === 2 && (
              <>
                <Button
                  type="button"
                  variant="outline"
                  className="min-h-11"
                  disabled={busy}
                  onClick={() => void finish("/categories")}
                >
                  {t("onboarding.customizeCategories")}
                </Button>
                <Button
                  type="button"
                  className="min-h-11"
                  disabled={busy}
                  onClick={() => void finish("/")}
                >
                  {busy ? t("common.loading") : t("onboarding.finish")}
                </Button>
              </>
            )}
          </div>
              </footer>
            </Card>
          </section>
        </main>
      </div>
    </div>
  );
}
