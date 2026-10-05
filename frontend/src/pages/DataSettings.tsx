import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CloudDownload, Cpu, DatabaseZap, Globe2, KeyRound, Loader2, MonitorPlay, RefreshCw, ShieldCheck } from "lucide-react";
import { useOutletContext } from "react-router-dom";

import { api, type Account, type Category, type OllamaModelKind, type OllamaModels } from "@/api/client";
import { useVault } from "@/auth/VaultContext";
import { BackPageHeader } from "@/components/BackPageHeader";
import { Button, Card, Input, Select, Textarea } from "@/components/ui";
import type { LayoutOutletContext } from "@/components/Layout";

export function DataSettingsPage() {
  const { t } = useTranslation();
  const { status: vaultStatus, refreshStatus } = useVault();
  const { demoMode, setDemoMode } = useOutletContext<LayoutOutletContext>();
  const [running, setRunning] = useState<"categorize" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ollama, setOllama] = useState<OllamaModels | null>(null);
  const [ollamaRefreshing, setOllamaRefreshing] = useState(false);
  const [categorizationWebSearch, setCategorizationWebSearch] = useState<boolean | null>(null);
  const [categorizationWebSearchSaving, setCategorizationWebSearchSaving] = useState(false);
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false);
  const [modelName, setModelName] = useState("");
  const [modelKind, setModelKind] = useState<OllamaModelKind>("chat");
  const [modelPulling, setModelPulling] = useState(false);
  const [modelPullCompleted, setModelPullCompleted] = useState(0);
  const [modelPullTotal, setModelPullTotal] = useState(0);
  const [modelSaving, setModelSaving] = useState(false);
  const [chatModelDraft, setChatModelDraft] = useState("");
  const [embeddingModelDraft, setEmbeddingModelDraft] = useState("");
  const [modelFeedback, setModelFeedback] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [recategorizeOpen, setRecategorizeOpen] = useState(false);
  const [recategorizeAccounts, setRecategorizeAccounts] = useState<Account[]>([]);
  const [recategorizeCategories, setRecategorizeCategories] = useState<Category[]>([]);
  const [recategorizeAccount, setRecategorizeAccount] = useState("");
  const [recategorizeCategory, setRecategorizeCategory] = useState("");
  const [includeManual, setIncludeManual] = useState(false);
  const [recategorizeLoading, setRecategorizeLoading] = useState(false);
  const [recoveryPhrase, setRecoveryPhrase] = useState("");
  const [recoveryConfirmation, setRecoveryConfirmation] = useState("");
  const [recoveryBusy, setRecoveryBusy] = useState(false);

  useEffect(() => {
    api.ollamaModels().then(setOllama).catch(() => setOllama(null));
    api.llmPreferences()
      .then((preferences) => setCategorizationWebSearch(
        preferences.categorization_web_search_enabled
      ))
      .catch(() => setCategorizationWebSearch(null));
  }, []);

  useEffect(() => {
    const phase = ollama?.auto_install.phase;
    if (phase !== "pending" && phase !== "waiting" && phase !== "checking" && phase !== "downloading") return;
    const timer = window.setTimeout(() => {
      void api.ollamaModels().then(setOllama).catch(() => undefined);
    }, phase === "downloading" ? 1500 : 5000);
    return () => window.clearTimeout(timer);
  }, [ollama?.auto_install.phase, ollama?.auto_install.completed]);

  const refreshOllama = async (button?: HTMLButtonElement) => {
    setOllamaRefreshing(true);
    try {
      setOllama(await api.ollamaModels());
    } finally {
      setOllamaRefreshing(false);
      button?.blur();
    }
  };

  const toggleCategorizationWebSearch = async () => {
    if (categorizationWebSearch === null || categorizationWebSearchSaving) return;
    const next = !categorizationWebSearch;
    setCategorizationWebSearchSaving(true);
    setError(null);
    try {
      const preferences = await api.setCategorizationWebSearch(next);
      setCategorizationWebSearch(
        preferences.categorization_web_search_enabled
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.error"));
    } finally {
      setCategorizationWebSearchSaving(false);
    }
  };

  const installOllamaModel = async () => {
    const requestedModel = modelName.trim();
    if (!requestedModel || modelPulling) return;
    if (!window.confirm(t(
      modelKind === "embedding"
        ? "dataSettings.installEmbeddingConfirm"
        : "dataSettings.installChatConfirm",
      { model: requestedModel }
    ))) return;
    setModelPulling(true);
    setModelPullCompleted(0);
    setModelPullTotal(0);
    setModelFeedback(null);
    try {
      await api.pullOllamaModel(requestedModel, modelKind, (progress) => {
        if (typeof progress.completed === "number") setModelPullCompleted(progress.completed);
        if (typeof progress.total === "number") setModelPullTotal(progress.total);
        if (progress.status === "selected") {
          if (modelKind === "embedding") setEmbeddingModelDraft(requestedModel);
          else setChatModelDraft(requestedModel);
          setOllama((current) => current
            ? modelKind === "embedding"
              ? { ...current, embedding_active: requestedModel }
              : { ...current, active: requestedModel }
            : current);
        }
      });
      await refreshOllama();
      setModelName("");
      setModelFeedback({
        tone: "success",
        text: t("dataSettings.modelInstallSuccess", { model: requestedModel }),
      });
    } catch (err) {
      setModelFeedback({
        tone: "error",
        text: err instanceof Error ? err.message : t("dataSettings.modelInstallFailed"),
      });
    } finally {
      setModelPulling(false);
    }
  };

  const modelPullPercent = modelPullTotal > 0
    ? Math.min(100, Math.round((modelPullCompleted / modelPullTotal) * 100))
    : null;

  const autoInstallPercent = ollama?.auto_install.total
    ? Math.min(100, Math.round(
        (ollama.auto_install.completed / ollama.auto_install.total) * 100
      ))
    : null;
  const ollamaStatus = ollama?.auto_install.phase === "downloading"
    ? t("dataSettings.defaultModelDownloading", {
        model: ollama.auto_install.model,
        percent: autoInstallPercent ?? 0,
      })
    : ollama?.auto_install.phase === "pending"
      ? t("dataSettings.defaultModelsPending")
    : ollama?.auto_install.phase === "waiting"
      ? t("dataSettings.defaultModelsWaiting")
      : ollama?.auto_install.phase === "error"
        ? t("dataSettings.defaultModelsFailed")
      : ollama?.auto_install.phase === "checking"
        ? t("dataSettings.defaultModelsChecking")
        : ollama?.reachable
          ? t("dataSettings.modelsAvailable")
          : t("dataSettings.modelOffline");

  const openRecategorizeSettings = async () => {
    setRecategorizeOpen(true);
    setRecategorizeLoading(true);
    setError(null);
    try {
      const [accounts, categories] = await Promise.all([
        api.accounts(),
        api.categories(),
      ]);
      setRecategorizeAccounts(accounts);
      setRecategorizeCategories(categories);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.error"));
    } finally {
      setRecategorizeLoading(false);
    }
  };

  const runRecategorize = async () => {
    if (running !== null || recategorizeLoading) return;
    if (includeManual && !window.confirm(t("dataSettings.recategorizeManualConfirm"))) return;
    setRunning("categorize");
    setMessage(null);
    setError(null);
    try {
      const result = await api.recategorize({
        account_id: recategorizeAccount ? Number(recategorizeAccount) : null,
        category_id: recategorizeCategory ? Number(recategorizeCategory) : null,
        include_manual: includeManual,
      });
      setMessage(t("dataSettings.recategorizeQueued", {
        reset: result.reset_count,
        rules: result.rules_applied,
        queued: result.queued_for_agent,
      }));
      setRecategorizeOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.error"));
    } finally {
      setRunning(null);
    }
  };

  const actions = [
    {
      id: "categorize" as const,
      title: t("dataSettings.categorizeTitle"),
      description: t("dataSettings.categorizeDescription"),
      action: t("dataSettings.categorizeAction"),
      icon: DatabaseZap,
    },
  ];

  const openModelSettings = () => {
    setChatModelDraft(ollama?.active || "");
    setEmbeddingModelDraft(ollama?.embedding_active || "");
    setModelFeedback(null);
    setModelSettingsOpen(true);
  };

  const applyModelSettings = async () => {
    if (!ollama || modelSaving || modelPulling) return;
    const chatChanged = Boolean(chatModelDraft && chatModelDraft !== ollama.active);
    const embeddingChanged = Boolean(
      embeddingModelDraft && embeddingModelDraft !== ollama.embedding_active
    );
    if (!chatChanged && !embeddingChanged) {
      setModelSettingsOpen(false);
      return;
    }
    if (embeddingChanged && !window.confirm(t("dataSettings.embeddingChangeConfirm"))) return;

    setModelSaving(true);
    setError(null);
    try {
      if (chatChanged) {
        await api.selectOllamaModel(chatModelDraft);
      }
      if (embeddingChanged) {
        await api.selectOllamaEmbeddingModel(embeddingModelDraft);
      }
      await refreshOllama();
      setMessage(t(
        embeddingChanged
          ? "dataSettings.modelChangeSavedWithEmbedding"
          : "dataSettings.modelChangeSaved"
      ));
      setModelSettingsOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.error"));
    } finally {
      setModelSaving(false);
    }
  };

  const normalizedPhrase = (value: string) =>
    value.trim().toLowerCase().split(/\s+/).filter(Boolean).join(" ");

  const createRecoveryPhrase = async () => {
    if (recoveryBusy) return;
    if (
      vaultStatus?.recovery_configured
      && !window.confirm(t("dataSettings.recoveryReplaceConfirm"))
    ) return;
    setRecoveryBusy(true);
    setError(null);
    try {
      const result = await api.vaultRegenerateRecovery();
      setRecoveryPhrase(result.recovery_phrase);
      setRecoveryConfirmation("");
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.error"));
    } finally {
      setRecoveryBusy(false);
    }
  };

  const confirmRecoveryPhrase = async () => {
    if (normalizedPhrase(recoveryConfirmation) !== recoveryPhrase) {
      setError(t("vault.recoveryMismatch"));
      return;
    }
    setRecoveryBusy(true);
    setError(null);
    try {
      await api.vaultConfirmRecovery(recoveryPhrase, undefined, true);
      setRecoveryPhrase("");
      setRecoveryConfirmation("");
      setMessage(t("dataSettings.recoveryConfirmed"));
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.error"));
    } finally {
      setRecoveryBusy(false);
    }
  };

  return (
    <section className="w-full space-y-5">
      <BackPageHeader title={t("dataSettings.settingsTitle")} />
      <Card className="space-y-3 p-4">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">{t("dataSettings.aiSection")}</p>
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-muted/55"><Cpu className="h-5 w-5" aria-hidden /></span>
          <div className="min-w-0 flex-1"><h3 className="text-sm font-semibold">{t("dataSettings.localModel")}</h3><p className="text-xs text-muted-foreground">{ollamaStatus}</p></div>
          <Button
            variant="ghost"
            className="h-9 w-9 rounded-full p-0"
            aria-label={t("common.refresh")}
            aria-busy={ollamaRefreshing}
            title={t("common.refresh")}
            disabled={ollamaRefreshing}
            onClick={(event) => void refreshOllama(event.currentTarget)}
          >
            <RefreshCw className={ollamaRefreshing ? "h-4 w-4 animate-spin" : "h-4 w-4"} aria-hidden />
          </Button>
        </div>
        <div className="flex items-center justify-between gap-3 rounded-xl bg-muted/25 px-3 py-2.5"><div className="min-w-0 text-sm"><p className="font-medium truncate">{ollama?.active || t("dataSettings.noModels")}</p><p className="text-xs text-muted-foreground">{t("dataSettings.embeddingModel")}: {ollama?.embedding_active || t("dataSettings.notSelected")}</p></div><Button variant="outline" className="h-9 shrink-0 px-3" onClick={openModelSettings}>{t("common.edit")}</Button></div>
        <div className="flex items-center gap-3 border-t border-border/35 pt-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-muted/55">
            <Globe2 className="h-5 w-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold">{t("dataSettings.categorizationWebSearchTitle")}</h3>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              {t("dataSettings.categorizationWebSearchDescription")}
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={categorizationWebSearch ?? false}
            aria-label={t("dataSettings.categorizationWebSearchTitle")}
            disabled={categorizationWebSearch === null || categorizationWebSearchSaving}
            onClick={() => void toggleCategorizationWebSearch()}
            className={`relative h-6 w-11 shrink-0 overflow-hidden rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50 ${categorizationWebSearch ? "bg-primary" : "bg-muted-foreground/30"}`}
          >
            <span className={`absolute left-0 top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${categorizationWebSearch ? "translate-x-6" : "translate-x-1"}`} />
          </button>
        </div>
      </Card>
      <Card className="space-y-3 p-4">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-muted/55">
            <MonitorPlay className="h-5 w-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold">{t("dataSettings.demoModeTitle")}</h3>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{t("dataSettings.demoModeDescription")}</p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={demoMode}
            aria-label={t("dataSettings.demoModeTitle")}
            onClick={() => setDemoMode(!demoMode)}
            className={`relative h-6 w-11 shrink-0 overflow-hidden rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 ${demoMode ? "bg-primary" : "bg-muted-foreground/30"}`}
          >
            <span className={`absolute left-0 top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${demoMode ? "translate-x-6" : "translate-x-1"}`} />
          </button>
        </div>
        {demoMode && <p className="rounded-xl bg-warning/10 px-3 py-2 text-xs leading-relaxed text-warning">{t("dataSettings.demoModeActive")}</p>}
      </Card>
      <Card className="space-y-3 p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="flex min-w-0 items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-muted/55">
              <KeyRound className="h-5 w-5" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="text-sm font-semibold">{t("dataSettings.recoveryTitle")}</h3>
              <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                {vaultStatus?.recovery_confirmed
                  ? t("dataSettings.recoveryReady")
                  : vaultStatus?.recovery_configured
                    ? t("dataSettings.recoveryUnconfirmed")
                    : t("dataSettings.recoveryMissingHint")}
              </p>
            </div>
          </div>
          <Button
            variant="outline"
            className="h-9 w-full shrink-0 gap-2 px-3 sm:ml-auto sm:w-auto"
            disabled={recoveryBusy}
            onClick={() => void createRecoveryPhrase()}
          >
            {recoveryBusy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
            {vaultStatus?.recovery_configured
              ? t("dataSettings.recoveryReplace")
              : t("dataSettings.recoveryCreate")}
          </Button>
        </div>
      </Card>
      <Card className="space-y-1 p-2">
        <p className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">{t("dataSettings.dataSection")}</p>
        {actions.map((item) => {
          const Icon = item.icon;
          const isRunning = running === item.id;
          return (
            <div key={item.id} className="rounded-[1.25rem] px-3 py-3.5 hover:bg-card/45 sm:px-4">
              <div className="flex items-center gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-muted/55">
                  <Icon className="h-5 w-5" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold sm:text-base">{item.title}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground sm:text-sm">
                    {item.description}
                  </span>
                </span>
                <Button
                  variant="outline"
                  className="h-9 shrink-0 px-3"
                  disabled={running !== null}
                  onClick={() => void openRecategorizeSettings()}
                >
                  {isRunning ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : item.action}
                </Button>
              </div>
            </div>
          );
        })}
      </Card>
      {message && <p className="px-1 text-sm text-accent">{message}</p>}
      {error && <p className="px-1 text-sm text-danger">{error}</p>}
      {recategorizeOpen && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/25 p-4 backdrop-blur-sm"
          onMouseDown={(event) => {
            if (running !== "categorize" && event.target === event.currentTarget) {
              setRecategorizeOpen(false);
            }
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="recategorize-title"
            className="max-h-[calc(100dvh-2rem)] w-full max-w-md overflow-y-auto rounded-[1.5rem] border border-border/50 bg-background/95 p-5 shadow-2xl"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 id="recategorize-title" className="text-lg font-semibold">
                  {t("dataSettings.categorizeModalTitle")}
                </h2>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  {t("dataSettings.categorizeModalHint")}
                </p>
              </div>
              <Button
                variant="ghost"
                className="h-8 w-8 rounded-full p-0"
                disabled={running === "categorize"}
                onClick={() => setRecategorizeOpen(false)}
                aria-label={t("common.close")}
              >×</Button>
            </div>

            <div className="mt-5 space-y-4">
              <label className="block space-y-1.5 text-xs text-muted-foreground">
                <span>{t("dataSettings.accountScope")}</span>
                <Select
                  value={recategorizeAccount}
                  disabled={recategorizeLoading || running === "categorize"}
                  onChange={(event) => setRecategorizeAccount(event.target.value)}
                >
                  <option value="">{t("dataSettings.allAccounts")}</option>
                  {recategorizeAccounts.map((account) => (
                    <option key={account.id} value={account.id}>{account.name}</option>
                  ))}
                </Select>
              </label>
              <label className="block space-y-1.5 text-xs text-muted-foreground">
                <span>{t("dataSettings.categoryScope")}</span>
                <Select
                  value={recategorizeCategory}
                  disabled={recategorizeLoading || running === "categorize"}
                  onChange={(event) => setRecategorizeCategory(event.target.value)}
                >
                  <option value="">{t("dataSettings.allCategories")}</option>
                  {recategorizeCategories.map((category) => (
                    <option key={category.id} value={category.id}>{category.name}</option>
                  ))}
                </Select>
              </label>
              <label className="flex items-start gap-3 rounded-xl border border-border/40 bg-muted/20 p-3">
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-border accent-primary"
                  checked={includeManual}
                  disabled={recategorizeLoading || running === "categorize"}
                  onChange={(event) => setIncludeManual(event.target.checked)}
                />
                <span>
                  <span className="block text-sm font-medium text-foreground">
                    {t("dataSettings.includeManual")}
                  </span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
                    {t("dataSettings.includeManualHint")}
                  </span>
                </span>
              </label>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <Button
                variant="ghost"
                disabled={running === "categorize"}
                onClick={() => setRecategorizeOpen(false)}
              >
                {t("common.cancel")}
              </Button>
              <Button
                className="gap-2"
                disabled={recategorizeLoading || running === "categorize"}
                onClick={() => void runRecategorize()}
              >
                {(recategorizeLoading || running === "categorize") && (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                )}
                {t("dataSettings.recategorizeStart")}
              </Button>
            </div>
          </div>
        </div>
      )}
      {modelSettingsOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/25 p-4 backdrop-blur-sm" onMouseDown={(event) => { if (!modelPulling && !modelSaving && event.target === event.currentTarget) setModelSettingsOpen(false); }}>
          <div role="dialog" aria-modal="true" aria-labelledby="model-settings-title" className="max-h-[calc(100dvh-2rem)] w-full max-w-md overflow-y-auto rounded-[1.5rem] border border-border/50 bg-background/95 p-5 shadow-2xl">
            <div className="mb-4 flex items-start justify-between gap-3"><div><h2 id="model-settings-title" className="text-lg font-semibold">{t("dataSettings.modelsTitle")}</h2><p className="mt-1 text-sm text-muted-foreground">{t("dataSettings.modelsHint")}</p></div><Button variant="ghost" className="h-8 w-8 rounded-full p-0" disabled={modelPulling || modelSaving} onClick={() => setModelSettingsOpen(false)} aria-label={t("common.close")}>×</Button></div>
            <div className="space-y-3"><label className="block space-y-1 text-xs text-muted-foreground"><span>{t("dataSettings.chatModel")}</span><Select disabled={!ollama?.reachable || !ollama.models.length || modelSaving} value={chatModelDraft} onChange={(e) => setChatModelDraft(e.target.value)}>{!ollama?.models.length && <option value="">{t("dataSettings.noModels")}</option>}{ollama?.models.map((model) => <option key={model} value={model}>{model}</option>)}</Select></label><label className="block space-y-1 text-xs text-muted-foreground"><span>{t("dataSettings.embeddingModel")}</span><Select disabled={!ollama?.reachable || !ollama.embedding_models.length || modelSaving} value={embeddingModelDraft} onChange={(e) => setEmbeddingModelDraft(e.target.value)}>{!ollama?.embedding_models.length && <option value="">{t("dataSettings.noEmbeddingModels")}</option>}{ollama?.embedding_models.map((model) => <option key={model} value={model}>{model}</option>)}</Select></label></div>
            <div className="mt-5 space-y-3 border-t border-border/40 pt-4">
              <div className="flex items-center gap-2"><CloudDownload className="h-4 w-4 text-muted-foreground" aria-hidden /><h3 className="text-sm font-semibold">{t("dataSettings.installModel")}</h3></div>
              <p className="text-xs leading-relaxed text-muted-foreground">{t("dataSettings.installModelHint")}</p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_8rem]">
                <label className="block space-y-1 text-xs text-muted-foreground"><span>{t("dataSettings.modelName")}</span><Input value={modelName} onChange={(event) => setModelName(event.target.value)} disabled={modelPulling} placeholder={modelKind === "embedding" ? "qwen3-embedding:4b" : "qwen3:4b"} /></label>
                <label className="block space-y-1 text-xs text-muted-foreground"><span>{t("dataSettings.modelRole")}</span><Select value={modelKind} onChange={(event) => setModelKind(event.target.value as OllamaModelKind)} disabled={modelPulling}><option value="chat">{t("dataSettings.chatModel")}</option><option value="embedding">{t("dataSettings.embeddingModel")}</option></Select></label>
              </div>
              {modelPulling && <div className="space-y-1.5" aria-live="polite"><div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={modelPullPercent ?? undefined} className="h-1.5 overflow-hidden rounded-full bg-muted/60"><div className={`h-full rounded-full bg-primary transition-[width] duration-300 ${modelPullPercent === null ? "w-1/3 animate-pulse" : ""}`} style={modelPullPercent === null ? undefined : { width: `${modelPullPercent}%` }} /></div><p className="text-xs text-muted-foreground">{modelPullPercent === null ? t("dataSettings.modelPreparing") : t("dataSettings.modelProgress", { percent: modelPullPercent })}</p></div>}
              <Button className="w-full gap-2" disabled={!ollama?.reachable || !modelName.trim() || modelPulling} onClick={() => void installOllamaModel()}>{modelPulling ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <CloudDownload className="h-4 w-4" aria-hidden />}{modelPulling ? t("dataSettings.modelInstalling") : t("dataSettings.modelInstall")}</Button>
              {modelFeedback && <p role="status" className={`text-xs ${modelFeedback.tone === "success" ? "text-accent" : "text-danger"}`}>{modelFeedback.text}</p>}
            </div>
            <div className="mt-5 flex justify-end gap-2"><Button variant="ghost" disabled={modelPulling || modelSaving} onClick={() => setModelSettingsOpen(false)}>{t("common.cancel")}</Button><Button className="gap-2" disabled={modelPulling || modelSaving} onClick={() => void applyModelSettings()}>{modelSaving && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}{t("common.save")}</Button></div>
          </div>
        </div>
      )}
      {recoveryPhrase && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/25 p-4 backdrop-blur-sm">
          <div role="dialog" aria-modal="true" aria-labelledby="recovery-title" className="max-h-[calc(100dvh-2rem)] w-full max-w-lg overflow-y-auto rounded-[1.5rem] border border-border/50 bg-background/95 p-5 shadow-2xl">
            <div className="flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-muted/55">
                <ShieldCheck className="h-5 w-5" aria-hidden />
              </span>
              <div>
                <h2 id="recovery-title" className="text-lg font-semibold">{t("vault.recoverySetupTitle")}</h2>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{t("vault.recoverySetupSubtitle")}</p>
              </div>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3">
              {recoveryPhrase.split(" ").map((word, index) => (
                <div key={`${word}-${index}`} className="rounded-xl border border-border/60 bg-muted/30 px-3 py-2">
                  <span className="mr-2 text-xs tabular-nums text-muted-foreground">{index + 1}.</span>
                  <span className="font-mono text-sm font-medium">{word}</span>
                </div>
              ))}
            </div>
            <p className="mt-4 rounded-xl bg-warning/10 px-3 py-2.5 text-xs leading-relaxed text-warning">{t("vault.recoveryWarning")}</p>
            <label className="mt-4 block space-y-1.5 text-sm font-medium" htmlFor="settings-recovery-confirmation">
              <span>{t("vault.recoveryConfirmLabel")}</span>
              <Textarea
                id="settings-recovery-confirmation"
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                value={recoveryConfirmation}
                onChange={(event) => setRecoveryConfirmation(event.target.value)}
                placeholder={t("vault.recoveryPlaceholder")}
                className="min-h-24 font-mono"
              />
            </label>
            {error && <p className="mt-3 text-sm text-danger">{error}</p>}
            <Button className="mt-4 h-11 w-full gap-2" disabled={recoveryBusy} onClick={() => void confirmRecoveryPhrase()}>
              {recoveryBusy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <ShieldCheck className="h-4 w-4" aria-hidden />}
              {t("vault.recoverySaved")}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
