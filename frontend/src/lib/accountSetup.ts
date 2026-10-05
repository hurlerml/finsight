import {
  api,
  type Account,
  type Connection,
  type ConnectionSyncStatus,
  type SyncProgress,
  type SyncStatus,
} from "@/api/client";

export const ACCOUNT_SETUP_LONG_RUNNING_MS = 60_000;

export class AccountSetupFailedError extends Error {
  constructor(message = "account_setup_failed") {
    super(message);
    this.name = "AccountSetupFailedError";
  }
}

export function isAccountSyncActive(status?: SyncStatus): boolean {
  if (!status) return false;
  if (status.status === "running" || status.status === "backfilling") {
    return true;
  }
  if (status.latest_job_status === "running" || status.latest_job_status === "pending") {
    return true;
  }
  return (status.pending_jobs ?? 0) > 0;
}

export function isSyncProgressActive(progress: SyncProgress | null): boolean {
  if (!progress) return false;
  return (
    progress.awaiting_user_action ||
    progress.phase === "running" ||
    progress.phase === "awaiting_user_action"
  );
}

export function accountsForConnection(
  accounts: Account[],
  connectionId: number,
): Account[] {
  return accounts.filter((account) => account.connection_id === connectionId);
}

export function connectionSyncStatusFor(
  statuses: ConnectionSyncStatus[],
  connectionId: number,
): ConnectionSyncStatus | undefined {
  return statuses.find((status) => status.connection_id === connectionId);
}

export function connectionHasActiveSync(
  status?: ConnectionSyncStatus,
): boolean {
  if (!status) return false;
  return status.pending_jobs > 0 || status.running_jobs > 0;
}

export function connectionSetupFailed(
  connection: Connection | undefined,
  status?: ConnectionSyncStatus,
): boolean {
  if (connectionHasActiveSync(status)) {
    return false;
  }
  if (connection?.last_error) {
    return true;
  }
  if (status?.latest_job_status === "failed") {
    return true;
  }
  return false;
}

export function isConnectionInitialSyncPending(
  connectionId: number,
  accounts: Account[],
  connections: { id: number }[],
  syncStatuses: SyncStatus[],
  connectionSyncStatuses: ConnectionSyncStatus[],
): boolean {
  if (!connections.some((connection) => connection.id === connectionId)) {
    return false;
  }
  const connectionSync = connectionSyncStatusFor(
    connectionSyncStatuses,
    connectionId,
  );
  if (connectionHasActiveSync(connectionSync)) {
    return true;
  }
  const linked = accountsForConnection(accounts, connectionId);
  if (linked.length === 0) {
    return false;
  }
  return linked.some((account) =>
    isAccountSyncActive(
      syncStatuses.find((status) => status.account_id === account.id),
    ),
  );
}

export function isAnyAccountSetupInProgress(
  accounts: Account[],
  connections: { id: number }[],
  syncStatuses: SyncStatus[],
  connectionSyncStatuses: ConnectionSyncStatus[],
): boolean {
  if (connections.length === 0) {
    return false;
  }
  if (connectionSyncStatuses.some(connectionHasActiveSync)) {
    return true;
  }
  if (accounts.length === 0) {
    return false;
  }
  return accounts.some((account) =>
    isAccountSyncActive(
      syncStatuses.find((status) => status.account_id === account.id),
    ),
  );
}

const sleep = (ms: number) => new Promise<void>((resolve) => {
  window.setTimeout(resolve, ms);
});

export async function waitForConnectionInitialSync(
  connectionId: number,
  onUpdate?: () => Promise<void>,
  timeoutMs = ACCOUNT_SETUP_LONG_RUNNING_MS,
): Promise<"complete" | "still-running"> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const [accounts, connections, syncStatuses, connectionSyncStatuses, progress] =
        await Promise.all([
          api.accounts(),
          api.connections(),
          api.syncStatus(),
          api.connectionSyncStatus(),
          api.syncProgress(),
        ]);
      await onUpdate?.();
      if (!isConnectionInitialSyncPending(
        connectionId,
        accounts,
        connections,
        syncStatuses,
        connectionSyncStatuses,
      )) {
        const connection = connections.find((item) => item.id === connectionId);
        const connectionSync = connectionSyncStatusFor(
          connectionSyncStatuses,
          connectionId,
        );
        if (connectionSetupFailed(connection, connectionSync)) {
          throw new AccountSetupFailedError(
            connection?.last_error ||
              connectionSync?.latest_job_error ||
              "account_setup_failed",
          );
        }
        return "complete";
      }
      const interval = progress.awaiting_user_action ? 1500 : 2500;
      await sleep(interval);
    } catch (error) {
      if (error instanceof AccountSetupFailedError) {
        throw error;
      }
      // A transient request failure must not turn an active server-side sync
      // into a destructive retry flow. Keep polling until the soft deadline.
      await sleep(2500);
    }
  }
  return "still-running";
}
