import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { KeyRound, LockKeyhole, Moon, ShieldCheck, Sun } from "lucide-react";

import { useVault } from "@/auth/VaultContext";
import { AssistantAvatar } from "@/components/AssistantAvatar";
import { Button, Card, Input, Textarea } from "@/components/ui";
import { LanguageSwitch } from "@/components/LanguageSwitch";
import { applyTheme, getStoredTheme, toggleTheme, type ThemeMode } from "@/lib/theme";

export function UnlockPage() {
  const { t } = useTranslation();
  const {
    status,
    setup,
    confirmSetupRecovery,
    unlock,
    recover,
    loading,
    error: vaultError,
  } = useVault();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mode, setMode] = useState<"password" | "recover" | "setupRecovery">("password");
  const [recoveryPhrase, setRecoveryPhrase] = useState("");
  const [recoveryConfirmation, setRecoveryConfirmation] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [theme, setTheme] = useState<ThemeMode>(() => getStoredTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-muted-foreground">{t("common.loading")}</p>
      </div>
    );
  }

  const isSetup = !(status?.initialized ?? true);

  const normalizedPhrase = (value: string) =>
    value.trim().toLowerCase().split(/\s+/).filter(Boolean).join(" ");

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (isSetup && password !== confirm) {
      setError(t("vault.passwordMismatch"));
      return;
    }
    if (password.length < 8) {
      setError(t("vault.passwordTooShort"));
      return;
    }
    setBusy(true);
    try {
      if (isSetup) {
        const result = await setup(password);
        setRecoveryPhrase(result.recovery_phrase);
        setSetupToken(result.token);
        setPassword("");
        setConfirm("");
        setMode("setupRecovery");
      } else {
        await unlock(password);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("vault.unlockFailed"));
    } finally {
      setBusy(false);
    }
  };

  const onConfirmRecovery = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!recoveryConfirmation.trim()) {
      return;
    }
    const firstRecoveryWord = recoveryPhrase.split(" ")[0] || "";
    if (normalizedPhrase(recoveryConfirmation) !== firstRecoveryWord) {
      setError(t("vault.recoveryFirstWordMismatch"));
      return;
    }
    setBusy(true);
    try {
      await confirmSetupRecovery(recoveryPhrase, setupToken);
      setRecoveryPhrase("");
      setRecoveryConfirmation("");
      setSetupToken("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("vault.recoveryConfirmFailed"));
    } finally {
      setBusy(false);
    }
  };

  const onRecover = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError(t("vault.passwordMismatch"));
      return;
    }
    if (password.length < 8) {
      setError(t("vault.passwordTooShort"));
      return;
    }
    setBusy(true);
    try {
      await recover(recoveryConfirmation, password);
      setRecoveryConfirmation("");
      setPassword("");
      setConfirm("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("vault.recoveryFailed"));
    } finally {
      setBusy(false);
    }
  };

  const title = mode === "setupRecovery"
    ? t("vault.recoverySetupTitle")
    : mode === "recover"
      ? t("vault.recoveryTitle")
      : isSetup
        ? t("vault.setupTitle")
        : t("vault.unlockTitle");

  const subtitle = mode === "setupRecovery"
    ? t("vault.recoverySetupSubtitle")
    : mode === "recover"
      ? t("vault.recoverySubtitle")
      : isSetup
        ? t("vault.setupSubtitle")
        : t("vault.unlockSubtitle");

  return (
    <div className="min-h-screen px-3 py-3 text-foreground sm:px-5 sm:py-5">
      <div className="mx-auto flex min-h-[calc(100vh-1.5rem)] max-w-6xl flex-col sm:min-h-[calc(100vh-2.5rem)]">
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

        <main className="flex flex-1 items-center justify-center py-10 sm:py-14">
          <section className="w-full max-w-md">
            <div className="mb-5 px-1 sm:mb-6">
              <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                {mode === "password" ? (
                  <LockKeyhole className="h-3.5 w-3.5" aria-hidden />
                ) : (
                  <KeyRound className="h-3.5 w-3.5" aria-hidden />
                )}
                <span>
                  {mode === "setupRecovery"
                    ? t("vault.recoveryPhrase")
                    : mode === "recover"
                      ? t("vault.recoverVault")
                      : isSetup
                        ? t("vault.createVault")
                        : t("vault.unlock")}
                </span>
              </div>
              <h1 className="text-[1.7rem] font-semibold leading-tight tracking-[-0.02em] sm:text-[1.9rem]">
                {title}
              </h1>
              <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-muted-foreground">
                {subtitle}
              </p>
            </div>

            <Card className="rounded-[1.5rem] p-4 sm:p-5">
              {mode === "setupRecovery" ? (
                <form className="flex flex-col gap-4" onSubmit={onConfirmRecovery}>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {recoveryPhrase.split(" ").map((word, index) => (
                      <div
                        key={`${word}-${index}`}
                        className="rounded-xl border border-border/60 bg-muted/30 px-3 py-2"
                      >
                        <span className="mr-2 text-xs tabular-nums text-muted-foreground">
                          {index + 1}.
                        </span>
                        <span className="font-mono text-sm font-medium">{word}</span>
                      </div>
                    ))}
                  </div>
                  <p className="rounded-xl bg-warning/10 px-3 py-2.5 text-xs leading-relaxed text-warning">
                    {t("vault.recoveryWarning")}
                  </p>
                  <label className="block space-y-1.5 text-sm font-medium" htmlFor="recovery-confirmation">
                    <span>{t("vault.recoveryFirstWordLabel")}</span>
                    <Input
                      id="recovery-confirmation"
                      autoComplete="off"
                      autoCapitalize="none"
                      spellCheck={false}
                      value={recoveryConfirmation}
                      onChange={(event) => setRecoveryConfirmation(event.target.value)}
                      placeholder={t("vault.recoveryFirstWordPlaceholder")}
                      required
                      className="h-11 font-mono"
                    />
                  </label>
                  {(error || vaultError) && (
                    <p className="text-sm text-danger">{error || vaultError}</p>
                  )}
                  <Button
                    type="submit"
                    disabled={busy || !recoveryConfirmation.trim()}
                    className="h-11 w-full gap-2 rounded-xl"
                  >
                    <ShieldCheck className="h-4 w-4" aria-hidden />
                    {busy ? t("common.loading") : t("vault.recoverySaved")}
                  </Button>
                </form>
              ) : mode === "recover" ? (
                <form className="flex flex-col gap-4" onSubmit={onRecover}>
                  <label className="block space-y-1.5 text-sm font-medium" htmlFor="recovery-phrase">
                    <span>{t("vault.recoveryPhrase")}</span>
                    <Textarea
                      id="recovery-phrase"
                      autoComplete="off"
                      autoCapitalize="none"
                      spellCheck={false}
                      value={recoveryConfirmation}
                      onChange={(event) => setRecoveryConfirmation(event.target.value)}
                      placeholder={t("vault.recoveryPlaceholder")}
                      required
                      className="min-h-24 font-mono"
                    />
                  </label>
                  <label className="block space-y-1.5 text-sm font-medium" htmlFor="new-password">
                    <span>{t("vault.newMasterPassword")}</span>
                    <Input
                      id="new-password"
                      type="password"
                      autoComplete="new-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      required
                      minLength={8}
                      className="h-11"
                    />
                  </label>
                  <label className="block space-y-1.5 text-sm font-medium" htmlFor="new-password-confirm">
                    <span>{t("vault.confirmPassword")}</span>
                    <Input
                      id="new-password-confirm"
                      type="password"
                      autoComplete="new-password"
                      value={confirm}
                      onChange={(event) => setConfirm(event.target.value)}
                      required
                      minLength={8}
                      className="h-11"
                    />
                  </label>
                  {(error || vaultError) && (
                    <p className="text-sm text-danger">{error || vaultError}</p>
                  )}
                  <Button type="submit" disabled={busy} className="h-11 w-full rounded-xl">
                    {busy ? t("common.loading") : t("vault.resetPassword")}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => {
                      setMode("password");
                      setError(null);
                      setRecoveryConfirmation("");
                      setPassword("");
                      setConfirm("");
                    }}
                  >
                    {t("vault.backToUnlock")}
                  </Button>
                </form>
              ) : (
              <form className="flex flex-col gap-4" onSubmit={onSubmit}>
                <label className="block space-y-1.5 text-sm font-medium" htmlFor="password">
                  <span>{t("vault.masterPassword")}</span>
                  <Input
                    id="password"
                    type="password"
                    autoComplete={isSetup ? "new-password" : "current-password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={8}
                    className="h-11"
                  />
                </label>
                {isSetup && (
                  <label className="block space-y-1.5 text-sm font-medium" htmlFor="confirm">
                    <span>{t("vault.confirmPassword")}</span>
                    <Input
                      id="confirm"
                      type="password"
                      autoComplete="new-password"
                      value={confirm}
                      onChange={(e) => setConfirm(e.target.value)}
                      required
                      minLength={8}
                      className="h-11"
                    />
                  </label>
                )}
                {(error || vaultError) && (
                  <p className="text-sm text-danger">{error || vaultError}</p>
                )}
                <Button type="submit" disabled={busy} className="mt-1 h-11 w-full rounded-xl">
                  {busy
                    ? t("common.loading")
                    : isSetup
                      ? t("vault.createVault")
                      : t("vault.unlock")}
                </Button>
                {!isSetup && status?.recovery_configured && (
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => {
                      setMode("recover");
                      setError(null);
                      setPassword("");
                    }}
                  >
                    {t("vault.forgotPassword")}
                  </Button>
                )}
              </form>
              )}
            </Card>
          </section>
        </main>
      </div>
    </div>
  );
}
