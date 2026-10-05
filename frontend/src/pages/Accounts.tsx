import { FormEvent, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Landmark, Loader2, Pencil, RefreshCw, Trash2, X } from "lucide-react";

import { api, type Account, type Connection, type SyncStatus } from "@/api/client";
import { useAppSetup } from "@/auth/AppSetupContext";
import { BackPageHeader } from "@/components/BackPageHeader";
import {
  ConnectionForm,
  FieldHint,
  fieldHint,
  fieldLabel,
  secretFields,
  type Provider,
} from "@/components/ConnectionForm";
import { Badge, Button, Card, Input, Textarea } from "@/components/ui";
import { AccountIcon } from "@/lib/icons";
import { cn, formatMoney } from "@/lib/utils";

type DetailTarget =
  | { kind: "account"; account: Account }
  | { kind: "connection"; connection: Connection };

export function AccountsPage() {
  const { t, i18n } = useTranslation();
  const { refreshAccounts, updateAccounts } = useAppSetup();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [status, setStatus] = useState<SyncStatus[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [backfillFrom, setBackfillFrom] = useState("2021-01-01");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [detail, setDetail] = useState<DetailTarget | null>(null);
  const [editingSetup, setEditingSetup] = useState(false);
  const [editingCredentials, setEditingCredentials] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [editConnName, setEditConnName] = useState("");
  const [editSecrets, setEditSecrets] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [refreshingIds, setRefreshingIds] = useState<Set<number>>(new Set());
  const [refreshingConnectionIds, setRefreshingConnectionIds] = useState<Set<number>>(new Set());
  const hasOpenModal = addOpen || detail !== null;

  const load = () => {
    Promise.all([api.accounts(), api.syncStatus(), api.connections()])
      .then(([accs, st, conns]) => {
        setAccounts(accs);
        updateAccounts(accs);
        setStatus(st);
        setConnections(conns);
        setError(null);
        setDetail((prev) => {
          if (!prev) return prev;
          if (prev.kind === "account") {
            const next = accs.find((a) => a.id === prev.account.id);
            return next ? { kind: "account", account: next } : null;
          }
          const next = conns.find((c) => c.id === prev.connection.id);
          return next ? { kind: "connection", connection: next } : null;
        });
      })
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    load();
    const id = window.setInterval(load, 5000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!hasOpenModal) return;
    const scrollY = window.scrollY;
    const previous = {
      position: document.body.style.position,
      top: document.body.style.top,
      width: document.body.style.width,
      overflow: document.body.style.overflow,
    };
    document.body.style.position = "fixed";
    document.body.style.top = `-${scrollY}px`;
    document.body.style.width = "100%";
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.position = previous.position;
      document.body.style.top = previous.top;
      document.body.style.width = previous.width;
      document.body.style.overflow = previous.overflow;
      window.scrollTo(0, scrollY);
    };
  }, [hasOpenModal]);

  const statusByAccount = useMemo(
    () => Object.fromEntries(status.map((s) => [s.account_id, s])),
    [status]
  );

  const connectionForAccount = (account: Account) => {
    if (account.connection_id != null) {
      return connections.find((c) => c.id === account.connection_id) || null;
    }
    const matches = connections.filter((c) => c.source === account.source);
    if (matches.length === 1) return matches[0];

    const normalize = (value?: string | null) =>
      (value || "").replace(/\s/g, "").toUpperCase();
    const accountIban = normalize(account.iban);
    if (!accountIban) return null;
    return matches.find((c) => normalize(c.public_fields.iban) === accountIban) || null;
  };

  const orphanConnections = connections.filter(
    (connection) =>
      !accounts.some((account) => connectionForAccount(account)?.id === connection.id)
  );

  type SyncActivity = "queued" | "running" | null;

  const syncActivity = (accountId: number, st?: SyncStatus): SyncActivity => {
    if (
      refreshingIds.has(accountId) ||
      st?.status === "running" ||
      st?.status === "backfilling" ||
      st?.latest_job_status === "running"
    ) {
      return "running";
    }
    if (st?.latest_job_status === "pending" || (st?.pending_jobs ?? 0) > 0) {
      return "queued";
    }
    return null;
  };

  const isSyncing = (accountId: number, st?: SyncStatus) =>
    syncActivity(accountId, st) !== null;

  useEffect(() => {
    const grace = window.setTimeout(() => {
      setRefreshingIds((prev) => {
        if (prev.size === 0) return prev;
        const next = new Set(prev);
        const busy = (st?: SyncStatus) =>
          st?.status === "running" || st?.status === "backfilling";
        for (const id of prev) {
          if (!busy(statusByAccount[id])) next.delete(id);
        }
        return next;
      });
    }, 2500);
    return () => window.clearTimeout(grace);
  }, [status, statusByAccount]);

  const StatusBadge = ({
    activity,
    error,
  }: {
    activity: SyncActivity;
    error?: boolean;
  }) => {
    if (!activity && !error) return null;
    return (
      <Badge
        className={cn(
          "shrink-0 gap-1.5 border-0 font-medium",
          activity && "bg-warning text-warning-foreground",
          !activity && error && "bg-danger text-danger-foreground",
        )}
      >
        {activity === "running" && <Loader2 className="h-3 w-3 animate-spin" aria-hidden />}
        {activity === "queued" && <RefreshCw className="h-3 w-3" aria-hidden />}
        {activity
          ? t(activity === "queued" ? "accounts.queued" : "accounts.updating")
          : t("syncStatus.error")}
      </Badge>
    );
  };

  const onRefresh = async (accountId: number) => {
    setRefreshingIds((prev) => new Set(prev).add(accountId));
    try {
      const res = await api.triggerSync({
        account_id: accountId,
        mode: "sync",
      });
      setMessage(res.message);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("accounts.syncFailed"));
    }
  };

  const onRefreshAll = async () => {
    if (refreshingAll) return;
    setRefreshingAll(true);
    setError(null);
    try {
      const res = await api.triggerSync({ mode: "sync" });
      setMessage(res.message);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("accounts.syncFailed"));
    } finally {
      // The request only enqueues the worker job. Keep the header action
      // visibly busy until the next status poll has picked up the jobs.
      window.setTimeout(() => setRefreshingAll(false), 2500);
    }
  };

  const onRefreshConnection = async (connectionId: number) => {
    setRefreshingConnectionIds((prev) => new Set(prev).add(connectionId));
    try {
      const res = await api.triggerSync({ connection_id: connectionId, mode: "sync" });
      setMessage(res.message);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("accounts.syncFailed"));
    } finally {
      // Sync runs in the backend worker. Keep the connection action visibly
      // busy long enough for the next status poll instead of clearing it after
      // the enqueue request has returned.
      window.setTimeout(() => {
        setRefreshingConnectionIds((prev) => {
          const next = new Set(prev);
          next.delete(connectionId);
          return next;
        });
      }, 30000);
    }
  };

  const onBackfill = async (target: DetailTarget) => {
    const body = target.kind === "account"
      ? { account_id: target.account.id, mode: "backfill" as const, history_from: backfillFrom }
      : { connection_id: target.connection.id, mode: "backfill" as const, history_from: backfillFrom };
    try {
      const res = await api.triggerSync(body);
      setMessage(res.message);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("accounts.syncFailed"));
    }
  };

  const closeDetail = () => {
    setDetail(null);
    setEditingSetup(false);
    setEditingCredentials(false);
  };

  const openAccountDetail = (account: Account) => {
    const conn = connectionForAccount(account);
    setDetail({ kind: "account", account });
    setEditConnName(conn?.name || account.name);
    setEditSecrets({});
    setEditingSetup(false);
  };

  const openConnectionDetail = (connection: Connection) => {
    setDetail({ kind: "connection", connection });
    setEditConnName(connection.name);
    setEditSecrets({});
    setEditingSetup(false);
  };

  const activeConnection = detail
    ? detail.kind === "connection"
      ? detail.connection
      : connectionForAccount(detail.account)
    : null;

  const openAddDialog = () => {
    setError(null);
    setAddOpen(true);
  };

  const onSaveSetup = async (e: FormEvent) => {
    e.preventDefault();
    if (!activeConnection) return;
    setError(null);
    try {
      const body: { name?: string; secrets?: Record<string, string> } = {
        name: editConnName.trim() || activeConnection.name,
      };
      const filled = Object.fromEntries(
        Object.entries(editSecrets).filter(([, v]) => v.trim() !== "")
      );
      if (Object.keys(filled).length > 0) body.secrets = filled;
      await api.updateConnection(activeConnection.id, body);
      setMessage(t("connections.saved"));
      setEditingSetup(false);
      setEditingCredentials(false);
      setEditSecrets({});
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("connections.saveFailed"));
    }
  };

  const onDelete = async () => {
    if (!detail || deleting) return;
    const name = detail.kind === "account" ? detail.account.name : detail.connection.name;
    if (!window.confirm(t("connections.deleteConfirm", { name }))) return;
    setDeleting(true);
    try {
      if (detail.kind === "account") {
        await api.deleteAccount(detail.account.id);
      } else {
        await api.deleteConnection(detail.connection.id);
      }
      closeDetail();
      load();
      await refreshAccounts();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("connections.deleteFailed"));
    } finally {
      setDeleting(false);
    }
  };

  const detailProvider = (activeConnection?.provider || "volksbank") as Provider;
  const detailFields = secretFields(detailProvider, t);

  const detailRows = (() => {
    const rows: { label: string; value: string }[] = [];
    if (detail?.kind === "account") {
      const acc = detail.account;
      rows.push({
        label: t("accounts.type"),
        value: t(`accountTypes.${acc.account_type}`, { defaultValue: acc.account_type }),
      });
      if (acc.iban) rows.push({ label: t("accounts.iban"), value: acc.iban });
      if (acc.current_balance != null) {
        rows.push({
          label: t("accounts.bookedBalance"),
          value: formatMoney(acc.current_balance, acc.currency, i18n.language),
        });
      }
      if (
        acc.available_balance != null &&
        acc.available_balance !== acc.current_balance
      ) {
        rows.push({
          label: t("accounts.availableBalance"),
          value: formatMoney(acc.available_balance, acc.currency, i18n.language),
        });
      }
      if (acc.balance_updated_at) {
        rows.push({
          label: t("accounts.balanceUpdated"),
          value: new Intl.DateTimeFormat(i18n.language, {
            dateStyle: "medium",
            timeStyle: "short",
          }).format(new Date(acc.balance_updated_at)),
        });
      }
    } else if (detail?.kind === "connection") {
      rows.push({
        label: t("connections.source"),
        value: t(`connections.providers.${detail.connection.provider}`, {
          defaultValue: detail.connection.name,
        }),
      });
    }
    if (activeConnection) {
      for (const [k, v] of Object.entries(activeConnection.public_fields)) {
        if (k === "bank_brand") continue;
        if (v) rows.push({ label: fieldLabel(k, t), value: v });
      }
    }
    return rows;
  })();

  return (
    <div className="space-y-6">
      <BackPageHeader title={t("accounts.title")}>
        <Button
          variant="outline"
          className="h-9 shrink-0 gap-1.5 rounded-xl px-3 text-xs"
          aria-label={t("accounts.refreshAll")}
          aria-busy={refreshingAll}
          title={t("accounts.refreshAll")}
          disabled={refreshingAll || accounts.some((account) => isSyncing(account.id, statusByAccount[account.id]))}
          onClick={() => void onRefreshAll()}
        >
          {refreshingAll ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <RefreshCw className="h-4 w-4" aria-hidden />
          )}
          <span>{t("accounts.refresh")}</span>
        </Button>
        <Button
          variant="outline"
          className="h-9 w-9 shrink-0 p-0 text-lg leading-none"
          aria-label={t("accounts.addConnection")}
          onClick={openAddDialog}
        >
          +
        </Button>
      </BackPageHeader>

      {message && <p className="text-sm text-accent">{message}</p>}
      {error && <p className="text-sm text-danger">{error}</p>}

      <div className="glass-surface divide-y divide-border/50 overflow-hidden rounded-2xl text-card-foreground">
        {accounts.map((acc) => {
          const st = statusByAccount[acc.id];
          const conn = connectionForAccount(acc);
          const typeLabel = t(`accountTypes.${acc.account_type}`, {
            defaultValue: acc.account_type,
          });
          const balanceUpdated = acc.balance_updated_at
            ? new Intl.DateTimeFormat(i18n.language, {
                dateStyle: "short",
                timeStyle: "short",
              }).format(new Date(acc.balance_updated_at))
            : null;
          return (
            <button
              key={acc.id}
              type="button"
              onClick={() => openAccountDetail(acc)}
              className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left transition hover:bg-muted/60"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted/60 text-muted-foreground">
                  <AccountIcon
                    source={acc.source}
                    provider={conn?.provider}
                    accountType={acc.account_type}
                    bankBrand={conn?.public_fields.bank_brand}
                    bankName={conn?.public_fields.bank_name || conn?.name}
                    bic={conn?.public_fields.bank_bic}
                  />
                </span>
                <div className="min-w-0">
                  <p className="truncate font-medium">{acc.name}</p>
                  <p className="truncate text-xs text-muted-foreground">{typeLabel}</p>
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1.5">
                {acc.current_balance != null && (
                  <p className="whitespace-nowrap text-sm font-semibold tabular-nums text-foreground">
                    {formatMoney(acc.current_balance, acc.currency, i18n.language)}
                  </p>
                )}
                <p className="whitespace-nowrap text-[0.65rem] text-muted-foreground/80">
                  {balanceUpdated
                    ? t("accounts.lastUpdated", { value: balanceUpdated })
                    : t("accounts.neverUpdated")}
                </p>
                <StatusBadge
                  activity={syncActivity(acc.id, st)}
                  error={st?.status === "error" || !!st?.last_error}
                />
              </div>
            </button>
          );
        })}

        {orphanConnections.map((conn) => (
          <button
            key={`conn-${conn.id}`}
            type="button"
            onClick={() => openConnectionDetail(conn)}
            className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left transition hover:bg-muted/60"
          >
            <div className="flex min-w-0 items-center gap-3">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted/60 text-muted-foreground">
                <AccountIcon
                  source={conn.source}
                  provider={conn.provider}
                  bankBrand={conn.public_fields.bank_brand}
                  bankName={conn.public_fields.bank_name || conn.name}
                  bic={conn.public_fields.bank_bic}
                />
              </span>
              <div className="min-w-0">
                <p className="truncate font-medium">{conn.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {t(`connections.providers.${conn.provider}`, {
                    defaultValue: conn.name,
                  })}
                </p>
              </div>
            </div>
            <StatusBadge
              activity={refreshingConnectionIds.has(conn.id) ? "running" : null}
              error={Boolean(conn.last_error)}
            />
          </button>
        ))}

        {accounts.length === 0 && orphanConnections.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-muted-foreground">
            {t("accounts.empty")}
          </p>
        )}
      </div>

      {addOpen && createPortal(
        <div
          className="modal-backdrop z-50 flex items-end justify-center bg-background/80 p-0 sm:items-center sm:bg-background/70 sm:p-4 sm:backdrop-blur-sm"
          onClick={() => setAddOpen(false)}
        >
          <Card
            className="modal-surface max-h-[92dvh] w-full max-w-lg touch-pan-y overflow-y-auto overscroll-contain rounded-b-none px-4 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-4 sm:max-h-[90vh] sm:rounded-[1.65rem] sm:p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-5 flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-muted/55 text-muted-foreground">
                  <Landmark className="h-5 w-5" aria-hidden />
                </span>
                <div className="min-w-0">
                  <h3 className="text-lg font-semibold leading-tight">{t("connections.add")}</h3>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {t("connections.addHint")}
                  </p>
                </div>
              </div>
              <Button
                variant="ghost"
                className="h-9 w-9 shrink-0 rounded-full p-0"
                aria-label={t("common.close")}
                onClick={() => setAddOpen(false)}
              >
                <X className="h-4 w-4" aria-hidden />
              </Button>
            </div>
            <ConnectionForm
              onCreated={async (_connection, syncQueued) => {
                setMessage(
                  t(syncQueued ? "accounts.historyQueued" : "connections.saved"),
                );
                setAddOpen(false);
                load();
                await refreshAccounts();
              }}
            />
          </Card>
        </div>,
        document.body
      )}

      {detail && createPortal(
        <div
          className="modal-backdrop z-50 flex items-end justify-center bg-background/80 p-0 sm:items-center sm:bg-background/70 sm:p-4 sm:backdrop-blur-sm"
          onClick={closeDetail}
        >
          <Card
            className="modal-surface max-h-[92dvh] w-full max-w-lg touch-pan-y overflow-y-auto overscroll-contain rounded-b-none px-4 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-4 sm:max-h-[90vh] sm:rounded-[1.65rem] sm:p-5"
            onClick={(e) => e.stopPropagation()}
          >
            {editingSetup && activeConnection ? (
              <>
                <div className="mb-5 flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-muted/55 text-muted-foreground">
                      <AccountIcon
                        source={activeConnection.source}
                        provider={activeConnection.provider}
                        bankBrand={activeConnection.public_fields.bank_brand}
                        bankName={activeConnection.public_fields.bank_name || activeConnection.name}
                        bic={activeConnection.public_fields.bank_bic}
                      />
                    </span>
                    <div>
                      <h3 className="text-lg font-semibold leading-tight">{t("accounts.editSetup")}</h3>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {activeConnection.name}
                      </p>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    className="h-9 w-9 shrink-0 rounded-full p-0"
                    aria-label={t("common.close")}
                    onClick={() => setEditingSetup(false)}
                  >
                    <X className="h-4 w-4" aria-hidden />
                  </Button>
                </div>
                <form className="space-y-5" onSubmit={onSaveSetup}>
                  <section className="rounded-2xl bg-muted/20 p-4">
                    <h4 className="text-sm font-semibold">{t("connections.displaySection")}</h4>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                      {t("connections.displayHint")}
                    </p>
                    <div className="mt-4 space-y-2">
                      <label className="block text-xs font-medium text-muted-foreground">
                        {t("connections.name")}
                      </label>
                      <Input
                        value={editConnName}
                        onChange={(e) => setEditConnName(e.target.value)}
                        required
                      />
                    </div>
                  </section>
                  <section className="rounded-2xl bg-muted/20 p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h4 className="text-sm font-semibold">{t("connections.credentials")}</h4>
                        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                          {editingCredentials
                            ? t("connections.credentialsEditHint")
                            : t("connections.secretsHidden")}
                        </p>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        className="shrink-0"
                        onClick={() => {
                          setEditSecrets({});
                          setEditingCredentials((current) => !current);
                        }}
                      >
                        {editingCredentials
                          ? t("common.cancel")
                          : t("connections.changeCredentials")}
                      </Button>
                    </div>
                    {editingCredentials && (
                      <div className="mt-5 grid gap-4">
                        {detailFields.map(([key, label, secret]) => (
                          <div key={key} className="space-y-2">
                            <label className="block text-xs font-medium text-muted-foreground">
                              {label}
                            </label>
                            {detailProvider === "coinbase" && key === "api_secret" ? (
                              <Textarea
                                className="min-h-32 font-mono text-xs"
                                autoComplete="off"
                                placeholder={t("accounts.leaveBlank")}
                                value={editSecrets[key] || ""}
                                onChange={(e) =>
                                  setEditSecrets((prev) => ({ ...prev, [key]: e.target.value }))
                                }
                              />
                            ) : (
                              <Input
                                type={secret ? "password" : "text"}
                                autoComplete="off"
                                placeholder={t("accounts.leaveBlank")}
                                value={editSecrets[key] || ""}
                                onChange={(e) =>
                                  setEditSecrets((prev) => ({ ...prev, [key]: e.target.value }))
                                }
                              />
                            )}
                            {fieldHint(key, t) && (
                              <FieldHint>{fieldHint(key, t) as string}</FieldHint>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                  <div className="flex justify-end gap-2 border-t border-border/40 pt-4">
                    <Button type="button" variant="ghost" onClick={() => setEditingSetup(false)}>
                      {t("common.cancel")}
                    </Button>
                    <Button type="submit">{t("connections.save")}</Button>
                  </div>
                </form>
              </>
            ) : (
              <>
                <div className="mb-5 flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-muted/55 text-muted-foreground">
                      <AccountIcon
                        source={
                          detail.kind === "account"
                            ? detail.account.source
                            : detail.connection.source
                        }
                        provider={activeConnection?.provider}
                        accountType={detail.kind === "account" ? detail.account.account_type : undefined}
                        bankBrand={activeConnection?.public_fields.bank_brand}
                        bankName={activeConnection?.public_fields.bank_name || activeConnection?.name}
                        bic={activeConnection?.public_fields.bank_bic}
                      />
                    </span>
                    <div className="min-w-0">
                      <h3 className="truncate text-lg font-semibold leading-tight">
                        {detail.kind === "account" ? detail.account.name : detail.connection.name}
                      </h3>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {activeConnection
                          ? t(`connections.providers.${activeConnection.provider}`, {
                              defaultValue: activeConnection.name,
                            })
                          : t("connections.source")}
                      </p>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <StatusBadge
                      activity={
                        detail.kind === "account"
                          ? syncActivity(detail.account.id, statusByAccount[detail.account.id])
                          : refreshingConnectionIds.has(detail.connection.id)
                            ? "running"
                            : null
                      }
                      error={
                        detail.kind === "account"
                          ? statusByAccount[detail.account.id]?.status === "error"
                          : Boolean(detail.connection.last_error)
                      }
                    />
                    <Button
                      variant="ghost"
                      className="h-9 w-9 rounded-full p-0"
                      aria-label={t("common.close")}
                      onClick={closeDetail}
                    >
                      <X className="h-4 w-4" aria-hidden />
                    </Button>
                  </div>
                </div>

                <div className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {detail.kind === "account" && (
                      <Button
                        variant="outline"
                        className="gap-2"
                        onClick={() => onRefresh(detail.account.id)}
                      >
                        {isSyncing(detail.account.id, statusByAccount[detail.account.id]) ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                        ) : (
                          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                        )}
                        {t("accounts.refresh")}
                      </Button>
                    )}
                    {detail.kind === "connection" && (
                      <Button
                        variant="outline"
                        className="gap-2"
                        onClick={() => void onRefreshConnection(detail.connection.id)}
                        disabled={refreshingConnectionIds.has(detail.connection.id)}
                      >
                        {refreshingConnectionIds.has(detail.connection.id) ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                        ) : (
                          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                        )}
                        {t("accounts.refresh")}
                      </Button>
                    )}
                    {activeConnection && (
                      <Button
                        variant="outline"
                        className="gap-2"
                        onClick={() => {
                          setEditConnName(activeConnection.name);
                          setEditSecrets({});
                          setEditingCredentials(false);
                          setEditingSetup(true);
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden />
                        {t("common.edit")}
                      </Button>
                    )}
                </div>

                <section className="space-y-4 rounded-2xl bg-muted/20 p-4">
                  <h4 className="text-sm font-semibold">{t("connections.details")}</h4>
                  {detailRows.length > 0 && (
                    <dl className="space-y-3 text-sm">
                      {detailRows.map((row) => (
                        <div
                          key={`${row.label}-${row.value}`}
                          className="grid gap-0.5 sm:grid-cols-[9rem_minmax(0,1fr)] sm:gap-3"
                        >
                          <dt className="text-xs text-muted-foreground">{row.label}</dt>
                          <dd className="min-w-0 break-words font-medium sm:break-all">{row.value}</dd>
                        </div>
                      ))}
                    </dl>
                  )}

                  {detail.kind === "account" && (
                    <div className="space-y-2 text-xs text-muted-foreground">
                    <p>
                      {t("accounts.bookingRange", {
                        from:
                          statusByAccount[detail.account.id]?.earliest_booking_date ||
                          t("common.emDash"),
                        to:
                          statusByAccount[detail.account.id]?.latest_booking_date ||
                          t("common.emDash"),
                      })}
                    </p>
                    <button type="button" className="font-medium text-muted-foreground underline underline-offset-2 hover:text-foreground" onClick={() => setHistoryOpen((value) => !value)}>
                      {t("accounts.extendHistory")}
                    </button>
                    {historyOpen && (
                      <div className="flex flex-col gap-2 pt-1 sm:flex-row sm:items-end">
                        <Input type="date" value={backfillFrom} onChange={(e) => setBackfillFrom(e.target.value)} />
                        <Button type="button" variant="outline" onClick={() => detail && void onBackfill(detail)}>{t("accounts.loadHistory")}</Button>
                      </div>
                    )}
                    </div>
                  )}

                  {detail.kind === "account" &&
                    statusByAccount[detail.account.id]?.last_error && (
                      <p className="text-sm text-danger">
                        {statusByAccount[detail.account.id]?.last_error}
                      </p>
                    )}

                </section>

                {(activeConnection || detail.kind === "account") && (
                  <div className="mt-5 flex items-center justify-end gap-3 border-t border-border/40 pt-4">
                    <Button type="button" variant="ghost" className="gap-2 text-danger" disabled={deleting} onClick={() => void onDelete()}>
                      <Trash2 className="h-3.5 w-3.5" aria-hidden />
                      {deleting ? t("connections.deleting") : t("connections.delete")}
                    </Button>
                  </div>
                )}
              </>
            )}
          </Card>
        </div>,
        document.body
      )}
    </div>
  );
}
